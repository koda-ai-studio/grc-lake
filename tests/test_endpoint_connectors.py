"""Endpoint inventory and alert evidence must retain scope and uncertainty."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import connectors_defender_endpoint as defender
from security_lakehouse import connectors_sentinelone_endpoint as sentinel
from security_lakehouse import netguard
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.io import read_json
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.validation import validate_raw_events

NOW = datetime(2026, 11, 25, tzinfo=UTC)
TOKEN = "synthetic-endpoint-token"
CASES = [(defender, "DefenderEndpoint", {}), (sentinel, "SentineloneEndpoint", {"subdomain": "example"})]


@pytest.fixture(params=CASES, ids=["defender", "sentinelone"])
def endpoint(request: Any) -> tuple[Any, Any, Any]:
    module, name, kwargs = request.param
    fixture = Path(__file__).parent / "fixtures" / module.SOURCE
    client = getattr(module, name + "FixtureClient")(fixture, **kwargs)
    return module, client, getattr(module, "collect_" + module.SOURCE + "_evidence")


def test_inventory_and_alerts_have_valid_distinct_bindings(endpoint: Any) -> None:
    module, client, collect = endpoint
    rows = collect(client, collected_at=NOW)
    assert validate_raw_events(rows) == []
    inventory = [r for r in rows if r["event_type"].endswith(".protection")]
    assert len(inventory) == 1 and inventory[0]["status"] == "observed"
    assert inventory[0]["safeguard_ids"] == ["SG-MALWARESCANNING-001"]
    alerts = [r for r in rows if r["event_type"].endswith(".alert")]
    assert sorted(r["status"] for r in alerts) == ["observed", "open"]
    assert len({r["event_id"] for r in rows}) == len(rows)
    assert len({r["entity"]["asset_id"] for r in alerts}) == 1
    assert all(r["safeguard_ids"] == ["SG-DETECTION-001"] for r in alerts)
    assert all(r["attributes"]["synthetic"] is True for r in rows)
    assert rows == collect(client, collected_at=NOW)


@pytest.mark.parametrize("value", [None, "2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "invalid"])
def test_stale_or_unknown_activity_blocks_positive_evidence(endpoint: Any, value: Any) -> None:
    module, client, collect = endpoint
    first = next(iter(client.responses.values()))
    record = first["value" if module is defender else "data"][0]
    record["lastSeen" if module is defender else "lastActiveDate"] = value
    row = next(r for r in collect(client, collected_at=NOW) if r["event_type"].endswith(".protection"))
    assert row["status"] == "not_evaluated"


@pytest.mark.parametrize("payload", [{}, None, [], {"value": [None], "data": [None]}])
def test_malformed_inventory_is_a_gap(endpoint: Any, payload: Any) -> None:
    _, client, collect = endpoint
    client.responses[next(iter(client.responses))] = payload
    rows = collect(client, collected_at=NOW)
    assert any(r["attributes"].get("collection_gap") is True for r in rows)
    assert not any(r["status"] == "pass" for r in rows)


def test_duplicate_inventory_is_a_gap(endpoint: Any) -> None:
    module, client, collect = endpoint
    data = next(iter(client.responses.values()))["value" if module is defender else "data"]
    data.append(data[0])
    assert any(r["attributes"].get("collection_gap") for r in collect(client, collected_at=NOW))


def test_empty_inventory_is_not_success(endpoint: Any) -> None:
    module, client, collect = endpoint
    first = next(iter(client.responses.values()))
    first["value" if module is defender else "data"] = []
    if module is sentinel:
        first["pagination"]["totalItems"] = 0
    assert any(r["attributes"].get("collection_gap") for r in collect(client, collected_at=NOW))


def test_missing_alert_read_preserves_inventory_and_partial_run(endpoint: Any, tmp_path: Path) -> None:
    module, client, collect = endpoint
    del client.responses[list(client.responses)[-1]]
    rows = collect(client, collected_at=NOW)
    assert any(r["event_type"].endswith(".protection") for r in rows)
    assert any(r["attributes"].get("collection_gap") for r in rows)
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "responses.json").write_text(json.dumps(client.responses))
    append_config_event(
        tmp_path, connector_id=module.CONNECTOR_ID, state="enabled", actor="test", credentials={"subdomain": "example"}
    )
    result = run_connector_sync(tmp_path, connector_id=module.CONNECTOR_ID, fixture_dir=fixture, materialize=False)
    assert result.coverage_gaps
    assert latest_run(tmp_path, module.CONNECTOR_ID, kind="sync")["metadata"]["partial"] is True
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    row = next(r for r in assessment["safeguards"] if r["safeguard_id"] == "SG-MALWARESCANNING-001")
    assert row["assessed_asset_count"] == 1 and row["invalid_binding_count"] == 0


@pytest.mark.parametrize("code", [401, 403, 429, 500])
@pytest.mark.parametrize("module,name,kwargs", CASES)
def test_http_errors_are_redacted_gaps(monkeypatch: Any, code: int, module: Any, name: str, kwargs: Any) -> None:
    def read(request: Any, **_: Any) -> Any:
        assert request.get_method() == "GET"
        raise urllib.error.HTTPError(request.full_url, code, TOKEN, {}, io.BytesIO(TOKEN.encode()))

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", lambda _: None)
    rows = getattr(module, "collect_" + module.SOURCE + "_evidence")(
        getattr(module, name + "Client")(token=TOKEN, **kwargs)
    )
    assert rows and all(r["attributes"].get("collection_gap") for r in rows)
    assert TOKEN not in json.dumps(rows)


@pytest.mark.parametrize("module,name,kwargs", CASES)
def test_runner_requires_explicit_resolvable_reference(
    tmp_path: Path, monkeypatch: Any, module: Any, name: str, kwargs: Any
) -> None:
    monkeypatch.setenv(module.TOKEN_ENV, TOKEN)
    monkeypatch.setattr(netguard, "open_public", lambda *a, **kw: pytest.fail("Unexpected network"))
    append_config_event(tmp_path, connector_id=module.CONNECTOR_ID, state="enabled", actor="test", credentials=kwargs)
    with pytest.raises(ConnectorSyncError, match="credential_ref"):
        run_connector_sync(tmp_path, connector_id=module.CONNECTOR_ID, materialize=False)


def test_defender_foreign_or_wrong_path_next_links_are_gaps() -> None:
    fixture = Path(__file__).parent / "fixtures/defender_endpoint"
    for link in (
        "https://evil.example/api/machines?$skip=1",
        "//evil.example/api/machines",
        "https://api.security.microsoft.com/api/alerts?$skip=1",
        "http://api.security.microsoft.com/api/machines",
    ):
        c = defender.DefenderEndpointFixtureClient(fixture)
        c.responses["/api/machines?$top=1000&$skip=0"]["@odata.nextLink"] = link
        rows = defender.collect_defender_endpoint_evidence(c, collected_at=NOW)
        assert any(r["attributes"].get("reason") == "unsafe_next_link" for r in rows)


def test_defender_odata_next_link_and_page_budget() -> None:
    c = defender.DefenderEndpointFixtureClient(Path(__file__).parent / "fixtures/defender_endpoint")
    path = "/api/machines"
    c.responses[path + "?$top=1000&$skip=0"]["@odata.nextLink"] = (
        "https://api.security.microsoft.com/api/machines?$skiptoken=next"
    )
    c.responses[path + "?$skiptoken=next"] = {"value": [{"id": "machine-2"}]}
    assert len(c.records(path)) == 2
    c.max_pages = 1
    rows = defender.collect_defender_endpoint_evidence(c, collected_at=NOW)
    assert any(r["attributes"].get("reason") == "page_budget_exhausted" for r in rows)


def test_sentinelone_cursor_is_encoded_and_totals_are_checked() -> None:
    c = sentinel.SentineloneEndpointFixtureClient(
        Path(__file__).parent / "fixtures/sentinelone_endpoint", subdomain="example"
    )
    path = "/web/api/v2.1/agents"
    c.responses[path + "?limit=1000"]["pagination"] = {"nextCursor": "https://evil.example/x", "totalItems": 2}
    c.responses[path + "?limit=1000&cursor=https%3A%2F%2Fevil.example%2Fx"] = {
        "data": [{"id": "agent-2"}],
        "pagination": {"nextCursor": None, "totalItems": 2},
    }
    assert len(c.records(path)) == 2
    c.max_pages = 1
    assert any(
        r["attributes"].get("reason") == "page_budget_exhausted"
        for r in sentinel.collect_sentinelone_endpoint_evidence(c)
    )
    c.max_pages = 100
    c.responses[path + "?limit=1000"]["pagination"] = {"nextCursor": None, "totalItems": 10}
    assert any(
        r["attributes"].get("reason") == "population_count_mismatch"
        for r in sentinel.collect_sentinelone_endpoint_evidence(c)
    )


@pytest.mark.parametrize("subdomain", ["evil.example", "a@evil", "a:443", "a/b", "a%2e", "-bad", ""])
def test_sentinelone_host_injection_rejected(subdomain: str) -> None:
    from security_lakehouse.connector_errors import ConnectorConfigError

    with pytest.raises(ConnectorConfigError):
        sentinel.SentineloneEndpointClient(token=TOKEN, subdomain=subdomain)


def test_detect_only_agent_is_not_protected() -> None:
    c = sentinel.SentineloneEndpointFixtureClient(
        Path(__file__).parent / "fixtures/sentinelone_endpoint", subdomain="example"
    )
    c.responses["/web/api/v2.1/agents?limit=1000"]["data"][0]["mitigationMode"] = "detect"
    row = next(
        r
        for r in sentinel.collect_sentinelone_endpoint_evidence(c, collected_at=NOW)
        if r["event_type"].endswith(".protection")
    )
    assert row["status"] == "open"


@pytest.mark.parametrize("module,name,kwargs", CASES)
def test_retry_after_keeps_vendor_host_and_auth(monkeypatch: Any, module: Any, name: str, kwargs: Any) -> None:
    c = getattr(module, name + "Client")(token=TOKEN, **kwargs)
    sleeps: list[float] = []
    calls: list[str] = []

    def read(request: Any, **_: Any) -> Any:
        calls.append(request.full_url)
        assert request.full_url.startswith("https://" + c.host + "/")
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == ("Bearer " if module is defender else "ApiToken ") + TOKEN
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, TOKEN, {"Retry-After": "2"}, None)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", sleeps.append)
    assert c.get("/test") == {}
    assert sleeps == [2.0] and len(calls) == 2
