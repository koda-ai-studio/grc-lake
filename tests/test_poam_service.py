"""POA&M service layer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")

from fastapi.testclient import TestClient

from security_lakehouse.db.base import session_scope
from security_lakehouse.db.repository import create_tenant
from security_lakehouse.server_app import create_app
from security_lakehouse.services import poam as poam_services
from test_api_v1 import _seed_lake
from test_risks import _bearer, _provision


def _app(tmp_path: Path):
    _seed_lake(tmp_path)
    return create_app(tmp_path)


def test_poam_item_round_trip(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with session_scope(app.state.sessionmaker) as session:
        tenant = create_tenant(session, slug="acme", name="Acme")
        created = poam_services.create_poam_item(
            session,
            tenant.id,
            requirement_id="3.1.1",
            control_id="CMMC-3.1.1",
            title="Limit system access",
            weakness="Failing control test",
            sprs_points=5,
            created_by="alice@example.com",
        )
        assert created["status"] == "open"
        assert created["sprs_points"] == 5

        listed = poam_services.list_poam_items(session, tenant.id)
        assert len(listed) == 1
        assert listed[0]["requirement_id"] == "3.1.1"

        updated = poam_services.update_poam_item(
            session,
            tenant.id,
            created["id"],
            changes={"status": "in_progress", "owner": "bob"},
        )
        assert updated["status"] == "in_progress"
        assert updated["owner"] == "bob"


def test_sync_poam_from_posture_is_idempotent_without_failures(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with session_scope(app.state.sessionmaker) as session:
        tenant = create_tenant(session, slug="acme", name="Acme")
        first = poam_services.sync_poam_from_posture(session, tenant.id, tmp_path, created_by="ops")
        second = poam_services.sync_poam_from_posture(session, tenant.id, tmp_path, created_by="ops")
        assert "sprs" in first
        assert first["created"] == second["created"] == 0


def test_poam_http_preserves_actor_fields_and_service_errors(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _tenant_id, token = _provision(app, "poam")
    headers = _bearer(token)
    client = TestClient(app)
    path = "/api/v1/gov-compliance/poam"
    payload = {
        "requirement_id": "3.1.1",
        "control_id": "CMMC-3.1.1",
        "title": "Limit access",
        "milestone": "Review administrators",
        "sprs_points": 5,
        "poam_eligible": False,
        "due_at": "2026-11-01T12:00:00",
    }
    assert client.post(path, json={**payload, "created_by": "someone-else"}, headers=headers).status_code == 422
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 201
    created = response.json()["data"]
    assert all(created[key] == value for key, value in payload.items())
    assert created["created_by"] == "contributor@poam.test"
    invalid = client.patch(f"{path}/{created['id']}", json={"status": "bogus"}, headers=headers)
    assert invalid.status_code == 400
    assert invalid.json()["errors"][0]["code"] == "bad_request"
    missing = client.patch(f"{path}/missing", json={"status": "in_progress"}, headers=headers)
    assert missing.status_code == 404
    assert missing.json()["errors"] == [{"code": "not_found", "detail": "POA&M item not found"}]
    assert len(client.get(path, headers=headers).json()["data"]) == 1
