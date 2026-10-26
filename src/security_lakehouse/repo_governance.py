"""Authenticated repository governance evidence collector.

The public repo audit records what can be seen without credentials. This module
collects private/org-only governance signals when a GitHub App installation
token, GitLab access token, or fixture is available and emits the same raw
evidence shape.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from security_lakehouse import netguard
from security_lakehouse.connector_errors import ConnectorAccessError, ConnectorConfigError
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import next_link_url, object_rows, paginate
from security_lakehouse.io import read_json, write_jsonl
from security_lakehouse.models import utc_iso
from security_lakehouse.runtime_environment import runtime_env
from security_lakehouse.secret_refs import resolve_ref_or_default
from security_lakehouse.vocabulary import SEVERITY_ORDER, EventStatus, Severity

# Runaway guard for page-number pagination, matched to the shared paginator so a
# repo with thousands of alerts is not silently truncated.
_MAX_PAGES = 1000


def _guarded_page(request: urllib.request.Request, *, timeout: int, label: str) -> tuple[object, str]:
    """Perform a read-only GET through the SSRF guard, with transient-error retry.

    Routes through ``netguard.open_public`` — same as every other HTTP connector —
    so a redirect from the configured host cannot pivot the request (or its bearer
    token) at an internal address, and a base URL supplied via env/spec is still
    boundary-checked on every hop. Retries 429/5xx (honoring ``Retry-After``); a
    ``204`` keeps its ``{"enabled": True}`` contract.
    """

    def _fetch() -> tuple[object, str]:
        with netguard.open_public(request, timeout=timeout, label=label) as resp:
            if getattr(resp, "status", None) == 204:
                return {"enabled": True}, ""
            return json.loads(resp.read().decode("utf-8")), getattr(resp, "headers", {}).get("Link", "")

    return backoff.http_retry(_fetch)


GITLAB_RE = re.compile(
    r"^(?:https?://(?:[\w.-]+\.)?gitlab\.com/)?(?P<path>[\w./-]+?)(?:\.git)?/?$",
)

CONTROL_MAP = {
    "branch_protection": ["SOC2-CC6.1", "ISO27001-A.5.15", "PCI-DSS-7"],
    "collaborators": ["SOC2-CC6.1", "ISO27001-A.5.15"],
    "teams": ["SOC2-CC6.1", "ISO27001-A.5.15"],
    "workflow_permissions": ["SOC2-CC7.2", "ISO27001-A.8.16"],
    "security_settings": ["SOC2-CC7.2", "PCI-DSS-11", "GDPR-Art.32"],
    "security_findings": ["SOC2-CC7.2", "PCI-DSS-11", "ISO27001-A.8.16"],
}

# The default-branch change-approval verdict binds to the change-approval
# safeguard. Safeguards accept the "repo" asset type, so the verdict is recorded
# on the repository's default branch rather than on the "repository" observation
# asset, which would otherwise carry two asset types and never be assessable.
CHANGE_APPROVAL_SAFEGUARD = "SG-CHANGEAPPROVAL-001"
CHANGE_APPROVAL_CONTROLS = ["SOC2-CC8.1", "ISO27001-A.8.32"]
CHANGE_APPROVAL_CRITERIA = [
    "branch protection readable",
    "required_approving_review_count >= 1",
    "enforce_admins.enabled is true",
    "allow_force_pushes.enabled is false",
    "allow_deletions.enabled is false",
]

GITHUB_READ_ONLY_SCOPES = [
    "metadata:read",
    "administration:read",
    "code_scanning_alerts:read",
    "secret_scanning_alerts:read",
    "dependabot_alerts:read",
]
GITLAB_READ_ONLY_SCOPES = ["read_api", "read_repository", "read_user", "read_registry"]

# Alert endpoint per security signal, and whether it pages only by Link cursors.
# GitHub answers HTTP 400 to `page` on the Dependabot endpoint.
GITHUB_ALERT_ENDPOINTS = {
    "code_scanning": ("code-scanning/alerts", False),
    "secret_scanning": ("secret-scanning/alerts", False),
    "dependabot": ("dependabot/alerts", True),
}
# GitHub's documented 403/404 bodies when a feature is off for the repository:
# "Advanced Security must be enabled", "no analysis found", "Secret scanning is
# disabled", "Dependabot alerts are disabled".
_SIGNAL_NOT_ENABLED = re.compile(r"not enabled|disabled|must be enabled|no analysis found", re.IGNORECASE)


@dataclass(frozen=True)
class GovernanceRepoSpec:
    provider: str
    owner: str
    repo: str

    @property
    def slug(self) -> str:
        if self.provider == "gitlab" and "/" in self.owner:
            return f"{self.owner}/{self.repo}"
        if self.provider == "gitlab":
            return f"{self.owner}/{self.repo}"
        return f"{self.owner}/{self.repo}"

    @property
    def asset_id(self) -> str:
        return f"{self.provider}:repo:{self.slug}"


class GovernanceClient(Protocol):
    def repo(self) -> dict[str, Any]:
        pass

    def branch_protection(self, branch: str) -> dict[str, Any] | list[dict[str, Any]]:
        pass

    def collaborators(self) -> list[dict[str, Any]]:
        pass

    def teams(self) -> list[dict[str, Any]]:
        pass

    def workflow_permissions(self) -> dict[str, Any]:
        pass

    def vulnerability_alerts(self) -> dict[str, Any]:
        pass

    def security_findings(self) -> dict[str, Any]:
        pass


def parse_governance_repo_spec(value: str, *, provider: str | None = None) -> GovernanceRepoSpec:
    raw = value.strip()
    detected = provider
    if detected is None:
        lowered = raw.lower()
        if "gitlab" in lowered:
            detected = "gitlab"
        elif "github" in lowered:
            detected = "github"
        else:
            detected = "github"
    if detected == "gitlab":
        match = GITLAB_RE.match(raw)
        if not match:
            raise ValueError("repo must be a GitLab URL or NAMESPACE/PROJECT")
        parts = [part for part in match.group("path").split("/") if part]
        if len(parts) < 2:
            raise ValueError("GitLab repo must include namespace and project")
        return GovernanceRepoSpec(provider="gitlab", owner="/".join(parts[:-1]), repo=parts[-1])
    from security_lakehouse.repo_audit import parse_repo_spec

    spec = parse_repo_spec(raw)
    return GovernanceRepoSpec(provider="github", owner=spec.owner, repo=spec.repo)


class GitHubGovernanceClient:
    def __init__(self, spec: GovernanceRepoSpec, *, token: str) -> None:
        self.spec = spec
        self.token = token

    def repo(self) -> dict[str, Any]:
        return self._json(f"https://api.github.com/repos/{self.spec.slug}")

    def branch_protection(self, branch: str) -> dict[str, Any]:
        return self._json(f"https://api.github.com/repos/{self.spec.slug}/branches/{branch}/protection")

    def collaborators(self) -> list[dict[str, Any]]:
        return self._json_list_paginated(f"https://api.github.com/repos/{self.spec.slug}/collaborators")

    def teams(self) -> list[dict[str, Any]]:
        return self._json_list_paginated(f"https://api.github.com/repos/{self.spec.slug}/teams")

    def workflow_permissions(self) -> dict[str, Any]:
        return self._json(f"https://api.github.com/repos/{self.spec.slug}/actions/permissions/workflow")

    def vulnerability_alerts(self) -> dict[str, Any]:
        return self._json(f"https://api.github.com/repos/{self.spec.slug}/vulnerability-alerts")

    def security_findings(self) -> dict[str, Any]:
        base = f"https://api.github.com/repos/{self.spec.slug}"
        findings: dict[str, Any] = {}
        for signal, (path, cursor_only) in GITHUB_ALERT_ENDPOINTS.items():
            reader = self._json_list_cursor if cursor_only else self._json_list_paginated
            findings[signal] = _safe_call(lambda reader=reader, path=path: reader(f"{base}/{path}"))
        return findings

    def probe_signals(self) -> dict[str, dict[str, Any]]:
        """Read one page of each alert endpoint the sync collects, without following continuations.

        Each request has the sync's shape for that endpoint (page numbers or
        cursor-only), so a request the sync cannot make fails here as well.
        """
        base = f"https://api.github.com/repos/{self.spec.slug}"
        signals: dict[str, dict[str, Any]] = {}
        for signal, (path, cursor_only) in GITHUB_ALERT_ENDPOINTS.items():
            url = f"{base}/{path}?per_page=1" + ("" if cursor_only else "&page=1")
            signals[signal] = _probe_signal(signal, lambda url=url: object_rows(self._request(url), label="GitHub"))
        return signals

    def _json(self, url: str) -> dict[str, Any]:
        payload = self._request(url)
        if isinstance(payload, dict):
            return payload
        raise ValueError(f"GitHub returned non-object JSON for {url}")

    def _json_list_paginated(self, url: str, *, max_pages: int = _MAX_PAGES) -> list[dict[str, Any]]:
        """Read a paginated GitHub list endpoint without silently truncating.

        ``max_pages`` is a runaway guard, not an expected ceiling — matched to the
        shared paginator so a repo with thousands of alerts is not dropped at 1000.
        """
        rows: list[dict[str, Any]] = []
        seen_pages: set[str] = set()
        separator = "&" if "?" in url else "?"
        for page in range(1, max_pages + 1):
            payload = self._request(f"{url}{separator}per_page=100&page={page}")
            if not isinstance(payload, list):
                raise ValueError(f"GitHub returned non-list JSON for {url}")
            if any(not isinstance(item, dict) for item in payload):
                raise ValueError("GitHub list contains a non-object item")
            fingerprint = _sha(payload)
            if payload and fingerprint in seen_pages:
                raise ValueError("GitHub returned a repeated page; collection is incomplete")
            seen_pages.add(fingerprint)
            rows.extend(payload)
            if len(payload) < 100:
                return rows
        raise ValueError("GitHub page limit reached; collection is incomplete")

    def _json_list_cursor(self, url: str, *, max_pages: int = _MAX_PAGES) -> list[dict[str, Any]]:
        """Read a GitHub list that pages only through ``Link`` cursors (``before``/``after``).

        The next link may use the numeric ``/repositories/{id}`` form, so only the
        same scheme, host and endpoint tail are accepted before the token is sent.
        """
        origin = urllib.parse.urlsplit(url)
        prefix = f"/repos/{self.spec.slug}"
        tail = origin.path.removeprefix(prefix)
        allowed = re.compile(rf"^(?:{re.escape(prefix)}|/repositories/\d+){re.escape(tail)}$")
        first_url = f"{url}{'&' if '?' in url else '?'}per_page=100"
        seen_pages: set[str] = set()

        def fetch(cursor: str | None) -> tuple[list[dict[str, Any]], str, str]:
            current = cursor or first_url
            target = urllib.parse.urlsplit(current)
            if (target.scheme, target.netloc) != (origin.scheme, origin.netloc) or not allowed.match(target.path):
                raise ValueError("GitHub collection incomplete: unexpected pagination endpoint")
            payload, link = self._request_page(current)
            rows = object_rows(payload, label="GitHub")
            fingerprint = _sha(rows)
            if rows and fingerprint in seen_pages:
                raise ValueError("GitHub collection incomplete: repeated page")
            seen_pages.add(fingerprint)
            return rows, link, current

        def next_cursor(page: tuple[list[dict[str, Any]], str, str]) -> str | None:
            _rows, link, current = page
            next_url = next_link_url(link)
            return urllib.parse.urljoin(current, next_url) if next_url else None

        return list(paginate(fetch, lambda page: page[0], next_cursor, start_cursor=first_url, max_pages=max_pages))

    def _request(self, url: str) -> object:
        return self._request_page(url)[0]

    def _request_page(self, url: str) -> tuple[object, str]:
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/vnd.github+json",
                "authorization": f"Bearer {self.token}",
                "user-agent": "grc-lake",
            },
        )
        return _guarded_page(request, timeout=20, label="github api")


class GitLabGovernanceClient:
    def __init__(self, spec: GovernanceRepoSpec, *, token: str, base_url: str | None = None) -> None:
        self.spec = spec
        self.token = token
        self.api_base = (base_url or runtime_env().get("GRC_LAKE_GITLAB_API_URL", "https://gitlab.com/api/v4")).rstrip(
            "/"
        )
        self.project_id = urllib.parse.quote(self.spec.slug, safe="")

    def repo(self) -> dict[str, Any]:
        project = self._json(f"{self.api_base}/projects/{self.project_id}")
        return {
            "default_branch": project.get("default_branch") or "main",
            "full_name": project.get("path_with_namespace") or self.spec.slug,
            "name": project.get("name") or self.spec.repo,
            "private": project.get("visibility") != "public",
            "visibility": project.get("visibility") or "private",
            "project_id": project.get("id"),
        }

    def branch_protection(self, branch: str) -> dict[str, Any]:
        branches = self._json_list(f"{self.api_base}/projects/{self.project_id}/protected_branches")
        match = next((item for item in branches if str(item.get("name")) == branch), None)
        if match is None:
            return {
                "available": False,
                "requires_scope_or_permission": True,
                "reason": f"no protected branch rule for {branch}",
            }
        return _normalize_gitlab_branch_protection(match)

    def collaborators(self) -> list[dict[str, Any]]:
        members = self._json_list(f"{self.api_base}/projects/{self.project_id}/members/all")
        return [
            {
                "login": item.get("username") or item.get("name") or "unknown",
                "role_name": _gitlab_access_label(int(item.get("access_level") or 0)),
                "permissions": {"access_level": item.get("access_level")},
            }
            for item in members
        ]

    def teams(self) -> list[dict[str, Any]]:
        groups = self._json_list(f"{self.api_base}/projects/{self.project_id}/groups")
        return [
            {
                "name": item.get("full_name") or item.get("name") or "unknown",
                "permission": _gitlab_access_label(int(item.get("group_access_level") or 0)),
                "privacy": item.get("visibility") or "private",
            }
            for item in groups
        ]

    def workflow_permissions(self) -> dict[str, Any]:
        project = self._json(f"{self.api_base}/projects/{self.project_id}")
        restricted = bool(project.get("restrict_user_defined_variables"))
        return {
            "default_workflow_permissions": "read" if restricted else "write",
            "can_approve_pull_request_reviews": bool(project.get("only_allow_merge_if_all_discussions_are_resolved")),
            "only_allow_merge_if_pipeline_succeeds": bool(project.get("only_allow_merge_if_pipeline_succeeds")),
        }

    def vulnerability_alerts(self) -> dict[str, Any]:
        project = self._json(f"{self.api_base}/projects/{self.project_id}")
        enabled = bool(project.get("security_and_compliance_enabled"))
        return {"enabled": enabled, "security_and_compliance_enabled": enabled}

    def security_findings(self) -> dict[str, Any]:
        # GitLab exposes vulnerability detail through tier- and permission-dependent
        # APIs. Keep this signal honest until a stable read contract is configured.
        return {
            "available": False,
            "requires_scope_or_permission": True,
            "reason": "GitLab vulnerability findings require a supported security tier and API scope",
        }

    def _json(self, url: str) -> dict[str, Any]:
        payload = self._request(url)
        if isinstance(payload, dict):
            return payload
        raise ValueError(f"GitLab returned non-object JSON for {url}")

    def _json_list(self, url: str, *, max_pages: int = _MAX_PAGES) -> list[dict[str, Any]]:
        origin = urllib.parse.urlsplit(url)
        first_url = f"{url}{'&' if '?' in url else '?'}per_page=100"
        seen_pages: set[str] = set()

        def fetch(cursor: str | None) -> tuple[list[dict[str, Any]], str, str]:
            current = cursor or first_url
            target = urllib.parse.urlsplit(current)
            if (target.scheme, target.netloc, target.path) != (origin.scheme, origin.netloc, origin.path):
                raise ValueError("GitLab collection incomplete: unexpected pagination endpoint")
            payload, link = self._request_page(current)
            rows = object_rows(payload, label="GitLab")
            fingerprint = _sha(rows)
            if rows and fingerprint in seen_pages:
                raise ValueError("GitLab collection incomplete: repeated page")
            seen_pages.add(fingerprint)
            return rows, link, current

        def next_cursor(page: tuple[list[dict[str, Any]], str, str]) -> str | None:
            rows, link, current = page
            next_url = next_link_url(link)
            if next_url:
                return urllib.parse.urljoin(current, next_url)
            if len(rows) < 100:
                return None
            # GitLab may omit pagination headers. A full page still needs a
            # subsequent read before completeness can be established.
            parts = urllib.parse.urlsplit(current)
            query = urllib.parse.parse_qs(parts.query)
            query["page"] = [str(int(query.get("page", ["1"])[0]) + 1)]
            return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query, doseq=True)))

        return list(paginate(fetch, lambda page: page[0], next_cursor, start_cursor=first_url, max_pages=max_pages))

    def _request(self, url: str) -> object:
        return self._request_page(url)[0]

    def _request_page(self, url: str) -> tuple[object, str]:
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "private-token": self.token,
                "user-agent": "grc-lake",
            },
        )
        return _guarded_page(request, timeout=20, label="gitlab api")


def _gitlab_access_label(level: int) -> str:
    if level >= 50:
        return "owner"
    if level >= 40:
        return "maintainer"
    if level >= 30:
        return "developer"
    if level >= 20:
        return "reporter"
    return "guest"


def _normalize_gitlab_branch_protection(payload: dict[str, Any]) -> dict[str, Any]:
    approvals = int(payload.get("approvals_before_merge") or payload.get("required_approving_review_count") or 0)
    contexts = [str(item.get("name")) for item in payload.get("status_checks") or [] if isinstance(item, dict)]
    return {
        "required_pull_request_reviews": {
            "required_approving_review_count": approvals,
            "require_code_owner_reviews": bool(payload.get("code_owner_approval_required")),
        },
        "required_status_checks": {"strict": True, "contexts": contexts},
        "enforce_admins": {"enabled": bool(payload.get("allow_force_push") is False)},
    }


class FixtureGovernanceClient:
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture = Path(fixture_dir)

    def repo(self) -> dict[str, Any]:
        return read_json(self.fixture / "repo.json")

    def branch_protection(self, _branch: str) -> dict[str, Any]:
        return self._read("branch_protection.json")

    def collaborators(self) -> list[dict[str, Any]]:
        payload = self._read("collaborators.json")
        return payload if isinstance(payload, list) else payload.get("collaborators", [])

    def teams(self) -> list[dict[str, Any]]:
        payload = self._read("teams.json")
        return payload if isinstance(payload, list) else payload.get("teams", [])

    def workflow_permissions(self) -> dict[str, Any]:
        return self._read("workflow_permissions.json")

    def vulnerability_alerts(self) -> dict[str, Any]:
        return self._read("vulnerability_alerts.json")

    def security_findings(self) -> dict[str, Any]:
        return self._read("security_findings.json")

    def probe_signals(self) -> dict[str, dict[str, Any]]:
        findings = self.security_findings()
        signals: dict[str, dict[str, Any]] = {}
        for signal in GITHUB_ALERT_ENDPOINTS:
            payload = findings.get(signal) if isinstance(findings, dict) else None
            if isinstance(payload, list):
                signals[signal] = {"status": "readable"}
            else:
                status = payload.get("http_status") if isinstance(payload, dict) else None
                signals[signal] = {"status": "forbidden", **({"http_status": status} if status else {})}
        return signals

    def _read(self, name: str) -> Any:
        path = self.fixture / name
        return read_json(path) if path.exists() else {"available": False}


def sync_repo_governance(
    repo: str,
    *,
    out: str | Path | None = None,
    fixture_dir: str | Path | None = None,
    token: str | None = None,
    token_env: str | None = None,
    provider: str | None = None,
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    spec = parse_governance_repo_spec(repo, provider=provider)
    secret = _resolve_token(spec, token=token, token_env=token_env)
    client: GovernanceClient
    if fixture_dir:
        client = FixtureGovernanceClient(fixture_dir)
    elif secret:
        if spec.provider == "gitlab":
            client = GitLabGovernanceClient(spec, token=secret)
        else:
            client = GitHubGovernanceClient(spec, token=secret)
    else:
        raise ValueError("repo governance sync requires --fixture-dir or an authenticated access token")

    repo_data = client.repo()
    now = collected_at or datetime.now(UTC)
    rows = _build_events(
        spec,
        repo_data,
        client,
        now,
        credential_fingerprint=_fingerprint(secret) if secret else "fixture",
    )
    if out:
        write_jsonl(out, rows)
    return rows


def _resolve_token(spec: GovernanceRepoSpec, *, token: str | None, token_env: str | None) -> str | None:
    if token:
        return token
    default_env = (
        "GRC_LAKE_GITLAB_ACCESS_TOKEN" if spec.provider == "gitlab" else "GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN"
    )
    return resolve_ref_or_default(token_env, default_env, dict(runtime_env()), field="credential_ref", file_first=False)


def probe_github_access(*, credentials: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Prove the configured token can read the repository and each security signal the sync collects.

    The token is resolved as ``run_connector_sync`` resolves it: the stored
    ``credential_ref``, else ``options.token_env``, else the provider default
    variable. A literal ``token`` is never read, because sync never reads one.
    Repository metadata must be readable. Each alert endpoint then gets one
    request and reports ``readable``, ``forbidden`` or ``not_enabled``; any
    other HTTP failure fails the probe, as it fails the sync.
    """
    repo = str(options.get("repo") or "").strip()
    if not repo:
        raise ConnectorConfigError("github-security probe requires options.repo set to the repository owner and name")
    spec = parse_governance_repo_spec(repo, provider="github")
    fixture_dir = options.get("fixture_dir")
    client: GitHubGovernanceClient | FixtureGovernanceClient
    if fixture_dir:
        client = FixtureGovernanceClient(fixture_dir)
    else:
        ref = str(credentials.get("credential_ref") or options.get("token_env") or "").strip() or None
        secret = _resolve_token(spec, token=None, token_env=ref)
        if not secret:
            raise ConnectorConfigError(
                "no GitHub token resolved: set credential_ref to the environment variable or secret "
                "that holds the installation token"
            )
        client = GitHubGovernanceClient(spec, token=secret)
    try:
        repo_data = client.repo()
    except urllib.error.HTTPError as exc:
        raise ConnectorAccessError(
            f"GitHub repository metadata is not readable with the configured token (HTTP {exc.code})"
        ) from None
    # A list, not a mapping: run records redact any key containing "secret",
    # which would blank the secret_scanning entry.
    signals = [{"signal": signal, **access} for signal, access in client.probe_signals().items()]
    return {
        "ok": True,
        "repo": spec.slug,
        "credential_mode": "fixture" if fixture_dir else "access_token",
        "default_branch": str(repo_data.get("default_branch") or "") or None,
        "capabilities": ["metadata:read"],
        "signals": signals,
        "partial": any(signal["status"] != "readable" for signal in signals),
    }


