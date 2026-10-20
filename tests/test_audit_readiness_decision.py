"""Strong aggregate scores must not hide an unresolved framework assessment."""

from copy import deepcopy
from pathlib import Path

import pytest

from security_lakehouse import audit_readiness
from test_audit_readiness import _readiness


@pytest.fixture
def ready_environment(monkeypatch):
    """Hold operational prerequisites constant to isolate the scope decision."""
    payload = {
        "posture": {"score": 100, "open_violation_count": 0},
        "frameworks": [
            {"framework": "SOC 2", "score": 100, "control_count": 61, "state": "ready"},
            {"framework": "ISO 27001:2022", "score": 100, "control_count": 93, "state": "ready"},
            {"framework": "NIST AI RMF", "score": 100, "control_count": 72, "state": "ready"},
        ],
        "evidence_freshness": {"count": 1, "stale_count": 0},
    }
    monkeypatch.setattr(audit_readiness, "build_current_posture", lambda _: deepcopy(payload))
    monkeypatch.setattr(audit_readiness, "read_jsonl", lambda *a, **kw: [{"result": "pass"}])
    monkeypatch.setattr(audit_readiness, "build_ingestion_status", lambda _: {"summary": {"enabled_connectors": 1}})
    monkeypatch.setattr(audit_readiness.trust_share, "list_shares", lambda _: [{"role": "auditor"}])
    monkeypatch.setattr(audit_readiness.remediation, "list_evidence_requests", lambda *a, **kw: [])
    monkeypatch.setattr(
        audit_readiness.access_review_services, "list_campaigns", lambda *a, **kw: [{"status": "active"}]
    )
    monkeypatch.setattr(
        audit_readiness,
        "_personnel_summary",
        lambda *a, **kw: {"identity_connectors": 1, "active_campaigns": 1, "pending_certifications": 0},
    )
    monkeypatch.setattr(audit_readiness, "_vendor_risk_summary", lambda *a, **kw: {"total": 1, "overdue": 0, "open": 0})
    return payload


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"control_count": 1}, "insufficient_coverage"),
        ({"framework": "Unknown standard"}, "unknown_coverage"),
        ({"score": 99}, "score_below_threshold"),
        ({"state": "attention_required"}, "assessment_not_ready"),
        ({"control_count": 72, "not_evaluated_control_count": 72}, "insufficient_coverage"),
    ],
)
def test_high_score_cannot_override_framework_gate(tmp_path: Path, ready_environment, change, reason):
    ready_environment["frameworks"][-1].update(change)
    data = _readiness(tmp_path, "blocked-framework")
    assert data["audit_score"] == 93
    assert data["state"] == "on_track"
    assert any(gap["id"] == "framework_readiness" for gap in data["gaps"])
    assert reason in data["frameworks"][-1]["blocking_reasons"]
    gates = {gate["id"]: gate for gate in data["readiness_decision"]["gates"]}
    assert gates["score"]["passed"] is True
    assert gates["frameworks"]["passed"] is False
    assert gates["blocking_gaps"]["passed"] is False


def test_ready_decision_requires_all_gates(tmp_path: Path, ready_environment):
    data = _readiness(tmp_path, "ready-frameworks")
    assert data["state"] == "audit_ready"
    assert data["audit_score"] == 100
    assert data["gaps"] == []
    assert all(gate["passed"] for gate in data["readiness_decision"]["gates"])
    assert all(row["blocking_reasons"] == [] for row in data["frameworks"])


def test_missing_framework_scope_is_an_actionable_gap(tmp_path: Path, ready_environment):
    ready_environment["frameworks"] = []
    data = _readiness(tmp_path, "missing-frameworks")
    assert data["state"] != "audit_ready"
    assert any(gap["id"] == "framework_readiness" for gap in data["gaps"])
    gates = {gate["id"]: gate for gate in data["readiness_decision"]["gates"]}
    assert gates["frameworks"]["passed"] is False


def test_operational_gap_still_blocks_complete_frameworks(tmp_path: Path, ready_environment, monkeypatch):
    monkeypatch.setattr(audit_readiness.trust_share, "list_shares", lambda _: [])
    data = _readiness(tmp_path, "missing-share")
    assert data["audit_score"] == 100
    assert data["state"] == "on_track"
    gates = {gate["id"]: gate for gate in data["readiness_decision"]["gates"]}
    assert gates["frameworks"]["passed"] is True
    assert gates["blocking_gaps"]["passed"] is False


def test_score_gate_still_blocks_otherwise_ready_assessment(tmp_path: Path, ready_environment):
    ready_environment["posture"]["score"] = 40
    data = _readiness(tmp_path, "low-index")
    assert data["audit_score"] == 73
    assert data["state"] == "on_track"
    gates = {gate["id"]: gate for gate in data["readiness_decision"]["gates"]}
    assert gates["score"]["passed"] is False
    assert gates["frameworks"]["passed"] is True
    assert gates["blocking_gaps"]["passed"] is True


def test_readiness_decision_api_uses_only_authenticated_tenant_evidence(tmp_path: Path):
    from fastapi.testclient import TestClient

    from security_lakehouse import tenancy
    from security_lakehouse.server_app import create_app
    from test_api_v1 import _seed_lake
    from test_tenant_isolation import _bearer, _provision_tenant

    app = create_app(tmp_path)
    tenant_a, token_a = _provision_tenant(app, "evidence-owner")
    _, token_b = _provision_tenant(app, "empty-reviewer")
    lake_a = tmp_path / tenancy.TENANTS_DIRNAME / tenant_a
    lake_a.mkdir(parents=True)
    _seed_lake(lake_a)
    client = TestClient(app)
    endpoint = "/api/v1/platform/audit-readiness"
    assert client.get(endpoint).status_code == 401
    a = client.get(endpoint, headers=_bearer(token_a))
    b = client.get(endpoint, headers=_bearer(token_b))
    assert a.status_code == b.status_code == 200
    data_a, data_b = a.json()["data"], b.json()["data"]
    assert len(data_a["frameworks"]) == 2
    assert data_b["frameworks"] == []
    assert data_a["readiness_decision"]["gates"][1]["detail"].startswith("0 of 2")
    assert data_b["readiness_decision"]["gates"][1]["detail"].startswith("0 of 0")
    assert data_b["audit_score"] == 0
    for data in (data_a, data_b):
        assert (data["state"] == "audit_ready") == all(gate["passed"] for gate in data["readiness_decision"]["gates"])
