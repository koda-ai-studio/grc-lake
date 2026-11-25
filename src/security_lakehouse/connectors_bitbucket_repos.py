"""Read-only Bitbucket Cloud default-branch governance snapshots (Preview)."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows
from security_lakehouse.io import canonical_sha256, read_json
from security_lakehouse.models import utc_iso
from security_lakehouse.repo_governance import CHANGE_APPROVAL_CONTROLS, CHANGE_APPROVAL_SAFEGUARD, GovernanceRepoSpec

CONNECTOR_ID = "bitbucket-repos"
TOKEN_ENV = "BITBUCKET_ACCESS_TOKEN"
API_BASE = "https://api.bitbucket.org/2.0"
REQUIRED = {"require_approvals_to_merge", "force", "delete", "enforce_merge_checks", "push"}


def _gap(collection: str, reason: str) -> CollectionGapError:
    return CollectionGapError("Bitbucket collection incomplete", collection=collection, reason=reason, api="Bitbucket")


def _slug(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError("Invalid Bitbucket workspace or repository slug")
    return value


class BitbucketReposClient:
    def __init__(self, *, token: str, workspace: str, max_pages: int = 100) -> None:
        try:
            self.workspace = _slug(workspace)
        except ValueError:
            raise ConnectorConfigError("Bitbucket workspace must be a slug, not a URL") from None
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ConnectorConfigError("Bitbucket max_pages must be an integer from 1 to 1000")
        self.base = f"{API_BASE}/repositories/{self.workspace}"
        self._token, self.max_pages = token, max_pages

    def get(self, url: str) -> Any:
        request = urllib.request.Request(
            url, method="GET", headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label=CONNECTOR_ID) as response:
                return read_json_response(response)

        try:
            return backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise _gap("repositories", f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise _gap("repositories", "unreadable_response") from None


class BitbucketReposFixtureClient(BitbucketReposClient):
    def __init__(self, fixture_dir: str | Path, *, workspace: str, max_pages: int = 100) -> None:
        super().__init__(token="", workspace=workspace, max_pages=max_pages)
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, url: str) -> Any:
        if url not in self.responses:
            raise _gap("repositories", "fixture_missing")
        return self.responses[url]


def _list(client: BitbucketReposClient, path: str) -> list[dict[str, Any]]:
    base = f"{client.base}{path}"
    url = base + "?pagelen=100"
    rows: list[dict[str, Any]] = []
    pages: set[str] = set()
    records: set[str] = set()
    expected: int | None = None
    for _ in range(client.max_pages):
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "api.bitbucket.org"
            or parsed.path != urllib.parse.urlsplit(base).path
            or parsed.fragment
        ):
            raise _gap(path or "repositories", "unsafe_next_url")
        if url in pages:
            raise _gap(path or "repositories", "repeated_page")
        pages.add(url)
        payload = client.get(url)
        if not isinstance(payload, dict):
            raise _gap(path or "repositories", "invalid_page")
        chunk = object_rows(payload.get("values"), label="Bitbucket")
        if len(chunk) > 100:
            raise _gap(path or "repositories", "invalid_page_size")
        total = payload.get("size")
        if total is not None:
            if type(total) is not int or total < 0 or (expected is not None and expected != total):
                raise _gap(path or "repositories", "invalid_population_count")
            expected = total
        for row in chunk:
            key = canonical_sha256(row)
            if key in records:
                raise _gap(path or "repositories", "duplicate_record")
            records.add(key)
        rows.extend(chunk)
        link = payload.get("next")
        if link is None:
            if expected is not None and len(rows) != expected:
                raise _gap(path or "repositories", "population_count_mismatch")
            return rows
        if not isinstance(link, str) or not link or len(link) > 8192 or not chunk:
            raise _gap(path or "repositories", "invalid_next_page")
        url = link
    raise _gap(path or "repositories", "page_budget_exhausted")


def _matches(pattern: str, branch: str) -> bool:
    parts = pattern.split("*")
    if len(parts) == 1:
        return pattern == branch
    if not branch.startswith(parts[0]) or not branch.endswith(parts[-1]):
        return False
    position = len(parts[0])
    end = len(branch) - len(parts[-1])
    for part in parts[1:-1]:
        found = branch.find(part, position, end)
        if found < 0:
            return False
        position = found + len(part)
    return position <= end


def _evaluate(rules: list[dict[str, Any]], branch: str) -> tuple[str, dict[str, Any]]:
    applicable: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    identifiers: set[int] = set()
    for rule in rules:
        identifier = rule.get("id")
        if type(identifier) is not int or identifier in identifiers:
            unknown.append("invalid_rule_id")
        else:
            identifiers.add(identifier)
        kind = rule.get("kind")
        if not isinstance(kind, str):
            unknown.append("invalid_rule_kind")
            continue
        if kind not in REQUIRED:
            continue
        pattern = rule.get("pattern")
        if rule.get("branch_match_kind") != "glob" or not isinstance(pattern, str) or len(pattern) > 1024:
            unknown.append("unsupported_branch_match")
            continue
        # Bitbucket's documented glob treats only '*' specially; '?' and brackets are literal.
        if not _matches(pattern, branch):
            continue
        if kind in applicable:
            unknown.append("overlapping_restrictions")
        applicable[kind] = rule
    approvals = applicable.get("require_approvals_to_merge", {}).get("value", 0)
    if type(approvals) is not int or approvals < 0:
        unknown.append("unknown_approval_count")
    unmet = sorted(REQUIRED - applicable.keys())
    if type(approvals) is int and approvals == 0 and "require_approvals_to_merge" in applicable:
        unmet.append("required_approving_reviews")
    push = applicable.get("push")
    if push is not None:
        if not isinstance(push.get("users"), list) or not isinstance(push.get("groups"), list):
            unknown.append("unknown_push_exceptions")
        elif push["users"] or push["groups"]:
            unmet.append("direct_push_exceptions")
    attrs = {
        "default_branch": branch,
        "required_approving_review_count": approvals if type(approvals) is int and approvals >= 0 else None,
        "prevent_force_pushes": "force" in applicable,
        "prevent_deletions": "delete" in applicable,
        "enforce_merge_checks": "enforce_merge_checks" in applicable,
        "unmet_requirements": unmet,
        "unknown_requirements": sorted(set(unknown)),
        "restriction_ids": sorted(identifiers),
    }
    return ("not_evaluated" if unknown else "open" if unmet else "pass"), attrs


def collect_bitbucket_repos_evidence(
    client: BitbucketReposClient, *, collected_at: datetime | None = None, tenant_id: str = "customer-managed"
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    try:
        repos = _list(client, "")
        if not repos:
            raise _gap("repositories", "empty_scope")
        slugs = [_slug(r.get("slug")) for r in repos]
        if len(set(slugs)) != len(slugs) or any(
            r.get("full_name") != f"{client.workspace}/{slug}" for r, slug in zip(repos, slugs, strict=True)
        ):
            raise _gap("repositories", "mismatched_repository_scope")
    except (CollectionGapError, ValueError) as exc:
        error = exc if isinstance(exc, CollectionGapError) else _gap("repositories", "invalid_response")
        return [_event(client, "collection", "collection_gap", "not_evaluated", error.attributes(), now, tenant_id)]
    for repo in repos:
        slug = repo["slug"]
        private = repo.get("is_private")
        visibility = {"visibility": "private" if private is True else "public" if private is False else None}
        if type(private) is not bool:
            visibility.update(_gap(slug, "unknown_visibility").attributes())
        rows.append(
            _event(
                client,
                slug,
                "visibility",
                "observed" if type(private) is bool else "not_evaluated",
                visibility,
                now,
                tenant_id,
            )
        )
        main = repo.get("mainbranch")
        branch = main.get("name") if isinstance(main, dict) else None
        try:
            if not isinstance(branch, str) or not branch or len(branch) > 1024:
                raise _gap(slug, "default_branch_not_reported")
            rules = _list(client, f"/{slug}/branch-restrictions")
            status, attrs = _evaluate(rules, branch)
            if status == "not_evaluated":
                attrs.update(_gap(slug, "ambiguous_branch_restrictions").attributes())
        except (CollectionGapError, ValueError) as exc:
            error = exc if isinstance(exc, CollectionGapError) else _gap(slug, "invalid_branch_restrictions")
            status, attrs = "not_evaluated", error.attributes()
        rows.append(_event(client, slug, "change_approval", status, attrs, now, tenant_id))
    return rows


def _event(
    client: BitbucketReposClient,
    slug: str,
    signal: str,
    status: str,
    attrs: dict[str, Any],
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    spec = GovernanceRepoSpec(provider="bitbucket", owner=client.workspace, repo=slug)
    key = canonical_sha256([spec.slug, signal, "bitbucket"])[:32]
    bound = signal == "change_approval"
    gap = signal == "collection_gap"
    return {
        "event_id": f"bitbucket-{key}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": "bitbucket-repo-governance",
        "event_type": f"repository.governance.{signal}",
        "entity": {
            "asset_id": spec.asset_id + ("#default-branch" if bound else ""),
            "asset_type": "repo" if bound else "collection_scope" if gap else "repository",
            "asset_owner": client.workspace,
            "environment": "prod",
            "repo": spec.slug,
            "provider": "bitbucket",
        },
        "status": status,
        "severity": "medium" if status == "open" else "info",
        "controls": list(CHANGE_APPROVAL_CONTROLS) if bound else [],
        "safeguard_ids": [CHANGE_APPROVAL_SAFEGUARD] if bound else [],
        "evidence": {
            "evidence_id": f"ev-{key}",
            "evidence_ref": client.base + ("" if gap else f"/{slug}") + ("/branch-restrictions" if bound else ""),
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": attrs,
    }
