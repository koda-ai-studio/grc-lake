"""Snyk vulnerability connector tests (fixture-backed + fake Snyk REST API).

Fixture and fake-API shapes follow the Snyk REST OpenAPI document served at
``https://api.snyk.io/rest/openapi/2026-03-25`` (checked 2026-10-24); the
endpoints used were last changed at GA versions 2024-02-28 (``GET /orgs``),
2024-05-31 (``GET /orgs/{org_id}/projects``) and 2024-01-23
(``GET /orgs/{org_id}/issues``), so the pinned ``version=2024-10-15`` serves the
same shapes: JSON:API ``data``/``links`` envelopes, cursor pagination through a
``starting_after`` parameter in ``links.next``, and ``limit`` 10-100.
"""

from __future__ import annotations

import copy
import io
import json
import time
import urllib.error
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import connectors_snyk, netguard
from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.connector_errors import ConnectorAccessError, ConnectorConfigError
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event, configure_payload_error, latest_run
from security_lakehouse.connectors_snyk import (
    API_VERSION,
    SNYK_REGIONS,
    VULNERABILITY_CONTROLS,
    VULNERABILITY_SAFEGUARD,
    SnykClient,
    SnykFixtureClient,
    api_host,
    collect_snyk_evidence,
)
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.safeguards import load_safeguards
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures" / "snyk"
COLLECTED = datetime(2026, 6, 3, tzinfo=UTC)
HOST = "api.snyk.io"
TOKEN = "snyk-test-token-0f9e8d7c"  # synthetic; must never appear in evidence or errors
ORG = "0a1b2c3d-0000-4000-8000-000000000001"
OTHER_ORG = "0a1b2c3d-0000-4000-8000-000000000002"


def _pid(n: int) -> str:
    return f"0a1b2c3d-0000-4000-8000-1000000000{n:02d}"


def _iid(n: int) -> str:
    return f"0a1b2c3d-0000-4000-8000-3000000000{n:02d}"


def _rows(**kwargs: Any) -> list[dict[str, Any]]:
    return collect_snyk_evidence(SnykFixtureClient(FIXTURE), collected_at=COLLECTED, **kwargs)


