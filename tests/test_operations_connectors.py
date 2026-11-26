"""Read-only monitoring and change evidence retains missing-data boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import connectors_datadog_monitoring as dd
from security_lakehouse import connectors_servicenow_operations as sn
from security_lakehouse.validation import validate_raw_events

NOW = datetime(2026, 11, 25, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures"


def test_datadog_monitor_and_retention_bindings() -> None:
    rows = dd.collect_datadog_monitoring_evidence(
        dd.DatadogMonitoringFixtureClient(FIXTURES / "datadog_monitoring"), collected_at=NOW
    )
    assert validate_raw_events(rows) == []
    monitors = [r for r in rows if r["event_type"].endswith(".monitor")]
    assert len(monitors) == 2 and all(r["status"] == "open" for r in monitors)
    assert all(r["safeguard_ids"] == ["SG-DETECTION-001"] for r in monitors)
    index = next(r for r in rows if r["event_type"].endswith(".log_index"))
    assert index["attributes"]["retention_days"] == 15
    assert index["safeguard_ids"] == ["SG-LOGGING-001"]
    assert index["status"] == "observed"
    audit = next(r for r in rows if r["event_type"].endswith(".audit_trail"))
    assert audit["status"] == "not_evaluated" and audit["attributes"]["enabled"] is None
    assert "private@example.com" not in json.dumps(rows)


def test_servicenow_implemented_without_approval_and_overdue_incident() -> None:
    rows = sn.collect_servicenow_operations_evidence(
        sn.ServicenowOperationsFixtureClient(FIXTURES / "servicenow_operations", subdomain="example"), collected_at=NOW
    )
    assert validate_raw_events(rows) == []
    changes = [r for r in rows if r["event_type"].endswith(".change")]
    assert sorted(r["status"] for r in changes) == ["observed", "open"]
    assert all(r["safeguard_ids"] == ["SG-CHANGEAPPROVAL-001"] for r in changes)
    incident = next(r for r in rows if r["event_type"].endswith(".incident"))
    assert incident["status"] == "open" and incident["safeguard_ids"] == ["SG-INCIDENTHANDLING-001"]
    assert "private description" not in json.dumps(rows)


CASES = [
    (dd, "DatadogMonitoring", {"api_key": "synthetic-api", "application_key": "synthetic-app"}, {}),
    (sn, "ServicenowOperations", {"token": "synthetic-token", "subdomain": "example"}, {"subdomain": "example"}),
]


@pytest.fixture(params=CASES, ids=["datadog", "servicenow"])
def operations(request: Any) -> tuple[Any, Any, Any]:
    module, name, _, fixture_kwargs = request.param
    client = getattr(module, name + "FixtureClient")(FIXTURES / module.SOURCE, **fixture_kwargs)
    return module, client, getattr(module, "collect_" + module.SOURCE + "_evidence")


@pytest.mark.parametrize("payload", [{}, None, [None], {"result": [None], "indexes": [None]}])
def test_malformed_scope_is_a_gap(operations: Any, payload: Any) -> None:
    _, c, collect = operations
    c.responses[next(iter(c.responses))] = payload
    rows = collect(c, collected_at=NOW)
    assert any(r["attributes"].get("collection_gap") for r in rows)
    assert not any(r["status"] == "pass" for r in rows)


def test_duplicate_records_are_partial(operations: Any) -> None:
    module, c, collect = operations
    first = next(iter(c.responses.values()))
    rows = first["indexes" if module is dd else "result"]
    rows.append(rows[0])
    assert any(r["attributes"].get("reason") == "duplicate_record" for r in collect(c, collected_at=NOW))


def test_runner_to_pipeline_binding_and_partial_metadata(operations: Any, tmp_path: Path) -> None:
    from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
    from security_lakehouse.connector_state import append_config_event, latest_run
    from security_lakehouse.io import read_json
    from security_lakehouse.pipeline import run_pipeline

    module, c, _ = operations
    del c.responses[list(c.responses)[-1]]
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "responses.json").write_text(json.dumps(c.responses))
    append_config_event(
        tmp_path, connector_id=module.CONNECTOR_ID, state="enabled", actor="test", credentials={"subdomain": "example"}
    )
    result = run_connector_sync(tmp_path, connector_id=module.CONNECTOR_ID, fixture_dir=fixture, materialize=False)
    assert result.coverage_gaps
    assert latest_run(tmp_path, module.CONNECTOR_ID, kind="sync")["metadata"]["partial"] is True
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    safeguard = "SG-LOGGING-001" if module is dd else "SG-CHANGEAPPROVAL-001"
    row = next(r for r in assessment["safeguards"] if r["safeguard_id"] == safeguard)
    assert row["assessed_asset_count"] >= 1 and row["invalid_binding_count"] == 0


@pytest.mark.parametrize("module,name,kwargs,fixture_kwargs", CASES)
@pytest.mark.parametrize("code", [401, 403, 429, 500])
def test_http_errors_never_expose_credentials(
    monkeypatch: Any, module: Any, name: str, kwargs: Any, fixture_kwargs: Any, code: int
) -> None:
    import io
    import urllib.error

    from security_lakehouse import netguard

    def deny(request: Any, **_: Any) -> Any:
        assert request.get_method() == "GET"
        raise urllib.error.HTTPError(request.full_url, code, "synthetic-secret", {}, io.BytesIO(b"synthetic-secret"))

    monkeypatch.setattr(netguard, "open_public", deny)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", lambda _: None)
    rows = getattr(module, "collect_" + module.SOURCE + "_evidence")(getattr(module, name + "Client")(**kwargs))
    assert rows and all(r["attributes"].get("collection_gap") for r in rows)
    assert "synthetic-secret" not in json.dumps(rows)


@pytest.mark.parametrize("module,name,kwargs,fixture_kwargs", CASES)
def test_retry_after_is_respected(monkeypatch: Any, module: Any, name: str, kwargs: Any, fixture_kwargs: Any) -> None:
    import io
    import urllib.error

    from security_lakehouse import netguard

    c = getattr(module, name + "Client")(**kwargs)
    calls = []
    sleeps = []

    def read(request: Any, **_: Any) -> Any:
        calls.append(request.full_url)
        assert request.full_url.startswith("https://" + c.host + "/")
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "limited", {"Retry-After": "2"}, None)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", sleeps.append)
    assert c.get("/test", {}) == {} and sleeps == [2.0]


@pytest.mark.parametrize("module,name,kwargs,fixture_kwargs", CASES)
def test_no_ambient_credential_fallback(
    monkeypatch: Any, tmp_path: Path, module: Any, name: str, kwargs: Any, fixture_kwargs: Any
) -> None:
    from security_lakehouse import netguard
    from security_lakehouse.connector_runner import ConnectorSyncError, run_connector_sync
    from security_lakehouse.connector_state import append_config_event

    monkeypatch.setenv(module.TOKEN_ENV, "synthetic-token")
    monkeypatch.setattr(netguard, "open_public", lambda *a, **kw: pytest.fail("Unexpected network"))
    append_config_event(
        tmp_path, connector_id=module.CONNECTOR_ID, state="enabled", actor="test", credentials=fixture_kwargs
    )
    with pytest.raises(ConnectorSyncError, match="credential_ref"):
        run_connector_sync(tmp_path, connector_id=module.CONNECTOR_ID, materialize=False)


def test_datadog_cursor_never_follows_links_and_partial_queries_fail() -> None:
    c = dd.DatadogMonitoringFixtureClient(FIXTURES / "datadog_monitoring")
    path = "/api/v2/security_monitoring/signals"
    c.responses[path]["meta"]["page"] = {"after": "https://evil.example/"}
    c.responses[path]["links"] = {"next": "https://evil.example/"}
    c.responses[path + "?page%5Bcursor%5D=https%3A%2F%2Fevil.example%2F"] = {
        "data": [],
        "meta": {"status": "done", "page": {}},
    }
    assert len(c.records("signal", NOW)) == 1
    c.max_pages = 1
    assert any(
        r["attributes"].get("reason") == "page_budget_exhausted"
        for r in dd.collect_datadog_monitoring_evidence(c, collected_at=NOW)
    )
    c.responses[path]["meta"]["status"] = "timeout"
    assert any(
        r["attributes"].get("reason") == "incomplete_query"
        for r in dd.collect_datadog_monitoring_evidence(c, collected_at=NOW)
    )


def test_servicenow_offsets_and_page_budget() -> None:
    c = sn.ServicenowOperationsFixtureClient(FIXTURES / "servicenow_operations", subdomain="example")
    path = "/api/now/table/incident"
    row = c.responses[path]["result"][0]
    c.responses[path] = {"result": [dict(row, sys_id=f"{i:032x}") for i in range(100)]}
    c.responses[path + "?sysparm_offset=100"] = {"result": [dict(row, sys_id=f"{100:032x}")]}
    assert len(c.records("incident")) == 101
    c.max_pages = 1
    assert any(
        r["attributes"].get("reason") == "page_budget_exhausted" for r in sn.collect_servicenow_operations_evidence(c)
    )


@pytest.mark.parametrize("value", ["evil.example", "a@evil", "a:443", "a/b", "a%2e", "-bad", ""])
def test_host_injection_is_rejected(value: str) -> None:
    from security_lakehouse.connector_errors import ConnectorConfigError

    with pytest.raises(ConnectorConfigError):
        dd.DatadogMonitoringClient(api_key="test", application_key="test", site=value)
    with pytest.raises(ConnectorConfigError):
        sn.ServicenowOperationsClient(token="test", subdomain=value)


def test_late_approval_is_not_evidence_of_prior_approval() -> None:
    c = sn.ServicenowOperationsFixtureClient(FIXTURES / "servicenow_operations", subdomain="example")
    c.responses["/api/now/table/change_request"]["result"][1]["approval_set"] = "2026-11-24 01:00:00"
    assert all(
        r["status"] == "open"
        for r in sn.collect_servicenow_operations_evidence(c, collected_at=NOW)
        if r["event_type"].endswith(".change")
    )


def test_unreadable_incident_dates_are_unknown() -> None:
    c = sn.ServicenowOperationsFixtureClient(FIXTURES / "servicenow_operations", subdomain="example")
    c.responses["/api/now/table/incident"]["result"][0]["opened_at"] = None
    assert (
        next(
            r
            for r in sn.collect_servicenow_operations_evidence(c, collected_at=NOW)
            if r["event_type"].endswith(".incident")
        )["status"]
        == "not_evaluated"
    )
