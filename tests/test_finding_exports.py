"""Portable finding exports: the ``grc-lake.findings.v1`` contract across module, API, CLI and MCP."""

from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

import pytest

from security_lakehouse import finding_exports
from security_lakehouse.cli import main
from security_lakehouse.io import write_jsonl
from test_api_v1 import _seed_lake

SCHEMA = "grc-lake.findings.v1"


def _posture(violations: list[dict]) -> dict:
    return {
        "evaluated_at": "2026-05-22T13:01:00+00:00",
        "assessment_hash": "a" * 64,
        "violations": violations,
        "violation_summary": {"total_count": len(violations), "truncated": False},
    }


def _violation(index: int, **overrides: object) -> dict:
    row = {
        "violation_id": f"SOC2-CC6.1:evt-{index:03d}",
        "control_id": "SOC2-CC6.1",
        "event_id": f"evt-{index:03d}",
        "asset_id": "aws:iam:role/admin",
        "source_account_id": "123456789012",
        "asset_owner": "security-platform",
        "environment": "prod",
        "source": "okta",
        "event_type": "identity.access_review",
        "severity": "high",
        "severity_score": 80,
        "state": "open",
        "evidence_ref": f"s3://evidence/evt-{index:03d}.json",
        "raw_sha256": "abc",
        "detected_at": "2026-05-20T13:01:00Z",
    }
    row.update(overrides)
    return row


FRAMEWORKS = {"SOC2-CC6.1": ["SOC 2"], "NIST-AI-RMF-MAP-1.5": ["NIST AI RMF"]}


# --- export rows -------------------------------------------------------------


