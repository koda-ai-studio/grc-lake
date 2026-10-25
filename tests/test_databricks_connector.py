"""Databricks evidence-lake connector (fixture-backed + fake Statement Execution API)."""

from __future__ import annotations

import io
import json
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import security_lakehouse.connector_runner as connector_runner
from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_databricks import (
    DatabricksClient,
    DatabricksFixtureClient,
    collect_databricks_evidence,
    validate_identifier,
    validate_workspace_host,
)
from security_lakehouse.io import read_jsonl
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures" / "databricks"
HOST = "dbc-a1b2345c-d6e7.cloud.databricks.com"


def _statement_result() -> dict[str, Any]:
    return {
        "statement_id": "stmt-1",
        "status": {"state": "SUCCEEDED"},
        "manifest": {
            "format": "JSON_ARRAY",
            "schema": {"columns": [{"name": "audit_id"}]},
            "total_row_count": 1,
            "truncated": False,
        },
        "result": {"data_array": [["a1"]], "row_count": 1, "row_offset": 0},
    }


def _result_client(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any], chunk: dict[str, Any] | None = None
) -> DatabricksClient:
    _fake_workspace(
        monkeypatch,
        {
            ("POST", "/oidc/v1/token"): {"access_token": "synthetic-token"},
            ("POST", "/api/2.0/sql/statements"): response,
            ("GET", "/api/2.0/sql/statements/stmt-1/result/chunks/1"): chunk
            if chunk is not None
            else {
                "data_array": [["a2"]],
                "row_count": 1,
                "row_offset": 1,
            },
        },
    )
    return DatabricksClient(
        HOST, client_id="test-app", client_secret="synthetic-secret", warehouse_id="w", catalog="c", schema="s"
    )


@pytest.mark.parametrize(
    ("manifest", "result"),
    [
        ({"truncated": True}, {}),
        ({"truncated": "false"}, {}),
        ({"total_row_count": 2}, {}),
        ({"total_row_count": True}, {}),
        ({"total_row_count": -1}, {}),
        ({"total_row_count": "1"}, {}),
        ({"schema": {"columns": []}}, {}),
        ({"schema": {"columns": [{"name": ""}]}}, {}),
        ({"schema": {"columns": [{"name": "audit_id"}, {"name": "audit_id"}]}}, {"data_array": [["a1", "a2"]]}),
        ({}, {"data_array": [[]]}),
        ({}, {"data_array": [["a1", "extra"]]}),
        ({}, {"data_array": ["a1"]}),
        ({}, {"data_array": None}),
        ({}, {"row_count": 2}),
        ({}, {"row_count": True}),
        ({}, {"row_offset": 1}),
    ],
)
def test_statement_result_must_be_complete(
    monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any], result: dict[str, Any]
) -> None:
    response = _statement_result()
    response["manifest"].update(manifest)
    response["result"].update(result)
    with pytest.raises(CollectionGapError, match="incomplete"):
        _result_client(monkeypatch, response).audit_events()


