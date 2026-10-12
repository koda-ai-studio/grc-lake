"""Transport-independent assessments preserve publication and ownership contracts."""

import ast
from pathlib import Path

import pytest

from security_lakehouse.execution_mode import server_execution


def test_service_has_no_transport_dependencies():
    path = Path("src/security_lakehouse/services/assessments.py")
    assert path.exists()
    tree = ast.parse(path.read_text())
    imports = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(
        any(p in name.split(".") for p in ("api_v1", "api_contract", "server_app", "cli", "mcp_server", "fastapi"))
        for name in imports
    )


def test_service_rejects_conflicting_tenant_before_work(tmp_path):
    from security_lakehouse.services.assessments import AssessmentContext, EvaluationCommand, evaluate

    with server_execution("owner"), pytest.raises(ValueError, match="tenant"):
        evaluate(tmp_path, EvaluationCommand(), AssessmentContext(tenant_id="other", actor="operator"))
    assert not (tmp_path / "manifest.json").exists()


def test_expected_generation_cannot_overwrite_newer_evidence(tmp_path):
    from security_lakehouse.pipeline import run_pipeline
    from security_lakehouse.services.assessments import AssessmentContext, EvaluationCommand, evaluate

    run_pipeline("data/raw/security_events.jsonl", tmp_path)
    before = (tmp_path / ".active-generation").readlink()
    with pytest.raises(ValueError, match="generation"):
        evaluate(tmp_path, EvaluationCommand(), AssessmentContext(expected_generation="outdated"))
    assert (tmp_path / ".active-generation").readlink() == before


def test_failed_controls_are_successful_execution_with_committed_evidence(tmp_path):
    from security_lakehouse.pipeline import run_pipeline
    from security_lakehouse.services.assessments import AssessmentContext, EvaluationCommand, evaluate

    run_pipeline("data/raw/security_events.jsonl", tmp_path)
    result = evaluate(tmp_path, EvaluationCommand(), AssessmentContext())
    assert result.data["result"] == "ok"
    assert result.outcome["publication"] == "committed"
    assert result.outcome["generation_id"] == (tmp_path / ".active-generation").readlink().name
    assert result.outcome["execution"] == "completed"
    assert result.outcome["assessment_verdict"] == "see_generation"


def test_oversized_job_response_retains_success_and_result_reference(tmp_path, monkeypatch):
    from security_lakehouse import operation_jobs
    from security_lakehouse.auth.dependencies import _INSECURE_IDENTITY
    from security_lakehouse.server_app import create_app

    app = create_app(tmp_path, require_auth=False)
    queue = app.state.operation_queue
    job = queue.enqueue(_INSECURE_IDENTITY, "/api/v1/snapshots", {}, "size")
    row = queue.claim()
    monkeypatch.setattr(operation_jobs, "RESULT_LIMIT", 64)
    queue.finish(
        row,
        201,
        {
            "data": {"padding": "x" * 200},
            "meta": {"result_url": "/api/v1/operations/" + row.id + "/result"},
            "errors": [],
        },
    )
    stored = queue.get(_INSECURE_IDENTITY.tenant_id, job["id"], viewer=_INSECURE_IDENTITY)
    assert stored["status"] == "succeeded"
    assert stored["response"]["meta"]["result_url"].endswith("/result")


def test_durable_result_survives_lost_job_completion_and_is_authorized(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from security_lakehouse import api_v1
    from security_lakehouse.pipeline import run_pipeline
    from test_operation_jobs import _authenticated

    app, _, headers, other = _authenticated(tmp_path)
    client = TestClient(app)
    assert client.post("/api/v1/ingestion/eval", json={}, headers=headers).status_code == 202
    row = app.state.operation_queue.claim()
    run_pipeline("data/raw/security_events.jsonl", tmp_path / "tenants" / row.tenant_id, tenant_id=row.tenant_id)
    monkeypatch.setattr(api_v1, "handle_post", lambda *a, **kw: pytest.fail("assessment dispatched through HTTP"))
    code, payload = app.state.operation_worker.subprocess_execute(tmp_path, row)
    assert code == 201
    # Deliberately omit queue.finish: publication succeeded but the reply was lost.
    url = payload["meta"]["result_url"]
    receipt = client.get(url, headers=headers)
    assert receipt.status_code == 200
    assert receipt.json()["data"]["response"]["meta"]["outcome"]["publication"] == "committed"
    assert client.get(url, headers=other).status_code == 404
    from security_lakehouse.operation_receipts import result_path

    path = result_path(tmp_path / "tenants" / row.tenant_id, row.id)
    path.write_text(path.read_text().replace("grc.operation_result.v1", "grc.operation_result.v999"))
    assert client.get(url, headers=headers).json()["errors"][0]["code"] == "integrity_failure"


def test_distributed_receipt_recovers_committed_result_across_replicas(replicas, tmp_path):
    from fastapi.testclient import TestClient

    from security_lakehouse.operation_execution import execute_operation

    apps, credentials = replicas
    tenant, headers = credentials[0]
    client = TestClient(apps[0])
    job = client.post("/api/v1/snapshots", json={}, headers={**headers, "Prefer": "respond-async"}).json()["data"]
    row = apps[0].state.operation_queue.claim()
    code, response = execute_operation(tmp_path / "0", row, factory=apps[0].state.sessionmaker, require_auth=True)
    assert code == 201
    # No finish call: discover only the result from the authoritative manifest.
    result = TestClient(apps[1]).get(response["meta"]["result_url"], headers=headers)
    assert result.status_code == 200
    assert result.json()["data"]["operation_id"] == job["id"]
    assert result.json()["data"]["response"]["meta"]["outcome"]["publication"] == "committed"
    assert TestClient(apps[1]).get(response["meta"]["result_url"], headers=credentials[1][1]).status_code == 404
