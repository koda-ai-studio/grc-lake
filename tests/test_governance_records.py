"""Scoped implementations and risk decisions preserve basis and human authority."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from security_lakehouse.db.base import session_scope
from security_lakehouse.db.repository import create_api_key, create_tenant, create_user
from security_lakehouse.io import write_jsonl
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.server_app import create_app
from test_agent_decision_authority import human
from test_assurance_truth import complete_events
from test_remediation import _bearer


@pytest.fixture
def model_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRC_LAKE_COOKIE_SIGNING_KEY", "test-governance-records-signing-key")
    app = create_app(tmp_path)
    with session_scope(app.state.sessionmaker) as session:
        tenant = create_tenant(session, slug="model", name="Model fixture")
        tokens = []
        for name in ("requester", "reviewer"):
            user = create_user(session, tenant_id=tenant.id, email=name + "@example.test", role="admin")
            _, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
            tokens.append(token)
        other = create_tenant(session, slug="other", name="Other")
        user = create_user(session, tenant_id=other.id, email="other@example.test", role="admin")
        _, foreign = create_api_key(session, tenant_id=other.id, user_id=user.id)
    raw = tmp_path / "events.jsonl"
    rows = complete_events()
    for row in rows:
        row["safeguard_ids"] = ["SG-IDENTITY-001"]
    write_jsonl(raw, rows)
    run_pipeline(raw, tmp_path / "tenants" / tenant.id, tenant_id=tenant.id)
    return app, TestClient(app), tokens, foreign


def body():
    return {
        "kind": "risk_acceptance",
        "rationale": "Temporary change with monitored compensating access controls.",
        "residual_risk": "Restricted access remains under review.",
        "scope": {
            "safeguard_ids": ["SG-IDENTITY-001"],
            "control_ids": ["SOC2-CC6.1"],
            "assets": [{"source_account_id": "audit", "asset_id": "role-1"}],
        },
        "evidence_event_ids": ["assurance-0"],
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    }


def test_decision_requires_independent_human_review_and_preserves_extension_history(model_env):
    app, client, tokens, foreign = model_env
    requester, reviewer = (human(app, t) for t in tokens)
    created = client.post("/api/v1/governance/decisions", json=body(), headers=requester)
    assert created.status_code == 201, created.text
    row = created.json()["data"]
    url = "/api/v1/governance/decisions/" + row["id"] + "/reviews"
    review = {
        "decision": "approve",
        "rationale": "Reviewed scope and residual risk.",
        "content_sha256": row["content_sha256"],
    }
    assert not row["active"]
    assert client.post(url, json=review, headers=requester).status_code == 400
    assert client.post(url, json=review, headers=_bearer(tokens[1])).status_code == 403
    assert client.post(url, json=review, headers=human(app, foreign)).status_code == 404
    approved = client.post(url, json=review, headers=reviewer)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["active"]
    extension = {
        **body(),
        "supersedes_id": row["id"],
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
    }
    later = client.post("/api/v1/governance/decisions", json=extension, headers=requester).json()["data"]
    assert not later["active"]
    approved = client.post(
        "/api/v1/governance/decisions/" + later["id"] + "/reviews",
        json={**review, "content_sha256": later["content_sha256"]},
        headers=reviewer,
    )
    assert approved.status_code == 200, approved.text
    history = client.get("/api/v1/governance/decisions", headers=requester).json()["data"]
    old = next(r for r in history if r["id"] == row["id"])
    assert old["content"] == row["content"]
    assert not old["active"] and old["superseded"]
    assert client.post(url, json=review, headers=reviewer).status_code == 409


def test_scoped_implementation_is_versioned_and_cannot_supply_a_verdict(model_env):
    app, client, tokens, _ = model_env
    headers = human(app, tokens[0])
    request = {
        "safeguard_id": "SG-IDENTITY-001",
        "owner": "Security",
        "system": "Identity",
        "cadence_days": 7,
        "scope": body()["scope"],
        "evidence_event_ids": ["assurance-0"],
    }
    response = client.post("/api/v1/ccf/implementations", json=request, headers=headers)
    assert response.status_code == 201, response.text
    first = response.json()["data"]
    assert first["basis_verified"]
    second = client.post(
        "/api/v1/ccf/implementations", json={**request, "owner": "GRC", "supersedes_id": first["id"]}, headers=headers
    )
    assert second.status_code == 201, second.text
    assert second.json()["data"]["definition_sha256"] == first["definition_sha256"]
    assert "status" not in second.json()["data"]["content"]
    duplicate = client.post(
        "/api/v1/ccf/implementations", json={**request, "supersedes_id": first["id"]}, headers=headers
    )
    assert duplicate.status_code == 409


def test_scope_and_evidence_must_match_verified_tenant_generation(model_env):
    app, client, tokens, _ = model_env
    headers = human(app, tokens[0])
    for patch in [
        {"evidence_event_ids": ["absent"]},
        {"scope": {"safeguard_ids": ["UNKNOWN"]}},
        {"expires_at": "2000-01-01T00:00:00Z"},
    ]:
        response = client.post("/api/v1/governance/decisions", json={**body(), **patch}, headers=headers)
        assert response.status_code in (400, 422)


def test_definition_change_invalidates_pending_and_active_decision_basis(model_env, monkeypatch):
    from security_lakehouse import governance_records

    app, client, tokens, _ = model_env
    request_headers = human(app, tokens[0])
    review_headers = human(app, tokens[1])
    row = client.post("/api/v1/governance/decisions", json=body(), headers=request_headers).json()["data"]
    original = governance_records.load_safeguards

    def changed():
        payload = original()
        payload["safeguards"][0]["objective"] = "Different obligation"
        return payload

    monkeypatch.setattr(governance_records, "load_safeguards", changed)
    result = client.post(
        "/api/v1/governance/decisions/" + row["id"] + "/reviews",
        json={"decision": "approve", "rationale": "Review", "content_sha256": row["content_sha256"]},
        headers=review_headers,
    )
    assert result.status_code == 400
    current = client.get("/api/v1/governance/decisions", headers=request_headers).json()["data"][0]
    assert current["basis_verified"] is False and current["active"] is False


def test_revocation_keeps_approval_history_and_does_not_rewrite_assessment(model_env):
    from security_lakehouse.db.models import GovernanceDecision
    from security_lakehouse.io import canonical_sha256, read_json

    app, client, tokens, foreign = model_env
    requester, reviewer = (human(app, t) for t in tokens)
    row = client.post("/api/v1/governance/decisions", json=body(), headers=requester).json()["data"]
    # Find the owned lake from the fixture's database location.
    with session_scope(app.state.sessionmaker) as session:
        database_path = session.get_bind().url.database
    from pathlib import Path

    lake = Path(database_path).parent.parent / "tenants" / row["platform_tenant_id"]
    before = canonical_sha256(read_json(lake / "gold/current_posture.json"))
    review = {"decision": "approve", "rationale": "Reviewed", "content_sha256": row["content_sha256"]}
    url = "/api/v1/governance/decisions/" + row["id"] + "/reviews"
    assert client.post(url, json=review, headers=reviewer).json()["data"]["active"]
    revoked = client.post(url, json={**review, "decision": "revoke"}, headers=requester)
    assert revoked.status_code == 200
    assert revoked.json()["data"]["approved"] and revoked.json()["data"]["revoked"]
    assert not revoked.json()["data"]["active"]
    assert [r["decision"] for r in revoked.json()["data"]["reviews"]] == ["approve", "revoke"]
    assert client.get("/api/v1/governance/decisions", headers=human(app, foreign)).json()["data"] == []
    assert client.get("/api/v1/governance/decisions").status_code == 401
    after = canonical_sha256(read_json(lake / "gold/current_posture.json"))
    assert after == before
    with session_scope(app.state.sessionmaker) as session:
        stored = session.get(GovernanceDecision, row["id"])
        stored.content_json = stored.content_json.replace("Restricted access", "Changed access")
    assert client.get("/api/v1/governance/decisions", headers=requester).status_code == 409


def test_approved_decision_expires_at_read_time_and_catalog_changes_disable_it(model_env, monkeypatch):
    from security_lakehouse import governance_records

    app, client, tokens, _ = model_env
    requester, reviewer = (human(app, t) for t in tokens)
    row = client.post("/api/v1/governance/decisions", json=body(), headers=requester).json()["data"]
    url = "/api/v1/governance/decisions/" + row["id"] + "/reviews"
    approved = client.post(
        url,
        json={"decision": "approve", "rationale": "Reviewed", "content_sha256": row["content_sha256"]},
        headers=reviewer,
    )
    assert approved.json()["data"]["active"]
    real = governance_records.datetime

    class Future(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + timedelta(days=8)

    monkeypatch.setattr(governance_records, "datetime", Future)
    current = client.get("/api/v1/governance/decisions", headers=requester).json()["data"][0]
    assert current["approved"] and not current["active"] and current["basis_verified"]
    monkeypatch.setattr(governance_records, "datetime", real)
    original = governance_records.load_control_map

    def changed():
        controls = original()
        controls["SOC2-CC6.1"]["evidence_requirement"] = "Changed requirement"
        return controls

    monkeypatch.setattr(governance_records, "load_control_map", changed)
    current = client.get("/api/v1/governance/decisions", headers=requester).json()["data"][0]
    assert current["approved"] and not current["active"] and not current["basis_verified"]


def test_extension_approval_and_predecessor_revocation_serialize(model_env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    app, client, tokens, _ = model_env
    requester, reviewer = (human(app, t) for t in tokens)
    original = client.post("/api/v1/governance/decisions", json=body(), headers=requester).json()["data"]

    def review(row, action):
        return client.post(
            "/api/v1/governance/decisions/" + row["id"] + "/reviews",
            json={
                "decision": action,
                "rationale": "Concurrent decision review",
                "content_sha256": row["content_sha256"],
            },
            headers=reviewer,
        )

    assert review(original, "approve").status_code == 200
    extension = client.post(
        "/api/v1/governance/decisions",
        json={
            **body(),
            "supersedes_id": original["id"],
            "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        },
        headers=requester,
    ).json()["data"]
    gate = Barrier(2)

    def attempt(row, action):
        gate.wait(timeout=10)
        return review(row, action).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        revoke = pool.submit(attempt, original, "revoke")
        approve = pool.submit(attempt, extension, "approve")
        assert sorted([revoke.result(timeout=20), approve.result(timeout=20)]) == [200, 400]