def test_export_rows_have_stable_columns_and_no_evidence_payload() -> None:
    rows = list(
        finding_exports.iter_export_rows(
            _posture([_violation(1)]), tenant_id="tenant-a", frameworks=FRAMEWORKS, limit=10
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert tuple(row) == finding_exports.EXPORT_COLUMNS
    assert row["export_schema_version"] == SCHEMA
    assert row["finding_id"] == "SOC2-CC6.1:evt-001"
    assert row["tenant_id"] == "tenant-a"
    assert row["source_account_id"] == "123456789012"
    assert row["framework_ids"] == ["SOC 2"]
    assert row["evaluated_at"] == "2026-05-22T13:01:00+00:00"
    assert row["assessment_hash"] == "a" * 64
    assert row["evidence_ref"] == "s3://evidence/evt-001.json"
    # References only: never the raw payload hash/body or the inline risk fields.
    assert "raw_sha256" not in row
    assert "severity_score" not in row


def test_export_rows_resolve_unknown_framework_to_empty_list() -> None:
    rows = list(
        finding_exports.iter_export_rows(
            _posture([_violation(1, control_id="X-1", violation_id="X-1:evt-001")]),
            tenant_id="t",
            frameworks=FRAMEWORKS,
            limit=10,
        )
    )
    assert rows[0]["framework_ids"] == []


def test_export_rows_enforce_limit_lazily() -> None:
    def _violations():
        for index in range(1_000_000):
            yield _violation(index)

    posture = {"evaluated_at": "2026-05-22T13:01:00+00:00", "assessment_hash": None, "violations": _violations()}
    rows = list(finding_exports.iter_export_rows(posture, tenant_id="t", frameworks={}, limit=3))
    assert [row["finding_id"] for row in rows] == ["SOC2-CC6.1:evt-000", "SOC2-CC6.1:evt-001", "SOC2-CC6.1:evt-002"]


def test_jsonl_is_one_object_per_line() -> None:
    rows = finding_exports.iter_export_rows(
        _posture([_violation(1), _violation(2)]), tenant_id="t", frameworks=FRAMEWORKS, limit=10
    )
    text = "".join(finding_exports.render_jsonl(rows))
    lines = text.splitlines()
    assert len(lines) == 2
    assert text.endswith("\n")
    decoded = [json.loads(line) for line in lines]
    assert [row["finding_id"] for row in decoded] == ["SOC2-CC6.1:evt-001", "SOC2-CC6.1:evt-002"]
    assert all(row["export_schema_version"] == SCHEMA for row in decoded)


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_guards_formula_injection(prefix: str) -> None:
    rows = finding_exports.iter_export_rows(
        _posture([_violation(1, asset_id=f"{prefix}HYPERLINK(1)")]), tenant_id="t", frameworks=FRAMEWORKS, limit=10
    )
    text = "".join(finding_exports.render_csv(rows))
    parsed = list(csv.reader(io.StringIO(text)))
    header, row = parsed[0], parsed[1]
    assert header == list(finding_exports.EXPORT_COLUMNS)
    assert row[header.index("asset_id")] == f"'{prefix}HYPERLINK(1)"


def test_csv_is_rfc4180_with_header_and_joined_frameworks() -> None:
    rows = finding_exports.iter_export_rows(
        _posture([_violation(1, asset_id='bucket "quoted", with comma')]),
        tenant_id="t",
        frameworks={"SOC2-CC6.1": ["SOC 2", "ISO 27001"]},
        limit=10,
    )
    text = "".join(finding_exports.render_csv(rows))
    assert "\r\n" in text
    parsed = list(csv.reader(io.StringIO(text)))
    header, row = parsed[0], parsed[1]
    assert row[header.index("asset_id")] == 'bucket "quoted", with comma'
    assert row[header.index("framework_ids")] == "SOC 2;ISO 27001"
    assert row[header.index("snapshot_id")] == ""


def test_parse_export_limit_default_and_bounds() -> None:
    assert finding_exports.parse_export_limit(None) == finding_exports.DEFAULT_EXPORT_LIMIT
    assert finding_exports.parse_export_limit("5") == 5
    assert finding_exports.parse_export_limit(finding_exports.MAX_EXPORT_LIMIT) == finding_exports.MAX_EXPORT_LIMIT
    for bad in ("0", "-1", "abc", finding_exports.MAX_EXPORT_LIMIT + 1):
        with pytest.raises(ValueError):
            finding_exports.parse_export_limit(bad)


def test_prepare_export_reports_truncation_against_the_lake(tmp_path: Path) -> None:
    events = [
        {
            **_violation(index),
            "event_time": "2026-05-20T13:01:00Z",
            "control_ids": ["SOC2-CC6.1"],
            "asset_type": "iam_role",
            "status": "open",
        }
        for index in range(5)
    ]
    write_jsonl(tmp_path / "silver/normalized_events.jsonl", events)
    write_jsonl(
        tmp_path / "gold/control_posture.jsonl",
        [{"control_id": "SOC2-CC6.1", "framework": "SOC 2", "status": "fail", "risk_score": 80}],
    )
    export = finding_exports.prepare_export(tmp_path, tenant_id="t", fmt="jsonl", limit=2)
    lines = "".join(export.chunks).splitlines()
    assert len(lines) == 2
    assert export.truncated is True
    assert export.total_count == 5
    assert export.media_type == "application/x-ndjson"
    assert export.filename.startswith("grc-lake-findings-") and export.filename.endswith(".jsonl")


def test_prepare_export_rejects_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="format"):
        finding_exports.prepare_export(tmp_path, tenant_id="t", fmt="xlsx", limit=1)


# --- API ---------------------------------------------------------------------


@pytest.fixture
def api_env(tmp_path: Path):
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from fastapi.testclient import TestClient

    from security_lakehouse.db.base import session_scope
    from security_lakehouse.db.repository import create_api_key, create_tenant, create_user
    from security_lakehouse.server_app import create_app

    _seed_lake(tmp_path)
    app = create_app(tmp_path)
    client = TestClient(app)
    with session_scope(app.state.sessionmaker) as session:
        tenant = create_tenant(session, slug="acme", name="Acme")
        user = create_user(session, tenant_id=tenant.id, email="reader@acme.test", role="read_only")
        _key, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
        tenant_id = tenant.id
    return client, {"Authorization": f"Bearer {token}"}, tenant_id


def test_api_export_requires_auth(api_env) -> None:
    client, _headers, _tenant = api_env
    assert client.get("/api/v1/findings/export?format=csv").status_code == 401


def test_api_export_rejects_bad_format_and_limit(api_env) -> None:
    client, headers, _tenant = api_env
    bad_format = client.get("/api/v1/findings/export?format=xlsx", headers=headers)
    assert bad_format.status_code == 400
    assert bad_format.json()["errors"][0]["code"] == "bad_request"
    too_big = client.get(
        f"/api/v1/findings/export?format=csv&limit={finding_exports.MAX_EXPORT_LIMIT + 1}", headers=headers
    )
    assert too_big.status_code == 400
    assert client.get("/api/v1/findings/export?format=csv&limit=0", headers=headers).status_code == 400


def test_api_export_streams_csv_with_filename(api_env) -> None:
    client, headers, tenant_id = api_env
    response = client.get("/api/v1/findings/export?format=csv", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="grc-lake-findings-')
    assert disposition.endswith('.csv"')
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-export-schema-version"] == SCHEMA
    assert response.headers["x-export-truncated"] == "false"
    parsed = list(csv.reader(io.StringIO(response.text)))
    assert parsed[0] == list(finding_exports.EXPORT_COLUMNS)
    assert len(parsed) == 2
    row = dict(zip(parsed[0], parsed[1], strict=True))
    assert row["finding_id"] == "SOC2-CC6.1:evt-001"
    assert row["tenant_id"] == tenant_id
    assert row["framework_ids"] == "SOC 2"


def test_api_export_jsonl_default_and_limit(api_env) -> None:
    client, headers, _tenant = api_env
    response = client.get("/api/v1/findings/export", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["content-disposition"].endswith('.jsonl"')
    rows = [json.loads(line) for line in response.text.splitlines()]
    assert [row["finding_id"] for row in rows] == ["SOC2-CC6.1:evt-001"]
    assert response.headers["x-export-limit"] == str(finding_exports.DEFAULT_EXPORT_LIMIT)
    limited = client.get("/api/v1/findings/export?format=jsonl&limit=1", headers=headers)
    assert limited.headers["x-export-limit"] == "1"


def test_api_export_is_in_the_resource_catalog() -> None:
    from security_lakehouse import api_v1

    rows = {row["path"]: row for row in api_v1.resource_catalog()}
    row = rows["/api/v1/findings/export"]
    assert row["methods"] == ["GET"]
    assert row["scopes"] == ["read"]
    assert set(row["query"]) >= {"format", "limit"}


def test_local_server_serves_the_export(tmp_path: Path) -> None:
    from test_api_v1 import _spin

    server = _spin(tmp_path)
    try:
        host, port = server.server_address
        with urllib.request.urlopen(f"http://{host}:{port}/api/v1/findings/export?format=csv&limit=5") as response:
            assert response.status == 200
            assert response.headers["content-type"].startswith("text/csv")
            assert response.headers["content-disposition"].endswith('.csv"')
            body = response.read().decode("utf-8")
        parsed = list(csv.reader(io.StringIO(body)))
        assert parsed[0] == list(finding_exports.EXPORT_COLUMNS)
        assert len(parsed) == 2
    finally:
        server.shutdown()


# --- CLI ---------------------------------------------------------------------


def test_cli_violations_json_default_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_lake(tmp_path)
    assert main(["assessment", "violations", "--lake", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["violations"][0]["violation_id"] == "SOC2-CC6.1:evt-001"


def test_cli_violations_csv_and_jsonl_write_to_out(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lake = tmp_path / "lake"
    lake.mkdir()
    _seed_lake(lake)
    csv_path = tmp_path / "findings.csv"
    assert main(["assessment", "violations", "--lake", str(lake), "--format", "csv", "--out", str(csv_path)]) == 0
    parsed = list(csv.reader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
    assert parsed[0] == list(finding_exports.EXPORT_COLUMNS)
    assert parsed[1][parsed[0].index("finding_id")] == "SOC2-CC6.1:evt-001"
    assert capsys.readouterr().out == ""

    jsonl_path = tmp_path / "findings.jsonl"
    assert main(["assessment", "violations", "--lake", str(lake), "--format", "jsonl", "--out", str(jsonl_path)]) == 0
    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["export_schema_version"] == SCHEMA
    assert rows[0]["framework_ids"] == ["SOC 2"]


def test_cli_violations_jsonl_streams_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_lake(tmp_path)
    assert main(["assessment", "violations", "--lake", str(tmp_path), "--format", "jsonl"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["finding_id"] for row in rows] == ["SOC2-CC6.1:evt-001"]


# --- MCP ---------------------------------------------------------------------


def test_mcp_export_findings_local_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from test_mcp_server import _seeded_server, call_tool, tool_names

    monkeypatch.setenv("GRC_LAKE_MCP_MODE", "local")
    server = _seeded_server(tmp_path)
    assert "export_findings" in tool_names(server)
    text = call_tool(server, "export_findings", format="jsonl", limit=5)
    rows = [json.loads(line) for line in str(text).splitlines()]
    assert [row["finding_id"] for row in rows] == ["SOC2-CC6.1:evt-001"]
    csv_text = call_tool(server, "export_findings", format="csv", limit=5)
    assert list(csv.reader(io.StringIO(str(csv_text))))[0] == list(finding_exports.EXPORT_COLUMNS)


def test_mcp_export_findings_remote_mode_proxies_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from security_lakehouse import mcp_server, netguard
    from test_mcp_server import _seeded_server, call_tool

    captured: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int = -1) -> bytes:
            return b'{"finding_id": "SOC2-CC6.1:evt-001"}\n'

    def fake_urlopen(request: urllib.request.Request, *, timeout: float):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["accept"] = request.get_header("Accept")
        return Response()

    def _no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("real urlopen must not be called")

    monkeypatch.setenv("GRC_LAKE_MCP_MODE", "remote")
    monkeypatch.setenv("GRC_LAKE_API_URL", "https://trustops.example.test/")
    monkeypatch.setenv("GRC_LAKE_API_KEY", "secret-token")
    monkeypatch.setattr(mcp_server, "_open_api_request", fake_urlopen)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(netguard, "assert_url_is_public", lambda url, **_kw: url.split("//", 1)[1].split("/")[0])

    server = _seeded_server(tmp_path)
    text = call_tool(server, "export_findings", format="jsonl", limit=7)
    assert json.loads(str(text).strip())["finding_id"] == "SOC2-CC6.1:evt-001"
    assert captured["url"] == "https://trustops.example.test/api/v1/findings/export?format=jsonl&limit=7"
    assert captured["authorization"] == "Bearer secret-token"
    assert captured["accept"] == "application/x-ndjson"


def test_mcp_export_findings_rejects_bad_format_and_clamps_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from test_mcp_server import _seeded_server, call_tool

    monkeypatch.setenv("GRC_LAKE_MCP_MODE", "local")
    server = _seeded_server(tmp_path)
    with pytest.raises(Exception, match="format"):
        call_tool(server, "export_findings", format="xlsx", limit=5)
    with pytest.raises(Exception, match="limit"):
        call_tool(server, "export_findings", format="csv", limit=finding_exports.MAX_EXPORT_LIMIT + 1)