def _probe_signal(signal: str, read: Any) -> dict[str, Any]:
    try:
        read()
    except urllib.error.HTTPError as exc:
        if exc.code not in {401, 403, 404}:
            raise ConnectorAccessError(
                f"GitHub {signal} read failed (HTTP {exc.code}); sync would fail the same way"
            ) from None
        status = "not_enabled" if _SIGNAL_NOT_ENABLED.search(_http_error_message(exc)) else "forbidden"
        return {"status": status, "http_status": exc.code}
    return {"status": "readable"}


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError, AttributeError):
        # No readable JSON body; classify on the status code alone.
        return ""
    return str(payload.get("message") or "") if isinstance(payload, dict) else ""


def _build_events(
    spec: GovernanceRepoSpec,
    repo: dict[str, Any],
    client: GovernanceClient,
    collected_at: datetime,
    *,
    credential_fingerprint: str,
) -> list[dict[str, Any]]:
    branch = str(repo.get("default_branch") or "main")
    scopes = GITLAB_READ_ONLY_SCOPES if spec.provider == "gitlab" else GITHUB_READ_ONLY_SCOPES
    source_health = {
        "credential_fingerprint": credential_fingerprint,
        "credential_boundary": (
            "gitlab_access_token_or_fixture"
            if spec.provider == "gitlab"
            else "github_app_installation_token_or_fixture"
        ),
        "minimum_scopes": scopes,
        "collected_at": utc_iso(collected_at),
        "provider": spec.provider,
    }
    evidence_ref = (
        f"https://gitlab.com/api/v4/projects/{urllib.parse.quote(spec.slug, safe='')}"
        if spec.provider == "gitlab"
        else f"https://api.github.com/repos/{spec.slug}"
    )
    signal_payloads = {
        "branch_protection": _safe_call(lambda: client.branch_protection(branch)),
        "collaborators": _safe_call(client.collaborators),
        "teams": _safe_call(client.teams),
        "workflow_permissions": _safe_call(client.workflow_permissions),
        "security_settings": _safe_call(client.vulnerability_alerts),
        "security_findings": _safe_call(client.security_findings),
    }
    rows = [
        _event(
            spec,
            collected_at,
            signal=signal,
            event_type=f"repository.governance.{signal}",
            controls=CONTROL_MAP[signal],
            evidence_ref=evidence_ref,
            attributes={
                "default_branch": branch,
                "source_health": source_health,
                "governance": (
                    _normalize_security_findings(payload)
                    if signal == "security_findings"
                    else _normalize_signal(signal, payload)
                ),
            },
            status=_status_for(payload, signal=signal),
            severity=_findings_severity(payload) if signal == "security_findings" else "info",
        )
        for signal, payload in signal_payloads.items()
    ]
    if spec.provider == "github":
        rows.append(
            _change_approval_event(
                spec,
                collected_at,
                signal_payloads["branch_protection"],
                branch=branch,
                evidence_ref=f"{evidence_ref}/branches/{urllib.parse.quote(branch, safe='')}/protection",
                source_health=source_health,
            )
        )
    return rows


