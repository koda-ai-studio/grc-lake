"""Explicit account populations are pinned to each organization evaluation."""

import pytest

from security_lakehouse import connector_runner as runner
from security_lakehouse import organization_scopes as scopes
from security_lakehouse.connections import sync_connection
from security_lakehouse.io import read_json, read_jsonl
from test_named_connections import event, prepare


def test_scoped_ingestion_evaluation_and_revision_preserve_other_accounts(tmp_path, monkeypatch):
    for name in ["a", "b", "c", "d", "e", "f", "g"]:
        prepare(tmp_path, name, name)
    selected = ["a", "c", "e", "g"]
    saved = scopes.save_organization(tmp_path, organization_id="org", name="Organization", connection_ids=selected)
    called = []

    def collect(*args, **kwargs):
        account = kwargs["options"]["account"]
        called.append(account)
        return [event(account)]

    monkeypatch.setattr(runner, "_collect", collect)
    result = scopes.ingest_organization(tmp_path, "org")
    assert set(called) == set(selected)
    assert result["result"] == "ok"
    evaluation = scopes.evaluate_organization(tmp_path, "org")
    run = tmp_path / "organizations/org/evaluations" / evaluation["evaluation_id"]
    rows = read_jsonl(run / "silver/normalized_events.jsonl")
    assert {row["source_account_id"] for row in rows} == set(selected)
    receipt = read_json(run / "scope.json")
    assert receipt["scope"]["revision"] == saved["revision"]
    assert len(receipt["inputs"]) == 4
    assert all(row["raw_sha256"] and row["run_id"] for row in receipt["inputs"])
    before = (run / "bronze/raw_events.jsonl").read_bytes()
    scopes.save_organization(
        tmp_path, organization_id="org", name="Organization", connection_ids=["b"], expected_revision=1
    )
    sync_connection(tmp_path, "a", materialize=False)
    assert (run / "bronze/raw_events.jsonl").read_bytes() == before
    assert not (tmp_path / "gold/ccf_assessment.json").exists()
    assert (run / "gold/ccf_assessment.json").exists()


def test_one_failed_account_does_not_skip_others_or_report_complete(tmp_path, monkeypatch):
    for name in ["a", "b", "c"]:
        prepare(tmp_path, name, name)
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a", "b", "c"])

    def collect(*args, **kwargs):
        account = kwargs["options"]["account"]
        if account == "b":
            raise ValueError("provider secret must not reach public results")
        return [event(account)]

    monkeypatch.setattr(runner, "_collect", collect)
    result = scopes.ingest_organization(tmp_path, "org")
    assert result["result"] == "partial"
    assert [r["connection_id"] for r in result["connections"]] == ["a", "b", "c"]
    assert "provider secret" not in str(result)
    evaluation = scopes.evaluate_organization(tmp_path, "org")
    assert evaluation["coverage"] == "partial"
    assert evaluation["unavailable_connections"] == ["b"]
    run = tmp_path / "organizations/org/evaluations" / evaluation["evaluation_id"]
    rows = read_jsonl(run / "silver/normalized_events.jsonl")
    assert any(r["source_account_id"] == "b" and r["status"] == "not_evaluated" for r in rows)


def test_scope_rejects_unknown_cross_tenant_duplicate_and_stale_revision(tmp_path):
    prepare(tmp_path, "a", "a")
    for selected in [[], ["missing"], ["a", "a"]]:
        with pytest.raises((ValueError, FileNotFoundError)):
            scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=selected)
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a"])
    with pytest.raises(ValueError):
        scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a"])
    with pytest.raises(FileNotFoundError):
        scopes.evaluate_organization(tmp_path / "other", "org")
    with pytest.raises(ValueError):
        scopes.save_organization(tmp_path, organization_id="../escape", name="Org", connection_ids=["a"])


def test_scope_manifest_digest_is_retained_in_evidence(tmp_path, monkeypatch):
    from security_lakehouse.io import canonical_sha256

    prepare(tmp_path, "a", "a")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("a")])
    sync_connection(tmp_path, "a", materialize=False)
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a"])
    evaluation = scopes.evaluate_organization(tmp_path, "org")
    run = tmp_path / "organizations/org/evaluations" / evaluation["evaluation_id"]
    receipt = read_json(run / "scope.json")
    rows = read_jsonl(run / "bronze/raw_events.jsonl")
    assert rows[0]["raw"]["attributes"]["organization_scope_digest"] == canonical_sha256(receipt)


def test_organization_api_cli_and_mcp_share_scope(tmp_path, capsys):
    import asyncio
    import json

    from security_lakehouse import api_v1, cli, mcp_server
    from security_lakehouse.api_contract import required_post_scope
    from test_mcp_server import call_tool

    prepare(tmp_path, "a", "a")
    status, body = api_v1.handle_post(
        "/api/v1/organizations", {"organization_id": "org", "name": "Org", "connection_ids": ["a"]}, tmp_path
    )
    assert status == 201
    assert required_post_scope("/api/v1/organizations/org/evaluate") == "connector_manage"
    assert api_v1.handle_get("/api/v1/organizations", {}, tmp_path)[1]["data"][0]["organization_id"] == "org"
    assert cli.main(["organizations", "list", "--lake", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["organization_id"] == "org"
    server = mcp_server.build_server(tmp_path)
    assert call_tool(server, "list_organizations")[0]["organization_id"] == "org"
    result = asyncio.run(
        server.call_tool("save_organization", {"organization_id": "other", "name": "Other", "connection_ids": ["a"]})
    )
    assert result
    assert len(scopes.list_organizations(tmp_path)) == 2


def test_queued_operation_cannot_collect_a_later_scope(tmp_path, monkeypatch):
    for name in ["a", "b"]:
        prepare(tmp_path, name, name)
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a"])
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["b"], expected_revision=1)
    called = []
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: called.append(True))
    with pytest.raises(ValueError, match="scope changed"):
        scopes.ingest_organization(tmp_path, "org", expected_revision=1)
    assert called == []


