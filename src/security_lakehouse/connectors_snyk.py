"""Snyk vulnerability evidence collector (read-only REST API).

Verified 2026-10-24 against the OpenAPI document Snyk serves at
``https://api.snyk.io/rest/openapi/2026-03-25`` and docs.snyk.io:

* Auth: ``Authorization: token <API token>`` (the spec's ``APIToken`` scheme).
  Personal tokens and service-account tokens both use it.
* Hosts: one per Snyk region (docs.snyk.io "Regional hosting and data
  residency"); a token works only against its own region and gets 401 elsewhere.
* ``GET /rest/orgs`` (GA 2024-02-28), ``GET /rest/orgs/{org_id}/projects`` (GA
  2024-05-31) with ``meta.latest_issue_counts=true``, and
  ``GET /rest/orgs/{org_id}/issues`` (GA 2024-01-23). None changed after those
  releases, so the pinned ``version=2024-10-15`` (Snyk's recommended version)
  serves the shapes the 2026-03-25 document describes.
* Pagination: ``limit`` 10-100 and an opaque ``starting_after`` cursor carried in
  ``links.next``. Only the cursor is read from that link; the request is always
  rebuilt on the configured regional host.
* Rate limit: 1,620 requests per minute per API key; excess requests get HTTP 429.
  The docs name no retry header, so a ``Retry-After`` is honored when present and
  exponential backoff applies otherwise.
* "Last tested": Snyk's v1-to-REST projects migration guide maps v1
  ``lastTestedDate`` to ``meta.latest_issue_counts.updated_at``.

Only vulnerability evidence is bound: ``package_vulnerability`` (open source and
container dependencies) and ``code`` (first-party code) issues. License, IaC
configuration, cloud, custom, and secrets issues are counted, not evaluated.
Descriptions, code flows, and dependency coordinates are never stored.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorAccessError, ConnectorConfigError
from security_lakehouse.connector_ids import stable_id_slug
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import IncompleteCollectionError, object_rows, paginate
from security_lakehouse.io import read_json
from security_lakehouse.models import utc_iso
from security_lakehouse.timeutil import parse_iso

SOURCE = "snyk"
DEFAULT_TIMEOUT = 30
API_VERSION = "2024-10-15"
DEFAULT_REGION = "SNYK-US-01"
SNYK_REGIONS: dict[str, str] = {
    "SNYK-US-01": "api.snyk.io",
    "SNYK-US-02": "api.us.snyk.io",
    "SNYK-EU-01": "api.eu.snyk.io",
    "SNYK-AU-01": "api.au.snyk.io",
}
PAGE_LIMIT = 100
DEFAULT_MAX_PAGES = 200
MAX_PAGES_CEILING = 1000
DEFAULT_MAX_TEST_AGE = timedelta(days=7)

# Every tag is a requirement SG-VULNERABILITYMANAGEMENT-001 maps to, so a
# verdict row never carries a framework claim outside the bound safeguard.
VULNERABILITY_CONTROLS = ["SOC2-CC7.1", "ISO27001-A.8.8", "NIST-800-53-RA-5", "NIST-800-53-SI-2"]
VULNERABILITY_SAFEGUARD = "SG-VULNERABILITYMANAGEMENT-001"
VULNERABILITY_ISSUE_TYPES = frozenset({"package_vulnerability", "code"})
# OS package managers of container image projects; other project types scan source.
CONTAINER_PROJECT_TYPES = frozenset({"apk", "deb", "rpm", "linux"})
SEVERITIES = ("critical", "high", "medium", "low", "info")
MAX_PROBLEM_IDS = 20

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_GAP_PERMISSION = "View Organization, View Project"


def api_host(region: str | None) -> str:
    """Map a Snyk region code (or its exact API hostname) to the allowlisted host."""
    value = str(region or DEFAULT_REGION).strip()
    host = SNYK_REGIONS.get(value.upper())
    if host is None and value.lower() in SNYK_REGIONS.values():
        host = value.lower()
    if host is None:
        raise ConnectorConfigError(
            f"unknown Snyk region {value!r}; expected one of {', '.join(SNYK_REGIONS)} or its API hostname"
        )
    return host


def region_label(host: str) -> str:
    return next(code for code, value in SNYK_REGIONS.items() if value == host)


def require_uuid(value: Any, *, label: str) -> str:
    text = str(value or "").strip()
    if not _UUID.match(text):
        raise ValueError(f"Snyk collection incomplete: {label} is not a UUID")
    return text.lower()


class SnykClient:
    """Read-only Snyk REST client for one region."""

    def __init__(
        self,
        region: str | None,
        *,
        token: str,
        timeout: int = DEFAULT_TIMEOUT,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self.host = api_host(region)
        self.region = region_label(self.host)
        self.timeout = timeout
        self.max_pages = max_pages
        self._token = token

    def __repr__(self) -> str:
        return f"SnykClient(region={self.region!r})"

    def orgs(self) -> list[dict[str, Any]]:
        return self._list("/orgs", {}, kind="organizations")

    def projects(self, org_id: str) -> list[dict[str, Any]]:
        return self._list(
            f"/orgs/{require_uuid(org_id, label='org id')}/projects",
            {"meta.latest_issue_counts": "true"},
            kind="projects",
            org_id=org_id,
        )

    def issues(self, org_id: str) -> list[dict[str, Any]]:
        return self._list(f"/orgs/{require_uuid(org_id, label='org id')}/issues", {}, kind="issues", org_id=org_id)

    def _list(self, path: str, query: dict[str, str], *, kind: str, org_id: str | None = None) -> list[dict[str, Any]]:
        def fetch_page(cursor: str | None) -> dict[str, Any]:
            params = {"version": API_VERSION, "limit": str(PAGE_LIMIT), **query}
            if cursor:
                params["starting_after"] = cursor
            return self._get(path, params, kind=kind, org_id=org_id)

        return list(paginate(fetch_page, _data, _next_cursor, max_pages=self.max_pages))

    def _get(self, path: str, query: dict[str, str], *, kind: str, org_id: str | None) -> dict[str, Any]:
        url = f"https://{self.host}/rest{path}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "accept": "application/vnd.api+json",
                "authorization": f"token {self._token}",
                "user-agent": "grc-lake",
            },
        )
        try:
            payload = backoff.http_retry(lambda: self._open(request))
        except urllib.error.HTTPError as exc:
            raise self._http_failure(exc.code, kind=kind, org_id=org_id) from None
        if not isinstance(payload, dict):
            raise ValueError(f"Snyk collection incomplete: non-object JSON for {kind}")
        return payload

    def _http_failure(self, code: int, *, kind: str, org_id: str | None) -> Exception:
        if code == 401:
            return ConnectorAccessError(
                f"Snyk rejected the API token (HTTP 401); check the token and that it belongs to region {self.region}"
            )
        if code in {403, 404} and org_id:
            return CollectionGapError(
                f"Snyk {kind} for organization {org_id} were not collected (HTTP {code})",
                collection=f"{kind}:{org_id}",
                reason="permission_denied" if code == 403 else "not_found",
                api="Snyk REST",
                permission=_GAP_PERMISSION,
            )
        return ConnectorAccessError(f"Snyk API request for {kind} failed (HTTP {code})")

    def _open(self, request: urllib.request.Request) -> Any:
        with netguard.open_public(request, timeout=self.timeout, label="snyk") as resp:
            return read_json_response(resp)


class SnykFixtureClient:
    """Offline client backed by orgs.json, projects.json, and issues.json API pages."""

    def __init__(self, fixture_dir: str | Path, *, region: str | None = None) -> None:
        self.fixture = Path(fixture_dir)
        self.host = api_host(region)
        self.region = region_label(self.host)

    def orgs(self) -> list[dict[str, Any]]:
        return self._read("orgs.json")

    def projects(self, org_id: str) -> list[dict[str, Any]]:
        return [row for row in self._read("projects.json") if _related_id(row, "organization") == org_id]

    def issues(self, org_id: str) -> list[dict[str, Any]]:
        return [row for row in self._read("issues.json") if _related_id(row, "organization") == org_id]

    def _read(self, name: str) -> list[dict[str, Any]]:
        path = self.fixture / name
        payload = read_json(path) if path.exists() else {"data": []}
        return _data(payload if isinstance(payload, dict) else {"data": payload})


def collect_snyk_evidence(
    client: SnykClient | SnykFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    org_ids: list[str] | None = None,
    max_test_age: timedelta = DEFAULT_MAX_TEST_AGE,
) -> list[dict[str, Any]]:
    """Per active project: one test-coverage row plus one row per vulnerability issue."""
    now = collected_at or datetime.now(UTC)
    wanted = [_config_uuid(value) for value in org_ids] if org_ids else None
    listed = {require_uuid(org.get("id"), label="org id"): org for org in client.orgs()}
    rows: list[dict[str, Any]] = []
    selected = list(listed) if wanted is None else [org_id for org_id in wanted if org_id in listed]
    for org_id in wanted or []:
        if org_id not in listed:
            gap = CollectionGapError(
                f"Snyk organization {org_id} is not visible to this token",
                collection=f"organization:{org_id}",
                reason="not_accessible",
                api="Snyk REST",
                permission=_GAP_PERMISSION,
            )
            rows.append(_gap_event(client, org_id, gap, now, tenant_id))
    for org_id in selected:
        rows.extend(
            _collect_org(client, org_id, listed[org_id], now=now, tenant_id=tenant_id, max_test_age=max_test_age)
        )
    return rows


def _collect_org(
    client: SnykClient | SnykFixtureClient,
    org_id: str,
    org: dict[str, Any],
    *,
    now: datetime,
    tenant_id: str,
    max_test_age: timedelta,
) -> list[dict[str, Any]]:
    org_attrs = org.get("attributes") or {}
    org_info = {"org_id": org_id, "org_name": org_attrs.get("name"), "org_slug": org_attrs.get("slug")}
    try:
        projects = client.projects(org_id)
    except (CollectionGapError, IncompleteCollectionError) as exc:
        return [_gap_event(client, org_id, _as_gap(exc, "projects", org_id), now, tenant_id)]
    rows: list[dict[str, Any]] = []
    issues_complete = True
    try:
        issues = client.issues(org_id)
    except (CollectionGapError, IncompleteCollectionError) as exc:
        rows.append(_gap_event(client, org_id, _as_gap(exc, "issues", org_id), now, tenant_id))
        issues, issues_complete = [], False
    issues = _first_per_id(issues)

    by_id = {require_uuid(p.get("id"), label="project id"): p for p in projects}
    active = {pid: p for pid, p in by_id.items() if (p.get("attributes") or {}).get("status") == "active"}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped: Counter[str] = Counter()
    for issue in issues:
        scan_item = ((issue.get("relationships") or {}).get("scan_item") or {}).get("data") or {}
        if scan_item.get("type") != "project":
            skipped["non_project_issue_count"] += 1
            continue
        project_id = str(scan_item.get("id") or "").lower()
        if project_id in active:
            grouped[project_id].append(issue)
        elif project_id in by_id:
            skipped["inactive_project_issue_count"] += 1
        else:
            skipped["unmatched_issue_count"] += 1

    for project_id, project in active.items():
        project_issues = grouped.get(project_id, [])
        vulnerabilities = [i for i in project_issues if _attrs(i).get("type") in VULNERABILITY_ISSUE_TYPES]
        skipped["non_vulnerability_issue_count"] += len(project_issues) - len(vulnerabilities)
        info = {**org_info, **_project_attributes(project_id, project)}
        entity = _project_entity(client, org_id, project_id, project)
        for issue in vulnerabilities:
            rows.append(_issue_event(client, entity, info, issue, now, tenant_id))
        rows.append(
            _project_event(
                client,
                entity,
                info,
                project,
                project_issues,
                vulnerabilities,
                issues_complete=issues_complete,
                now=now,
                tenant_id=tenant_id,
                max_test_age=max_test_age,
            )
        )
    rows.append(
        _org_event(
            client,
            org_id,
            {
                **org_info,
                "project_count": len(by_id),
                "active_project_count": len(active),
                "inactive_project_count": len(by_id) - len(active),
                "issues_complete": issues_complete,
                "listed_issue_count": len(issues),
                "non_project_issue_count": skipped["non_project_issue_count"],
                "inactive_project_issue_count": skipped["inactive_project_issue_count"],
                "unmatched_issue_count": skipped["unmatched_issue_count"],
                "non_vulnerability_issue_count": skipped["non_vulnerability_issue_count"],
            },
            now,
            tenant_id,
        )
    )
    return rows


def _project_attributes(project_id: str, project: dict[str, Any]) -> dict[str, Any]:
    attrs = project.get("attributes") or {}
    meta = project.get("meta") or {}
    recurring = ((attrs.get("settings") or {}).get("recurring_tests") or {}).get("frequency")
    return {
        "project_id": project_id,
        "project_name": attrs.get("name"),
        "project_type": attrs.get("type"),
        "project_origin": attrs.get("origin"),
        "target_file": attrs.get("target_file"),
        "target_reference": attrs.get("target_reference"),
        "project_created_at": attrs.get("created"),
        "business_criticality": list(attrs.get("business_criticality") or []),
        "lifecycle": list(attrs.get("lifecycle") or []),
        "project_environment": list(attrs.get("environment") or []),
        "recurring_test_frequency": recurring,
        "cli_monitored_at": meta.get("cli_monitored_at"),
    }


def _project_entity(client: Any, org_id: str, project_id: str, project: dict[str, Any]) -> dict[str, Any]:
    project_type = str((project.get("attributes") or {}).get("type") or "").lower()
    return {
        "asset_id": f"{SOURCE}:project:{project_id}",
        "asset_type": "container_image" if project_type in CONTAINER_PROJECT_TYPES else "repo",
        "asset_owner": org_id,
        "environment": "prod",
        "org": org_id,
    }


def _project_event(
    client: Any,
    entity: dict[str, Any],
    info: dict[str, Any],
    project: dict[str, Any],
    project_issues: list[dict[str, Any]],
    vulnerabilities: list[dict[str, Any]],
    *,
    issues_complete: bool,
    now: datetime,
    tenant_id: str,
    max_test_age: timedelta,
) -> dict[str, Any]:
    counts_meta = (project.get("meta") or {}).get("latest_issue_counts") or {}
    last_tested = parse_iso(counts_meta.get("updated_at"), lenient=True)
    reported_total = sum(_count(counts_meta.get(level)) for level in ("critical", "high", "medium", "low"))
    if not issues_complete:
        reason = "issue_collection_incomplete"
    elif last_tested is None:
        reason = "never_tested"
    elif now - last_tested > max_test_age:
        reason = "not_tested_recently"
    elif reported_total and not project_issues:
        # The latest test counted issues the issues API did not list: never a clean pass.
        reason = "issue_counts_unconfirmed"
    else:
        reason = None
    open_counts = dict.fromkeys(SEVERITIES, 0)
    ignored = resolved = 0
    for issue in vulnerabilities:
        attrs = _attrs(issue)
        if attrs.get("status") == "resolved":
            resolved += 1
        elif attrs.get("ignored") is True:
            ignored += 1
        else:
            open_counts[_severity(attrs)] += 1
    project_id = info["project_id"]
    return _event(
        client=client,
        key=project_id,
        entity=entity,
        signal="project.test_coverage",
        status="pass" if reason is None else "not_evaluated",
        severity="info",
        attributes={
            **info,
            "last_tested_at": utc_iso(last_tested) if last_tested else None,
            "max_test_age_days": max_test_age.days,
            "latest_issue_counts": {
                level: _count(counts_meta.get(level)) for level in ("critical", "high", "medium", "low")
            },
            "open_issue_counts": open_counts,
            "ignored_issue_count": ignored,
            "resolved_issue_count": resolved,
            "non_vulnerability_issue_count": len(project_issues) - len(vulnerabilities),
            "issues_complete": issues_complete,
            "finding_reason": reason,
        },
        evidence_ref=f"https://{client.host}/rest/orgs/{info['org_id']}/projects/{project_id}",
        now=now,
        tenant_id=tenant_id,
        bound=True,
    )


def _issue_event(
    client: Any,
    entity: dict[str, Any],
    info: dict[str, Any],
    issue: dict[str, Any],
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    attrs = _attrs(issue)
    issue_id = require_uuid(issue.get("id"), label="issue id")
    snyk_status = str(attrs.get("status") or "").lower()
    ignored = attrs.get("ignored") is True
    if snyk_status == "resolved":
        status, reason = "resolved", None
    elif snyk_status == "open" and ignored:
        status, reason = "not_evaluated", "ignored_in_snyk"
    elif snyk_status == "open":
        status, reason = "open", None
    else:
        status, reason = "not_evaluated", "unknown_issue_status"
    resolution = attrs.get("resolution") or {}
    created = parse_iso(attrs.get("created_at"), lenient=True)
    resolved_at = parse_iso(resolution.get("resolved_at"), lenient=True)
    end = resolved_at if status == "resolved" and resolved_at else now
    problem_ids = [str(p.get("id")) for p in attrs.get("problems") or [] if isinstance(p, dict) and p.get("id")]
    coordinates = [c for c in attrs.get("coordinates") or [] if isinstance(c, dict)]
    fix_flags = (
        "is_fixable_snyk",
        "is_fixable_upstream",
        "is_fixable_manually",
        "is_upgradeable",
        "is_patchable",
        "is_pinnable",
    )
    seen_flags = [c[flag] for c in coordinates for flag in fix_flags if isinstance(c.get(flag), bool)]
    risk = ((attrs.get("risk") or {}).get("score") or {}).get("value")
    return _event(
        client=client,
        key=f"{info['project_id']}:{issue_id}",
        entity=entity,
        signal="issue",
        status=status,
        severity=_severity(attrs),
        attributes={
            "org_id": info["org_id"],
            "project_id": info["project_id"],
            "project_name": info["project_name"],
            "issue_id": issue_id,
            "issue_key": attrs.get("key"),
            "issue_type": attrs.get("type"),
            "title": attrs.get("title"),
            "effective_severity_level": attrs.get("effective_severity_level"),
            "snyk_status": snyk_status or None,
            "ignored": ignored,
            "created_at": attrs.get("created_at"),
            "updated_at": attrs.get("updated_at"),
            "resolved_at": resolution.get("resolved_at"),
            "resolution_type": resolution.get("type"),
            "age_days": (end - created).days if created else None,
            "problem_ids": problem_ids[:MAX_PROBLEM_IDS],
            "cves": [pid for pid in problem_ids if pid.upper().startswith("CVE-")][:MAX_PROBLEM_IDS],
            "is_fixable": any(seen_flags) if seen_flags else None,
            "risk_score": risk if isinstance(risk, int | float) else None,
            "finding_reason": reason,
        },
        evidence_ref=f"https://{client.host}/rest/orgs/{info['org_id']}/issues/{issue_id}",
        now=now,
        tenant_id=tenant_id,
        bound=True,
    )


def _org_event(client: Any, org_id: str, attributes: dict[str, Any], now: datetime, tenant_id: str) -> dict[str, Any]:
    return _event(
        client=client,
        key=org_id,
        entity=_org_entity(org_id, "vulnerability_scanner_org", f"{SOURCE}:org:{org_id}"),
        signal="org.summary",
        status="observed",
        severity="info",
        attributes={**attributes, "region": client.region},
        evidence_ref=f"https://{client.host}/rest/orgs/{org_id}",
        now=now,
        tenant_id=tenant_id,
        bound=False,
    )


def _gap_event(client: Any, org_id: str, gap: CollectionGapError, now: datetime, tenant_id: str) -> dict[str, Any]:
    """A coverage-gap row: an actionable open item that neither passes nor fails a control."""
    return _event(
        client=client,
        key=f"gap:{gap.collection}",
        entity=_org_entity(org_id, "collection_scope", f"{SOURCE}:collection:{gap.collection}"),
        signal="collection_gap",
        status="not_evaluated",
        severity="low",
        attributes={**gap.attributes(), "org_id": org_id, "region": client.region},
        evidence_ref=f"https://{client.host}/rest/orgs/{org_id}",
        now=now,
        tenant_id=tenant_id,
        bound=False,
    )


def _org_entity(org_id: str, asset_type: str, asset_id: str) -> dict[str, Any]:
    return {"asset_id": asset_id, "asset_type": asset_type, "asset_owner": org_id, "environment": "prod", "org": org_id}


def _event(
    *,
    client: Any,
    key: str,
    entity: dict[str, Any],
    signal: str,
    status: str,
    severity: str,
    attributes: dict[str, Any],
    evidence_ref: str,
    now: datetime,
    tenant_id: str,
    bound: bool,
) -> dict[str, Any]:
    stable = stable_id_slug(f"{client.region}:{signal}:{key}", fallback="snyk")
    row: dict[str, Any] = {
        "event_id": f"{SOURCE}-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": SOURCE,
        "event_type": f"{SOURCE}.{signal}",
        "entity": entity,
        "severity": severity,
        "status": status,
        "controls": list(VULNERABILITY_CONTROLS) if bound else [],
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": attributes,
    }
    if bound:
        row["safeguard_ids"] = [VULNERABILITY_SAFEGUARD]
    return row


def _as_gap(exc: Exception, kind: str, org_id: str) -> CollectionGapError:
    if isinstance(exc, CollectionGapError):
        return exc
    return CollectionGapError(
        f"Snyk {kind} for organization {org_id} exceeded the page budget; coverage is incomplete",
        collection=f"{kind}:{org_id}",
        reason="page_budget_exhausted",
        api="Snyk REST",
    )


def _first_per_id(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A cursor page boundary can repeat an issue; keep the first copy of each id."""
    unique: dict[str, dict[str, Any]] = {}
    for issue in issues:
        unique.setdefault(require_uuid(issue.get("id"), label="issue id"), issue)
    return list(unique.values())