def _flag(payload: dict[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    enabled = value.get("enabled") if isinstance(value, dict) else None
    return enabled if isinstance(enabled, bool) else None


def _evaluate_change_approval(payload: dict[str, Any] | list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    """Return (status, unmet, unknown) for the default branch's change-approval settings.

    An unreadable record is never a pass. A readable record that omits pull
    request reviews requires none; any other missing setting is unknown.
    """
    if not isinstance(payload, dict) or payload.get("available") is False:
        return EventStatus.NOT_EVALUATED.value, [], ["branch_protection_unreadable"]
    unmet: list[str] = []
    unknown: list[str] = []
    reviews = payload.get("required_pull_request_reviews")
    count = reviews.get("required_approving_review_count") if isinstance(reviews, dict) else 0
    if (reviews is not None and not isinstance(reviews, dict)) or isinstance(count, bool) or not isinstance(count, int):
        unknown.append("required_approving_reviews")
    elif count < 1:
        unmet.append("required_approving_reviews")
    for key, expected, label in (
        ("enforce_admins", True, "admins_not_included"),
        ("allow_force_pushes", False, "force_pushes_allowed"),
        ("allow_deletions", False, "deletions_allowed"),
    ):
        enabled = _flag(payload, key)
        if enabled is None:
            unknown.append(key)
        elif enabled is not expected:
            unmet.append(label)
    if unmet:
        return EventStatus.OPEN.value, unmet, unknown
    if unknown:
        return EventStatus.NOT_EVALUATED.value, unmet, unknown
    return EventStatus.PASS.value, unmet, unknown


def _change_approval_event(
    spec: GovernanceRepoSpec,
    collected_at: datetime,
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    branch: str,
    evidence_ref: str,
    source_health: dict[str, Any],
) -> dict[str, Any]:
    status, unmet, unknown = _evaluate_change_approval(payload)
    record = payload if isinstance(payload, dict) else {}
    reviews = record.get("required_pull_request_reviews")
    row = _event(
        spec,
        collected_at,
        signal="change_approval",
        event_type="repository.governance.change_approval",
        controls=CHANGE_APPROVAL_CONTROLS,
        evidence_ref=evidence_ref,
        attributes={
            "default_branch": branch,
            "source_health": source_health,
            "criteria": CHANGE_APPROVAL_CRITERIA,
            "unmet_requirements": unmet,
            "unknown_requirements": unknown,
            "required_approving_review_count": (
                reviews.get("required_approving_review_count") if isinstance(reviews, dict) else None
            ),
            "http_status": record.get("http_status"),
        },
        status=status,
        severity=Severity.MEDIUM.value if status == EventStatus.OPEN else Severity.INFO.value,
        asset_id=f"{spec.asset_id}#default-branch",
        asset_type="repo",
    )
    row["safeguard_ids"] = [CHANGE_APPROVAL_SAFEGUARD]
    return row


def _safe_call(func: Any) -> dict[str, Any] | list[dict[str, Any]]:
    try:
        return func()
    except urllib.error.HTTPError as exc:
        if exc.code not in {401, 403, 404}:
            # Transient failures exhausted their retry budget. Fail the sync
            # instead of publishing them as an ordinary permission gap.
            raise
        return {
            "available": False,
            "requires_scope_or_permission": True,
            "http_status": exc.code,
            "reason": "authenticated API did not authorize this signal",
        }


def _normalize_signal(signal: str, payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(payload, list):
        return {
            "signal": signal,
            "available": True,
            "count": len(payload),
            "items": [_redact_item(item) for item in payload],
        }
    if payload.get("available") is False:
        return {"signal": signal, **payload}
    return {"signal": signal, "available": True, **_redact_item(payload)}


def _normalize_security_findings(payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    """Emit aggregate alert posture without copying secret- or code-bearing details."""

    if not isinstance(payload, dict) or payload.get("available") is False:
        return _normalize_signal("security_findings", payload)

    categories: dict[str, Any] = {}
    for category in ("code_scanning", "secret_scanning", "dependabot"):
        alerts = payload.get(category)
        if isinstance(alerts, dict) and alerts.get("available") is False:
            categories[category] = _redact_item(alerts)
            continue
        if not isinstance(alerts, list):
            alerts = []
        states = Counter(str(item.get("state") or "unknown") for item in alerts if isinstance(item, dict))
        severities = Counter(
            severity
            for item in alerts
            if isinstance(item, dict)
            for severity in [_alert_severity(category, item)]
            if severity
        )
        categories[category] = {
            "count": len(alerts),
            "by_state": dict(sorted(states.items())),
            "by_severity": dict(sorted(severities.items())),
        }
    return {"signal": "security_findings", "available": True, "categories": categories}


def _alert_severity(category: str, alert: dict[str, Any]) -> str | None:
    if category == "code_scanning":
        rule = alert.get("rule")
        value = rule.get("security_severity_level") if isinstance(rule, dict) else None
    elif category == "dependabot":
        advisory = alert.get("security_advisory")
        value = advisory.get("severity") if isinstance(advisory, dict) else None
    else:
        value = None
    return str(value).lower() if value else None


def _redact_item(item: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in item.items():
        lowered = key.lower()
        if any(secret in lowered for secret in ("token", "secret", "password", "private_key")):
            redacted[key] = "[redacted]"
        elif isinstance(value, dict):
            redacted[key] = _redact_item(value)
        elif isinstance(value, list):
            redacted[key] = [_redact_item(v) if isinstance(v, dict) else v for v in value]
        else:
            redacted[key] = value
    return redacted


def _open_alerts(payload: dict[str, Any] | list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(payload, dict) or payload.get("available") is False:
        return []
    return [
        (category, alert)
        for category in ("code_scanning", "secret_scanning", "dependabot")
        if isinstance(payload.get(category), list)
        for alert in payload[category]
        if isinstance(alert, dict) and alert.get("state") == EventStatus.OPEN
    ]


def _findings_severity(payload: dict[str, Any] | list[dict[str, Any]]) -> str:
    levels = [_alert_severity(category, alert) or Severity.INFO.value for category, alert in _open_alerts(payload)]
    return max(
        (level for level in levels if level in SEVERITY_ORDER),
        key=SEVERITY_ORDER.__getitem__,
        default=Severity.INFO.value,
    )


def _status_for(payload: dict[str, Any] | list[dict[str, Any]], *, signal: str = "") -> str:
    if isinstance(payload, dict) and payload.get("available") is False:
        return "requires_authenticated_connector"
    if signal == "security_findings" and _open_alerts(payload):
        return EventStatus.OPEN.value
    return EventStatus.OBSERVED.value


def _event(
    spec: GovernanceRepoSpec,
    collected_at: datetime,
    *,
    signal: str,
    event_type: str,
    controls: list[str],
    evidence_ref: str,
    attributes: dict[str, Any],
    status: str,
    severity: str = "info",
    asset_id: str | None = None,
    asset_type: str = "repository",
) -> dict[str, Any]:
    stable = _sha({"repo": spec.slug, "signal": signal, "provider": spec.provider})[:16]
    evidence_body = {"event_type": event_type, "evidence_ref": evidence_ref, "attributes": attributes}
    source = "gitlab-repo-governance" if spec.provider == "gitlab" else "github-repo-governance"
    return {
        "event_id": f"repo-governance-{stable}",
        "tenant_id": f"github:{spec.owner}" if spec.provider == "github" else "customer-managed",
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": source,
        "event_type": event_type,
        "entity": {
            "asset_id": asset_id or spec.asset_id,
            "asset_type": asset_type,
            "asset_owner": spec.owner,
            "environment": "prod",
            "repo": spec.slug,
            "provider": spec.provider,
        },
        "severity": severity,
        "status": status,
        "controls": controls,
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(collected_at),
            "raw_sha256": _sha(evidence_body),
        },
        "attributes": attributes,
    }


def _fingerprint(secret: str | None) -> str:
    if not secret:
        return "none"
    return f"sha256:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:12]}"


def _sha(value: object) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