def _by_type(rows: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [row for row in rows if row["event_type"] == event_type]


def _project_row(rows: list[dict[str, Any]], n: int) -> dict[str, Any]:
    [row] = [
        r for r in _by_type(rows, "snyk.project.test_coverage") if r["entity"]["asset_id"] == f"snyk:project:{_pid(n)}"
    ]
    return row


def _issue_row(rows: list[dict[str, Any]], n: int) -> dict[str, Any]:
    [row] = [r for r in _by_type(rows, "snyk.issue") if r["attributes"]["issue_id"] == _iid(n)]
    return row


# --- evidence mapping -----------------------------------------------------------------


def test_fixture_collection_emits_project_issue_and_org_rows() -> None:
    rows = _rows()
    assert validate_raw_events(rows) == []
    # 8 projects: one inactive is skipped. 7 issues: the inactive project's, the
    # environment-scoped one, and the license one are not vulnerability evidence.
    assert len(_by_type(rows, "snyk.project.test_coverage")) == 7
    assert {r["attributes"]["issue_id"] for r in _by_type(rows, "snyk.issue")} == {_iid(1), _iid(2), _iid(3), _iid(5)}
    assert len(_by_type(rows, "snyk.org.summary")) == 1
    assert _by_type(rows, "snyk.collection_gap") == []
    assert len(rows) == 12
    assert len({row["event_id"] for row in rows}) == len(rows)


@pytest.mark.parametrize(
    ("n", "status", "reason"),
    [
        (1, "pass", None),
        (2, "pass", None),
        (3, "not_evaluated", "not_tested_recently"),
        (4, "pass", None),
        (5, "pass", None),
        (7, "not_evaluated", "never_tested"),
        (8, "not_evaluated", "issue_counts_unconfirmed"),
    ],
)
def test_project_test_coverage_status(n: int, status: str, reason: str | None) -> None:
    row = _project_row(_rows(), n)
    assert row["status"] == status
    assert row["attributes"]["finding_reason"] == reason
    assert row["safeguard_ids"] == [VULNERABILITY_SAFEGUARD]


def test_a_project_without_issues_passes_only_when_recently_tested() -> None:
    rows = _rows(max_test_age=timedelta(hours=1))
    clean = _project_row(rows, 2)
    assert clean["status"] == "not_evaluated"
    assert clean["attributes"]["finding_reason"] == "not_tested_recently"
    assert clean["attributes"]["last_tested_at"] == "2026-06-02T06:00:00Z"


@pytest.mark.parametrize(
    ("n", "status", "severity", "reason"),
    [
        (1, "open", "high", None),
        (2, "resolved", "medium", None),
        (3, "not_evaluated", "medium", "ignored_in_snyk"),
        (5, "resolved", "critical", None),
    ],
)
def test_issue_status_and_severity(n: int, status: str, severity: str, reason: str | None) -> None:
    row = _issue_row(_rows(), n)
    assert (row["status"], row["severity"], row["attributes"]["finding_reason"]) == (status, severity, reason)
    assert row["safeguard_ids"] == [VULNERABILITY_SAFEGUARD]
    assert row["controls"] == VULNERABILITY_CONTROLS


def test_ignored_issue_never_counts_as_a_pass() -> None:
    row = _issue_row(_rows(), 3)
    assert row["attributes"]["ignored"] is True
    assert row["status"] not in {"pass", "passed", "resolved", "closed", "compliant", "observed"}


def test_issue_rows_carry_sla_relevant_fields() -> None:
    rows = _rows()
    open_issue = _issue_row(rows, 1)["attributes"]
    assert open_issue["created_at"] == "2026-05-20T08:00:00Z"
    assert open_issue["age_days"] == 13
    assert open_issue["resolved_at"] is None
    assert open_issue["is_fixable"] is True
    assert open_issue["problem_ids"] == ["SNYK-JS-EXAMPLE-1001", "CVE-2026-0001"]
    assert open_issue["cves"] == ["CVE-2026-0001"]
    assert open_issue["project_name"] == "example/payments-api:package.json"
    resolved = _issue_row(rows, 2)["attributes"]
    assert resolved["resolved_at"] == "2026-04-15T08:00:00Z"
    assert resolved["resolution_type"] == "fixed"
    assert resolved["age_days"] == 14  # created to resolved, not to collection time


def test_project_rows_summarize_issue_counts_and_asset_types() -> None:
    rows = _rows()
    payments = _project_row(rows, 1)
    assert payments["entity"]["asset_type"] == "repo"
    assert payments["attributes"]["open_issue_counts"] == {"critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0}
    assert payments["attributes"]["resolved_issue_count"] == 1
    infra = _project_row(rows, 4)["attributes"]
    assert infra["ignored_issue_count"] == 1
    assert infra["non_vulnerability_issue_count"] == 1
    assert _project_row(rows, 5)["entity"]["asset_type"] == "container_image"


def test_org_summary_counts_what_was_not_turned_into_evidence() -> None:
    [summary] = _by_type(_rows(), "snyk.org.summary")
    assert summary["status"] == "observed"
    assert "safeguard_ids" not in summary
    attrs = summary["attributes"]
    assert attrs["project_count"] == 8
    assert attrs["active_project_count"] == 7
    assert attrs["inactive_project_count"] == 1
    assert attrs["non_project_issue_count"] == 1
    assert attrs["inactive_project_issue_count"] == 1
    assert attrs["non_vulnerability_issue_count"] == 1
    assert attrs["issues_complete"] is True


def test_controls_and_safeguard_binding_fit_the_crosswalk() -> None:
    catalog_ids = set(load_control_catalog())
    assert set(VULNERABILITY_CONTROLS) <= catalog_ids
    [safeguard] = [row for row in load_safeguards()["safeguards"] if row["safeguard_id"] == VULNERABILITY_SAFEGUARD]
    assert set(VULNERABILITY_CONTROLS) <= {member["control_id"] for member in safeguard["satisfies"]}
    for row in _rows():
        if row.get("safeguard_ids"):
            assert row["entity"]["asset_type"] in safeguard["asset_types"], row["event_type"]


def test_evidence_is_minimized_and_never_carries_the_token() -> None:
    rows = _rows()
    text = json.dumps(rows)
    assert "Synthetic description" not in text
    assert "example-lib" not in text  # dependency coordinates are not stored
    assert TOKEN not in text
    for row in rows:
        assert row["evidence"]["evidence_ref"].startswith(f"https://{HOST}/rest/orgs/{ORG}")


# --- region allowlist -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("region", "host"),
    [
        (None, "api.snyk.io"),
        ("SNYK-US-01", "api.snyk.io"),
        ("snyk-us-02", "api.us.snyk.io"),
        ("SNYK-EU-01", "api.eu.snyk.io"),
        ("SNYK-AU-01", "api.au.snyk.io"),
        ("api.eu.snyk.io", "api.eu.snyk.io"),
    ],
)
def test_region_selects_an_allowlisted_api_host(region: str | None, host: str) -> None:
    assert api_host(region) == host


@pytest.mark.parametrize(
    "region", ["https://api.snyk.io", "api.snyk.io.evil.example", "169.254.169.254", "localhost", "SNYK-GOV-01"]
)
def test_unknown_region_is_rejected(region: str) -> None:
    with pytest.raises(ConnectorConfigError):
        api_host(region)
    assert set(SNYK_REGIONS.values()) == {"api.snyk.io", "api.us.snyk.io", "api.eu.snyk.io", "api.au.snyk.io"}


# --- live client against a fake Snyk REST API -------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _http_error(url: str, code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    import email.message

    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(url, code, "error", message, io.BytesIO(b'{"errors":[{"detail":"nope"}]}'))


def _page(data: list[dict[str, Any]], cursor: str | None = None, *, next_link: str | None = None) -> dict[str, Any]:
    links: dict[str, Any] = {}
    if next_link is not None:
        links["next"] = next_link
    elif cursor is not None:
        links["next"] = f"/orgs/{ORG}/issues?version={API_VERSION}&limit=100&starting_after={cursor}"
    return {"jsonapi": {"version": "1.0"}, "data": data, "links": links}


def _fixture_data(name: str) -> list[dict[str, Any]]:
    return copy.deepcopy(read_json(FIXTURE / name)["data"])


class _FakeSnyk:
    """Routes ``(path, starting_after)`` to queued responses and records requests."""

    def __init__(self, routes: dict[tuple[str, str | None], list[Any]]) -> None:
        self.routes = routes
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: Any, *, timeout: Any = None, label: str = "") -> _Response:
        self.requests.append(request)
        parsed = urllib.parse.urlsplit(request.full_url)
        assert parsed.scheme == "https"
        query = urllib.parse.parse_qs(parsed.query)
        key = (parsed.path, (query.get("starting_after") or [None])[0])
        queue = self.routes[key]
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return _Response(json.dumps(item).encode())