def _data(page: dict[str, Any]) -> list[dict[str, Any]]:
    return object_rows(page.get("data"), label="Snyk")


def _next_cursor(page: dict[str, Any]) -> str | None:
    link = (page.get("links") or {}).get("next")
    if isinstance(link, dict):
        link = link.get("href")
    if not link or not page.get("data"):
        return None
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(str(link)).query).get("starting_after") or []
    if len(values) != 1 or not values[0]:
        raise ValueError("Snyk collection incomplete: next link without a starting_after cursor")
    return values[0]


def _related_id(row: dict[str, Any], name: str) -> str:
    return str((((row.get("relationships") or {}).get(name) or {}).get("data") or {}).get("id") or "").lower()


def _attrs(row: dict[str, Any]) -> dict[str, Any]:
    attrs = row.get("attributes")
    return attrs if isinstance(attrs, dict) else {}


def _severity(attrs: dict[str, Any]) -> str:
    level = str(attrs.get("effective_severity_level") or "").lower()
    return level if level in SEVERITIES else "info"


def _count(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else 0


def parse_sync_options(options: dict[str, Any]) -> tuple[list[str] | None, timedelta, int]:
    """Validate ``org_ids``, ``max_test_age_days`` (1-90), and ``max_pages`` (1-1000)."""
    raw_orgs = options.get("org_ids")
    if raw_orgs in (None, "", []):
        org_ids = None
    else:
        items = raw_orgs.split(",") if isinstance(raw_orgs, str) else raw_orgs
        if not isinstance(items, list):
            raise ConnectorConfigError("snyk-vulnerabilities options.org_ids must be a list of organization UUIDs")
        org_ids = [_config_uuid(item) for item in items if str(item).strip()]
    return (
        org_ids,
        timedelta(days=_bounded_int(options, "max_test_age_days", DEFAULT_MAX_TEST_AGE.days, 90)),
        _bounded_int(options, "max_pages", DEFAULT_MAX_PAGES, MAX_PAGES_CEILING),
    )


def _bounded_int(options: dict[str, Any], name: str, default: int, ceiling: int) -> int:
    raw = options.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw))
    except ValueError:
        value = 0
    if not 1 <= value <= ceiling:
        raise ConnectorConfigError(f"snyk-vulnerabilities options.{name} must be an integer between 1 and {ceiling}")
    return value


def _config_uuid(value: Any) -> str:
    text = str(value or "").strip()
    if not _UUID.match(text):
        raise ConnectorConfigError("snyk-vulnerabilities options.org_ids must be Snyk organization UUIDs")
    return text.lower()


__all__ = [
    "API_VERSION",
    "SNYK_REGIONS",
    "VULNERABILITY_CONTROLS",
    "VULNERABILITY_SAFEGUARD",
    "SnykClient",
    "SnykFixtureClient",
    "api_host",
    "collect_snyk_evidence",
    "parse_sync_options",
]