@pytest.mark.parametrize("missing", ["manifest", "result"])
def test_success_status_does_not_replace_result_data(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    response = _statement_result()
    del response[missing]
    with pytest.raises(CollectionGapError, match="incomplete"):
        _result_client(monkeypatch, response).audit_events()


@pytest.mark.parametrize("link", ["@attacker.example/result", "other.example/result", "//attacker.example/result"])
def test_chunk_paths_cannot_change_the_request_authority(monkeypatch: pytest.MonkeyPatch, link: str) -> None:
    response = _statement_result()
    response["result"]["next_chunk_internal_link"] = link
    with pytest.raises(CollectionGapError, match="chunk link"):
        _result_client(monkeypatch, response).audit_events()


@pytest.mark.parametrize("cursor", ["index", "path", "absolute"])
def test_all_documented_chunk_cursors_return_the_complete_result(monkeypatch: pytest.MonkeyPatch, cursor: str) -> None:
    response = _statement_result()
    response["manifest"]["total_row_count"] = 2
    if cursor == "index":
        response["result"]["next_chunk_index"] = 1
    else:
        path = "/api/2.0/sql/statements/stmt-1/result/chunks/1"
        response["result"]["next_chunk_internal_link"] = f"https://{HOST}{path}" if cursor == "absolute" else path
    assert _result_client(monkeypatch, response).audit_events() == [{"audit_id": "a1"}, {"audit_id": "a2"}]


def test_declared_empty_result_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _statement_result()
    response["manifest"]["total_row_count"] = 0
    del response["result"]
    assert _result_client(monkeypatch, response).audit_events() == []


def test_sql_null_is_not_a_missing_column(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _statement_result()
    response["result"]["data_array"] = [[None]]
    assert _result_client(monkeypatch, response).audit_events() == [{"audit_id": None}]


@pytest.mark.parametrize("index", [True, -1, "1"])
def test_invalid_chunk_index_is_a_gap(monkeypatch: pytest.MonkeyPatch, index: Any) -> None:
    response = _statement_result()
    response["result"]["next_chunk_index"] = index
    with pytest.raises(CollectionGapError, match="incomplete"):
        _result_client(monkeypatch, response).audit_events()


def test_index_cursor_requires_a_statement_id(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _statement_result()
    del response["statement_id"]
    response["result"]["next_chunk_index"] = 1
    with pytest.raises(CollectionGapError, match="statement identifier"):
        _result_client(monkeypatch, response).audit_events()


def test_chunk_budget_exhaustion_is_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    from functools import partial

    from security_lakehouse.ingestion.paginate import paginate

    monkeypatch.setattr("security_lakehouse.connectors_databricks.paginate", partial(paginate, max_pages=1))
    response = _statement_result()
    response["manifest"]["total_row_count"] = 2
    response["result"]["next_chunk_internal_link"] = "/api/2.0/sql/statements/stmt-1/result/chunks/1"
    with pytest.raises(CollectionGapError, match="pagination did not finish"):
        _result_client(monkeypatch, response).audit_events()


@pytest.mark.parametrize(
    "chunk",
    [
        {"data_array": [["a2", "extra"]]},
        {"data_array": [["a2"]], "row_offset": 0},
        {"data_array": [["a2"]], "row_count": 2},
        {"data_array": [["a2"]], "next_chunk_index": 1},
        {},
    ],
)
def test_later_chunks_must_be_complete(monkeypatch: pytest.MonkeyPatch, chunk: dict[str, Any]) -> None:
    response = _statement_result()
    response["manifest"]["total_row_count"] = 2
    response["result"]["next_chunk_internal_link"] = "/api/2.0/sql/statements/stmt-1/result/chunks/1"
    with pytest.raises(CollectionGapError, match="incomplete"):
        _result_client(monkeypatch, response, chunk).audit_events()


@pytest.mark.parametrize("mapped", [False, True])
@pytest.mark.parametrize("failure", ["truncated", "late_chunk"])
def test_incomplete_sync_records_gap_without_replacing_evidence_or_advancing_watermark(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mapped: bool, failure: str
) -> None:
    from security_lakehouse.ingestion.watermark import read_watermark, write_watermark

    connector = "databricks-evidence-lake"
    credentials = {
        "host": HOST,
        "warehouse_id": "w",
        "catalog": "c",
        "schema": "s",
        "client_id": "test-app",
        "client_secret_ref": "DATABRICKS_CLIENT_SECRET",
    }
    append_config_event(tmp_path, connector_id=connector, state="enabled", actor="test", credentials=credentials)
    connector_runner.run_connector_sync(tmp_path, connector_id=connector, fixture_dir=FIXTURE)
    raw = tmp_path / connector_runner.CONNECTOR_RAW_FILE
    assessment = tmp_path / "gold/ccf_assessment.json"
    before = raw.read_bytes(), assessment.read_bytes()
    cursor = "2026-10-24T12:00:00Z"
    write_watermark(tmp_path, connector, cursor)
    if mapped:
        append_config_event(
            tmp_path,
            connector_id=connector,
            state="enabled",
            actor="test",
            credentials=credentials,
            options={
                "mapping": {
                    "spec_version": 1,
                    "name": "audit_scope",
                    "source": {"table": "audit_events"},
                    "fields": {
                        "id": {"column": "audit_id"},
                        "observed_at": {"column": "event_time", "format": "timestamp"},
                        "asset_id": {"column": "audit_id"},
                    },
                }
            },
        )
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "synthetic-secret")
    response = _statement_result()
    if failure == "truncated":
        response["manifest"]["truncated"] = True
    else:
        response["manifest"]["total_row_count"] = 2
        response["result"]["next_chunk_internal_link"] = "/api/2.0/sql/statements/stmt-1/result/chunks/1"
    _result_client(monkeypatch, response, {"data_array": [["a2", "extra"]]})
    with pytest.raises(connector_runner.ConnectorSyncError) as failed:
        connector_runner.run_connector_sync(tmp_path, connector_id=connector)
    run = failed.value.run
    assert run["result"] == "error"
    assert run["metadata"]["partial"] is True
    [gap] = run["metadata"]["coverage_gaps"]
    assert gap["collection"] == ("audit_scope" if mapped else "audit_events")
    assert gap["reason"] == "incomplete_result"
    assert "synthetic-secret" not in json.dumps(run) and "synthetic-token" not in json.dumps(run)
    assert (raw.read_bytes(), assessment.read_bytes()) == before
    assert read_watermark(tmp_path, connector) == cursor


def test_fixture_collection_uses_the_shared_evidence_view_contract() -> None:
    rows = collect_databricks_evidence(
        DatabricksFixtureClient(FIXTURE, host=HOST), collected_at=datetime(2026, 6, 3, tzinfo=UTC)
    )
    assert validate_raw_events(rows) == []
    assert rows
    assert {r["source"] for r in rows} == {"databricks"}
    assert {r["event_type"].split(".", 1)[1] for r in rows} == {
        "audit.event",
        "control.posture",
        "asset.risk",
        "evidence.bundle",
    }
    assert all(r["event_id"].startswith("databricks-") for r in rows)


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _fake_workspace(monkeypatch: pytest.MonkeyPatch, routes: dict[tuple[str, str], Any]) -> list[Any]:
    seen: list[Any] = []

    def fake_open_public(request: Any, *, timeout: float, label: str) -> _FakeResponse:
        seen.append(request)
        parsed = urllib.parse.urlparse(request.full_url)
        assert parsed.hostname == HOST, request.full_url
        key = (request.get_method(), parsed.path)
        payload = routes[key]
        if isinstance(payload, list):
            payload = payload.pop(0)
        return _FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr(netguard, "open_public", fake_open_public)
    return seen


def test_live_client_mints_m2m_token_polls_and_follows_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    columns = {"schema": {"columns": [{"name": "audit_id"}, {"name": "actor"}]}}
    seen = _fake_workspace(
        monkeypatch,
        {
            ("POST", "/oidc/v1/token"): {"access_token": "tok", "token_type": "Bearer", "expires_in": 3600},
            ("POST", "/api/2.0/sql/statements"): {"statement_id": "s1", "status": {"state": "RUNNING"}},
            ("GET", "/api/2.0/sql/statements/s1"): {
                "statement_id": "s1",
                "status": {"state": "SUCCEEDED"},
                "manifest": columns,
                "result": {
                    "data_array": [["a1", "x@example.com"]],
                    "next_chunk_internal_link": "/api/2.0/sql/statements/s1/result/chunks/1",
                },
            },
            ("GET", "/api/2.0/sql/statements/s1/result/chunks/1"): {"data_array": [["a2", "y@example.com"]]},
        },
    )
    client = DatabricksClient(
        HOST,
        client_id="sp-app-id",
        client_secret="sp-secret",
        warehouse_id="wh123",
        catalog="trustops",
        schema="evidence",
        sleep=lambda _s: None,
    )

    rows = client.audit_events()

    assert rows == [{"audit_id": "a1", "actor": "x@example.com"}, {"audit_id": "a2", "actor": "y@example.com"}]
    token_request, statement_request = seen[0], seen[1]
    assert token_request.data == b"grant_type=client_credentials&scope=all-apis"
    assert token_request.get_header("Authorization").startswith("Basic ")
    body = json.loads(statement_request.data)
    assert body["statement"] == "SELECT * FROM `trustops`.`evidence`.`GRC_LAKE_AUDIT_EVENTS`"
    assert body["warehouse_id"] == "wh123"
    assert (body["disposition"], body["format"]) == ("INLINE", "JSON_ARRAY")
    assert statement_request.get_header("Authorization") == "Bearer tok"


def test_failed_statement_raises_with_databricks_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_workspace(
        monkeypatch,
        {
            ("POST", "/oidc/v1/token"): {"access_token": "tok", "expires_in": 3600},
            ("POST", "/api/2.0/sql/statements"): {
                "statement_id": "s2",
                "status": {"state": "FAILED", "error": {"message": "TABLE_OR_VIEW_NOT_FOUND"}},
            },
        },
    )
    client = DatabricksClient(
        HOST, client_id="a", client_secret="b", warehouse_id="w", catalog="c", schema="s", sleep=lambda _s: None
    )
    with pytest.raises(RuntimeError, match="TABLE_OR_VIEW_NOT_FOUND"):
        client.control_posture()


def test_chunk_link_must_stay_on_the_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_workspace(
        monkeypatch,
        {
            ("POST", "/oidc/v1/token"): {"access_token": "tok", "expires_in": 3600},
            ("POST", "/api/2.0/sql/statements"): {
                "statement_id": "s3",
                "status": {"state": "SUCCEEDED"},
                "manifest": {"schema": {"columns": [{"name": "asset_id"}]}},
                "result": {"data_array": [["a"]], "next_chunk_internal_link": "https://attacker.example/x"},
            },
        },
    )
    client = DatabricksClient(
        HOST, client_id="a", client_secret="b", warehouse_id="w", catalog="c", schema="s", sleep=lambda _s: None
    )
    with pytest.raises(CollectionGapError, match="chunk link"):
        client.asset_risk()


@pytest.mark.parametrize(
    "host",
    [
        "dbc-a1b2345c-d6e7.cloud.databricks.com",
        "adb-1234567890123456.7.azuredatabricks.net",
        "12345.6.gcp.databricks.com",
    ],
)
def test_workspace_hosts_accepted(host: str) -> None:
    assert validate_workspace_host(host) == host


@pytest.mark.parametrize(
    "host",
    [
        "",
        "attacker.example",
        "https://dbc-1.cloud.databricks.com",
        "dbc-1.cloud.databricks.com/x",
        "cloud.databricks.com.attacker.example",
    ],
)
def test_workspace_hosts_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="host"):
        validate_workspace_host(host)


@pytest.mark.parametrize("name", ["", "a`b", "a.b", "x; DROP TABLE y", "a b"])
def test_identifiers_are_strict(name: str) -> None:
    with pytest.raises(ValueError, match="identifier"):
        validate_identifier(name)


def test_fixture_sync_and_live_config_gate(tmp_path: Path) -> None:
    creds = {
        "host": HOST,
        "warehouse_id": "wh123",
        "catalog": "trustops",
        "schema": "evidence",
        "client_id": "sp-app-id",
        "client_secret_ref": "DATABRICKS_CLIENT_SECRET",
    }
    append_config_event(
        tmp_path, connector_id="databricks-evidence-lake", state="enabled", actor="a", credentials=creds
    )
    result = connector_runner.run_connector_sync(tmp_path, connector_id="databricks-evidence-lake", fixture_dir=FIXTURE)
    assert result.result == "ok" and result.evidence_count > 0
    assert validate_raw_events(read_jsonl(tmp_path / connector_runner.CONNECTOR_RAW_FILE)) == []

    other = tmp_path / "unconfigured"
    append_config_event(other, connector_id="databricks-evidence-lake", state="enabled", actor="a")
    with pytest.raises(connector_runner.ConnectorSyncError):
        connector_runner.run_connector_sync(other, connector_id="databricks-evidence-lake")


def test_bootstrap_sql_matches_the_connector_contract() -> None:
    from security_lakehouse.connectors_snowflake import DEFAULT_VIEWS

    body = (Path(__file__).resolve().parents[1] / "deploy" / "databricks" / "bootstrap_poc.sql").read_text()
    for view in DEFAULT_VIEWS.values():
        assert f"CREATE OR REPLACE VIEW trustops.evidence.{view} AS" in body
    for column in ("AS audit_id", "AS control_id", "AS asset_id", "AS bundle_id", "AS hash_sha256", "AS risk_score"):
        assert column in body
    assert "GRANT USE CATALOG ON CATALOG trustops" in body
    assert "GRANT USE SCHEMA ON SCHEMA trustops.evidence" in body
    assert "GRANT SELECT ON SCHEMA trustops.evidence" in body
    grants = [line for line in body.splitlines() if line.startswith("GRANT")]
    assert grants and all(
        "system." not in line and "MODIFY" not in line and "ALL PRIVILEGES" not in line for line in grants
    )
    statements = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--")).upper()
    for forbidden in ("SECRET", "TOKEN", "PASSWORD", "CREATE SERVICE PRINCIPAL"):
        assert forbidden not in statements