def _default_routes() -> dict[tuple[str, str | None], list[Any]]:
    return {
        ("/rest/orgs", None): [_page(_fixture_data("orgs.json"))],
        (f"/rest/orgs/{ORG}/projects", None): [_page(_fixture_data("projects.json"))],
        (f"/rest/orgs/{ORG}/issues", None): [_page(_fixture_data("issues.json"))],
    }


def _client(**kwargs: Any) -> SnykClient:
    return SnykClient("SNYK-US-01", token=TOKEN, **kwargs)


def test_live_client_sends_token_auth_jsonapi_accept_and_pinned_version(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeSnyk(_default_routes())
    monkeypatch.setattr(netguard, "open_public", fake)
    rows = collect_snyk_evidence(_client(), collected_at=COLLECTED)
    assert rows == _rows()
    assert [urllib.parse.urlsplit(r.full_url).path for r in fake.requests] == [
        "/rest/orgs",
        f"/rest/orgs/{ORG}/projects",
        f"/rest/orgs/{ORG}/issues",
    ]
    for request in fake.requests:
        parsed = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(parsed.query)
        assert parsed.hostname == HOST
        assert query["version"] == [API_VERSION] and query["limit"] == ["100"]
        assert request.get_header("Authorization") == f"token {TOKEN}"
        assert request.get_header("Accept") == "application/vnd.api+json"
        assert request.get_method() == "GET"
    projects_query = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.requests[1].full_url).query)
    assert projects_query["meta.latest_issue_counts"] == ["true"]


def test_live_client_follows_starting_after_cursor_on_the_fixed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = _fixture_data("issues.json")
    routes = _default_routes()
    # The second next link names another host: only its cursor is used.
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [_page(issues[:3], "c1")]
    routes[(f"/rest/orgs/{ORG}/issues", "c1")] = [
        _page(issues[3:5], next_link="https://evil.example/rest/orgs/x/issues?starting_after=c2")
    ]
    routes[(f"/rest/orgs/{ORG}/issues", "c2")] = [_page(issues[5:])]
    fake = _FakeSnyk(routes)
    monkeypatch.setattr(netguard, "open_public", fake)
    rows = collect_snyk_evidence(_client(), collected_at=COLLECTED)
    assert rows == _rows()
    assert all(urllib.parse.urlsplit(r.full_url).hostname == HOST for r in fake.requests)
    assert len(fake.requests) == 5