def test_hosted_organization_job_is_revision_bound_and_tenant_private(tmp_path):
    from fastapi.testclient import TestClient

    from security_lakehouse.db.models import ApiKey
    from test_operation_jobs import _authenticated

    app, key_id, headers, other = _authenticated(tmp_path)
    with app.state.sessionmaker() as session:
        tenant_id = session.get(ApiKey, key_id).tenant_id
    lake = tmp_path / "tenants" / tenant_id
    prepare(lake, "a", "a")
    scopes.save_organization(lake, organization_id="org", name="Org", connection_ids=["a"])
    client = TestClient(app)
    response = client.post(
        "/api/v1/organizations/org/evaluate",
        headers={**headers, "Idempotency-Key": "revision-bound"},
        json={"expected_revision": 1},
    )
    assert response.status_code == 202, response.text
    job = response.json()["data"]
    assert client.get(job["status_url"], headers=other).status_code == 404
    assert client.get("/api/v1/organizations", headers=other).json()["data"] == []
    assert (
        client.post("/api/v1/organizations/org/evaluate", headers=other, json={"expected_revision": 1}).status_code
        == 403
    )
    scopes.save_organization(lake, organization_id="org", name="Changed", connection_ids=["a"], expected_revision=1)
    app.state.operation_worker.run_once()
    result = client.get(job["status_url"], headers=headers).json()["data"]
    assert result["status"] == "failed"
    assert not (lake / "organizations/org/evaluations").exists()


def test_changed_scope_receipt_cannot_be_presented_as_a_verified_assessment(tmp_path, monkeypatch):
    from security_lakehouse import api_v1
    from security_lakehouse.io import write_json

    prepare(tmp_path, "a", "a")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("a")])
    sync_connection(tmp_path, "a", materialize=False)
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a"])
    result = scopes.evaluate_organization(tmp_path, "org")
    endpoint = f"/api/v1/organizations/org/evaluations/{result['evaluation_id']}/assessment"
    assert api_v1.handle_get(endpoint, {}, tmp_path)[0] == 200
    run = tmp_path / "organizations/org/evaluations" / result["evaluation_id"]
    receipt = read_json(run / "scope.json")
    receipt["scope"]["connection_ids"] = ["other-account"]
    write_json(run / "scope.json", receipt)
    assert api_v1.handle_get(endpoint, {}, tmp_path)[0] == 400


def test_real_cloud_evidence_ccf_results_keep_selected_source_accounts(tmp_path):
    from pathlib import Path

    from security_lakehouse.connector_state import append_config_event

    for number in range(3):
        account = f"00000000000{number}"
        child = prepare(tmp_path, f"aws-{number}", account)
        append_config_event(
            child,
            connector_id="aws-posture",
            state="enabled",
            actor="test",
            credentials={"account_id": account},
            options={"fixture_dir": str(Path(__file__).parent / "fixtures/aws")},
        )
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["aws-0", "aws-2"])
    assert scopes.ingest_organization(tmp_path, "org")["result"] == "ok"
    result = scopes.evaluate_organization(tmp_path, "org")
    run = scopes.verify_organization_evaluation(tmp_path, "org", result["evaluation_id"])
    assessment = read_json(run / "gold/ccf_assessment.json")
    assert {r["source_tenant_id"] for r in assessment["asset_results"]} == {"000000000000", "000000000002"}
    assert assessment["population_completeness"] == "not_established"


def test_scoped_evaluation_cannot_replace_ambient_tenant_warehouse(tmp_path, monkeypatch):
    from security_lakehouse import lake_eval, lake_scale

    prepare(tmp_path, "a", "a")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("a")])
    sync_connection(tmp_path, "a", materialize=False)
    scopes.save_organization(tmp_path, organization_id="org", name="Org", connection_ids=["a"])
    monkeypatch.setattr(lake_scale, "WAREHOUSE_ROW_THRESHOLD", 1)
    monkeypatch.setenv("GRC_LAKE_DUCKDB_PATH", str(tmp_path / "tenant-wide.duckdb"))
    exported = []
    monkeypatch.setattr(lake_eval, "land_if_configured", lambda *a, **kw: exported.append(True) or {"ok": True})
    result = scopes.evaluate_organization(tmp_path, "org")
    assert exported == []
    assert result["result"] == "error"
    assert result["evaluation"]["mode"] == "warehouse_required"


def test_background_organization_evaluation_accepts_browser_idempotency_metadata(tmp_path):
    from fastapi.testclient import TestClient

    from security_lakehouse.db.models import ApiKey
    from test_operation_jobs import _authenticated

    app, key_id, headers, _ = _authenticated(tmp_path)
    with app.state.sessionmaker() as session:
        tenant_id = session.get(ApiKey, key_id).tenant_id
    lake = tmp_path / "tenants" / tenant_id
    prepare(lake, "a", "a")
    scopes.save_organization(lake, organization_id="org", name="Org", connection_ids=["a"])
    client = TestClient(app)
    response = client.post(
        "/api/v1/organizations/org/evaluate",
        headers={**headers, "Idempotency-Key": "organization-evaluation"},
        json={"expected_revision": 1},
    )
    assert response.status_code == 202
    job = response.json()["data"]
    app.state.operation_worker.run_once()
    result = client.get(job["status_url"], headers=headers).json()["data"]
    assert result["status"] == "succeeded", result
    assert result["response"]["data"]["coverage"] == "partial"
