"""First-admin setup is atomic and never repeats credential issuance."""

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_lakehouse import cli
from security_lakehouse.db import repository
from security_lakehouse.db.base import create_engine_for, session_factory, session_scope


def _args(lake: Path) -> list[str]:
    return [
        "auth",
        "bootstrap",
        "--lake",
        str(lake),
        "--slug",
        "example",
        "--name",
        "Example",
        "--email",
        "admin@example.com",
    ]


def test_bootstrap_delivers_expiring_admin_credential_and_refuses_retry(tmp_path, capsys):
    assert cli.main(_args(tmp_path)) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    path = Path(result["token_file"])
    token = path.read_text().strip()
    assert token not in output
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 6 < (datetime.fromisoformat(result["expires_at"]) - datetime.now(UTC)).total_seconds() / 86400 <= 7
    with session_scope(session_factory(create_engine_for(tmp_path))) as session:
        resolved = repository.resolve_api_key(session, token)
        assert resolved is not None
        tenant = repository.get_tenant_by_slug(session, slug="example")
        user = repository.get_user_by_email(session, tenant_id=tenant.id, email="admin@example.com")
        assert user.role == "admin"
    assert cli.main(_args(tmp_path)) == 1
    assert "already exists" in capsys.readouterr().err
    assert list(path.parent.glob("*.token")) == [path]
    assert path.read_text().strip() == token


def test_bootstrap_does_not_adopt_or_elevate_existing_tenant(tmp_path, capsys):
    assert cli.main(["auth", "create-tenant", "--lake", str(tmp_path), "--slug", "example", "--name", "Existing"]) == 0
    assert cli.main(_args(tmp_path)) == 1
    assert "already exists" in capsys.readouterr().err
    with session_scope(session_factory(create_engine_for(tmp_path))) as session:
        tenant = repository.get_tenant_by_slug(session, slug="example")
        assert tenant.name == "Existing"
        assert repository.get_user_by_email(session, tenant_id=tenant.id, email="admin@example.com") is None
    assert not list(tmp_path.glob("server/credentials/*.token"))


def test_bootstrap_key_signs_in_to_authenticated_server(tmp_path, capsys, monkeypatch):
    from fastapi.testclient import TestClient

    from security_lakehouse.server_app import create_app

    monkeypatch.setenv("GRC_LAKE_COOKIE_SIGNING_KEY", "x" * 48)
    assert cli.main(_args(tmp_path)) == 0
    metadata = json.loads(capsys.readouterr().out)
    token = Path(metadata["token_file"]).read_text().strip()
    with TestClient(create_app(tmp_path), base_url="https://testserver") as client:
        assert client.get("/api/v1/auth/whoami").status_code == 401
        assert client.post("/api/v1/auth/session-from-key", json={"api_key": token}).status_code == 200
        response = client.get("/api/v1/auth/whoami")
        assert response.status_code == 200
        assert "admin@example.com" in response.text
        assert "example" in response.text


def test_bootstrap_rolls_back_when_credential_delivery_fails(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("synthetic delivery failure")

    monkeypatch.setattr(cli, "_store_new_api_key", fail)
    assert cli.main(_args(tmp_path)) == 1
    with session_scope(session_factory(create_engine_for(tmp_path))) as session:
        assert repository.get_tenant_by_slug(session, slug="example") is None
    assert not list(tmp_path.glob("server/credentials/*.token"))


@pytest.mark.parametrize("days", ["0", "-1"])
def test_bootstrap_rejects_nonpositive_expiry_before_creating_state(tmp_path, days):
    assert cli.main([*_args(tmp_path), "--expires-days", days]) == 1
    assert not (tmp_path / "server").exists()