def test_an_issue_repeated_across_pages_is_counted_once(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = _fixture_data("issues.json")
    routes = _default_routes()
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [_page(issues, "c1")]
    routes[(f"/rest/orgs/{ORG}/issues", "c1")] = [_page(issues[:1])]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    rows = collect_snyk_evidence(_client(), collected_at=COLLECTED)
    assert rows == _rows()
    assert _project_row(rows, 1)["attributes"]["open_issue_counts"]["high"] == 1


def test_next_link_without_a_cursor_fails_instead_of_truncating(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = _default_routes()
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [_page(_fixture_data("issues.json")[:2], next_link="/orgs/x/issues")]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    with pytest.raises(ValueError, match="collection incomplete"):
        collect_snyk_evidence(_client(), collected_at=COLLECTED)


@pytest.mark.parametrize("bad", [{"data": "not-a-list"}, {"data": [{"id": "x"}, "malformed"]}, {"links": {}}])
def test_malformed_pages_fail_instead_of_shrinking_inventory(monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    routes = _default_routes()
    routes[(f"/rest/orgs/{ORG}/projects", None)] = [bad]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    with pytest.raises(ValueError, match="collection incomplete"):
        collect_snyk_evidence(_client(), collected_at=COLLECTED)


def test_page_budget_exhaustion_is_an_explicit_gap_not_a_smaller_success(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = _fixture_data("issues.json")
    routes = _default_routes()
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [_page(issues[:1], "c1")]
    routes[(f"/rest/orgs/{ORG}/issues", "c1")] = [_page(issues[1:2], "c2")]
    routes[(f"/rest/orgs/{ORG}/issues", "c2")] = [_page(issues[2:])]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    rows = collect_snyk_evidence(_client(max_pages=2), collected_at=COLLECTED)
    [gap] = _by_type(rows, "snyk.collection_gap")
    assert gap["attributes"]["collection_gap"] is True
    assert gap["attributes"]["reason"] == "page_budget_exhausted"
    assert gap["status"] == "not_evaluated"
    assert "safeguard_ids" not in gap and gap["controls"] == []
    # Partial issues never become per-issue evidence or a project pass.
    assert _by_type(rows, "snyk.issue") == []
    projects = _by_type(rows, "snyk.project.test_coverage")
    assert projects and {r["status"] for r in projects} == {"not_evaluated"}
    assert {r["attributes"]["finding_reason"] for r in projects} == {"issue_collection_incomplete"}


def test_rate_limit_waits_for_retry_after_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    routes = _default_routes()
    url = f"https://{HOST}/rest/orgs/{ORG}/issues"
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [
        _http_error(url, 429, {"Retry-After": "7"}),
        _page(_fixture_data("issues.json")),
    ]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    assert collect_snyk_evidence(_client(), collected_at=COLLECTED) == _rows()
    assert sleeps == [7.0]


def test_persistent_rate_limit_fails_closed_without_leaking_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    routes = _default_routes()
    url = f"https://{HOST}/rest/orgs?version={API_VERSION}"
    routes[("/rest/orgs", None)] = [_http_error(url, 429, {"Retry-After": "1"})]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    with pytest.raises(ConnectorAccessError) as exc:
        collect_snyk_evidence(_client(), collected_at=COLLECTED)
    assert "429" in str(exc.value)
    assert TOKEN not in str(exc.value) and "/" not in str(exc.value)


def test_rejected_token_fails_closed_and_names_the_region(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = _default_routes()
    routes[("/rest/orgs", None)] = [_http_error(f"https://{HOST}/rest/orgs", 401)]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    with pytest.raises(ConnectorAccessError, match="401") as exc:
        collect_snyk_evidence(_client(), collected_at=COLLECTED)
    assert "SNYK-US-01" in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_forbidden_org_issues_become_a_gap_and_block_project_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = _default_routes()
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [_http_error(f"https://{HOST}/rest/orgs/{ORG}/issues", 403)]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    rows = collect_snyk_evidence(_client(), collected_at=COLLECTED)
    [gap] = _by_type(rows, "snyk.collection_gap")
    assert gap["attributes"]["reason"] == "permission_denied"
    assert gap["attributes"]["collection"] == f"issues:{ORG}"
    assert {r["status"] for r in _by_type(rows, "snyk.project.test_coverage")} == {"not_evaluated"}
    [summary] = _by_type(rows, "snyk.org.summary")
    assert summary["attributes"]["issues_complete"] is False


def test_requested_org_outside_the_token_scope_is_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(_default_routes()))
    rows = collect_snyk_evidence(_client(), collected_at=COLLECTED, org_ids=[ORG, OTHER_ORG])
    [gap] = _by_type(rows, "snyk.collection_gap")
    assert gap["attributes"]["reason"] == "not_accessible"
    assert gap["attributes"]["collection"] == f"organization:{OTHER_ORG}"
    assert len(_by_type(rows, "snyk.project.test_coverage")) == 7


@pytest.mark.parametrize("org_id", ["../admin", "not-a-uuid", f"{ORG}/projects"])
def test_org_ids_must_be_uuids(org_id: str) -> None:
    with pytest.raises(ConnectorConfigError):
        collect_snyk_evidence(SnykFixtureClient(FIXTURE), collected_at=COLLECTED, org_ids=[org_id])


def test_api_identifiers_are_validated_before_entering_a_request_path(monkeypatch: pytest.MonkeyPatch) -> None:
    orgs = _fixture_data("orgs.json")
    orgs[0]["id"] = "../../admin"
    routes = _default_routes()
    routes[("/rest/orgs", None)] = [_page(orgs)]
    fake = _FakeSnyk(routes)
    monkeypatch.setattr(netguard, "open_public", fake)
    with pytest.raises(ValueError, match="collection incomplete"):
        collect_snyk_evidence(_client(), collected_at=COLLECTED)
    assert len(fake.requests) == 1


# --- runner, pipeline, and CCF assessment ----------------------------------------------


def _shift(value: Any, delta: timedelta) -> Any:
    if isinstance(value, dict):
        return {key: _shift(item, delta) for key, item in value.items()}
    if isinstance(value, list):
        return [_shift(item, delta) for item in value]
    if isinstance(value, str) and len(value) == 20 and value.endswith("Z") and value[4] == "-" and value[10] == "T":
        moved = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) + delta
        return moved.strftime("%Y-%m-%dT%H:%M:%SZ")
    return value


def _fresh_fixture(target: Path) -> Path:
    """Copy the fixtures with timestamps moved so 'now' plays the role of COLLECTED."""
    target.mkdir()
    delta = datetime.now(UTC).replace(microsecond=0) - COLLECTED
    for name in ("orgs.json", "projects.json", "issues.json"):
        (target / name).write_text(json.dumps(_shift(read_json(FIXTURE / name), delta)), encoding="utf-8")
    return target


def test_fixture_sync_reaches_the_ccf_assessment_through_runner_and_pipeline(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    append_config_event(lake, connector_id="snyk-vulnerabilities", state="enabled", actor="t")
    synced = run_connector_sync(
        lake, connector_id="snyk-vulnerabilities", fixture_dir=_fresh_fixture(tmp_path / "fx"), materialize=False
    )
    assert synced.result == "ok" and synced.evidence_count == 12 and synced.coverage_gaps == []
    raw = read_jsonl(lake / CONNECTOR_RAW_FILE)
    assert validate_raw_events(raw) == []
    assert all(row["attributes"]["synthetic"] is True for row in raw)

    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="snyk-test")
    assessment = read_json(out / "gold" / "ccf_assessment.json")
    by_asset = {
        row["asset_id"]: row["status"]
        for row in assessment["asset_results"]
        if row["safeguard_id"] == VULNERABILITY_SAFEGUARD
    }
    assert by_asset == {
        f"snyk:project:{_pid(1)}": "fail",  # an open high vulnerability
        f"snyk:project:{_pid(2)}": "pass",  # tested recently, no issues
        f"snyk:project:{_pid(3)}": "not_evaluated",  # last test is out of window
        f"snyk:project:{_pid(4)}": "not_evaluated",  # an ignored issue blocks the pass
        f"snyk:project:{_pid(5)}": "pass",  # only a resolved vulnerability
        f"snyk:project:{_pid(7)}": "not_evaluated",  # never tested
        f"snyk:project:{_pid(8)}": "not_evaluated",  # counts say issues, none were listed
    }
    [safeguard] = [row for row in assessment["safeguards"] if row["safeguard_id"] == VULNERABILITY_SAFEGUARD]
    assert safeguard["status"] == "fail"
    assert (safeguard["assessed_asset_count"], safeguard["invalid_binding_count"]) == (7, 0)
    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    assert VULNERABILITY_SAFEGUARD in requirements["SOC2-CC7.1"]["reviewed_safeguard_ids"]
    assert requirements["SOC2-CC7.1"]["status"] == "fail"


def test_live_sync_through_the_runner_records_a_partial_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    routes = _default_routes()
    routes[(f"/rest/orgs/{ORG}/issues", None)] = [_http_error(f"https://{HOST}/rest/orgs/{ORG}/issues", 403)]
    monkeypatch.setattr(netguard, "open_public", _FakeSnyk(routes))
    monkeypatch.setenv("ACME_SNYK_TOKEN", TOKEN)
    append_config_event(
        tmp_path,
        connector_id="snyk-vulnerabilities",
        state="enabled",
        actor="t",
        credentials={"region": "SNYK-US-01", "credential_ref": "ACME_SNYK_TOKEN"},
    )
    result = run_connector_sync(tmp_path, connector_id="snyk-vulnerabilities", materialize=False)
    assert result.result == "ok"
    assert [gap["reason"] for gap in result.coverage_gaps] == ["permission_denied"]
    run = latest_run(tmp_path, "snyk-vulnerabilities", kind="sync")
    assert run["metadata"]["partial"] is True
    lake_text = (tmp_path / CONNECTOR_RAW_FILE).read_text(encoding="utf-8")
    assert TOKEN not in lake_text


def test_live_sync_without_a_token_names_the_credential_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNYK_TOKEN", raising=False)
    monkeypatch.delenv("SNYK_TOKEN_FILE", raising=False)
    append_config_event(tmp_path, connector_id="snyk-vulnerabilities", state="enabled", actor="t")
    with pytest.raises(ConnectorSyncError, match="credential_ref"):
        run_connector_sync(tmp_path, connector_id="snyk-vulnerabilities", materialize=False)


def test_live_sync_rejects_an_unknown_region_before_any_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("no request may be sent to an unlisted host")

    monkeypatch.setattr(netguard, "open_public", refuse)
    monkeypatch.setenv("ACME_SNYK_TOKEN", TOKEN)
    append_config_event(
        tmp_path,
        connector_id="snyk-vulnerabilities",
        state="enabled",
        actor="t",
        credentials={"region": "internal.example", "credential_ref": "ACME_SNYK_TOKEN"},
    )
    with pytest.raises(ConnectorSyncError, match="region"):
        run_connector_sync(tmp_path, connector_id="snyk-vulnerabilities", materialize=False)


def test_options_select_orgs_and_test_window(tmp_path: Path) -> None:
    append_config_event(
        tmp_path,
        connector_id="snyk-vulnerabilities",
        state="enabled",
        actor="t",
        options={"org_ids": [ORG], "max_test_age_days": 60},
    )
    run_connector_sync(tmp_path, connector_id="snyk-vulnerabilities", fixture_dir=FIXTURE, materialize=False)
    rows = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    projects = [r for r in rows if r["event_type"] == "snyk.project.test_coverage"]
    assert len(projects) == 7
    assert {r["attributes"]["max_test_age_days"] for r in projects} == {60}


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"max_test_age_days": 0}, "max_test_age_days"),
        ({"max_test_age_days": 91}, "max_test_age_days"),
        ({"max_test_age_days": "seven"}, "max_test_age_days"),
        ({"max_pages": 100000}, "max_pages"),
        ({"org_ids": "not-a-uuid"}, "org_ids"),
    ],
)
def test_invalid_options_are_rejected(tmp_path: Path, options: dict[str, Any], message: str) -> None:
    append_config_event(tmp_path, connector_id="snyk-vulnerabilities", state="enabled", actor="t", options=options)
    with pytest.raises(ConnectorSyncError, match=message):
        run_connector_sync(tmp_path, connector_id="snyk-vulnerabilities", fixture_dir=FIXTURE, materialize=False)


def test_enablement_requires_a_credential_reference() -> None:
    assert (
        configure_payload_error(connector_id="snyk-vulnerabilities", state="enabled", credentials={}, options={})
        == "missing required connector configuration: credential_ref"
    )
    assert (
        configure_payload_error(
            connector_id="snyk-vulnerabilities",
            state="enabled",
            credentials={"region": "SNYK-EU-01", "credential_ref": "SNYK_TOKEN"},
            options={},
        )
        is None
    )


def test_module_constants_are_exported() -> None:
    assert set(connectors_snyk.__all__) >= {"SnykClient", "SnykFixtureClient", "collect_snyk_evidence", "api_host"}
