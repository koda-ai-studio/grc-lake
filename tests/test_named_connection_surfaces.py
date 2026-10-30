"""CLI and MCP select a named account without changing the default connection."""

import asyncio
import json

from security_lakehouse import cli, mcp_server
from security_lakehouse.connections import connection_context
from security_lakehouse.connector_state import append_config_event
from test_mcp_server import call_tool, call_tool_payload


def test_cli_creates_and_lists_connections(tmp_path, capsys):
    assert (
        cli.main(
            [
                "connections",
                "create",
                "--lake",
                str(tmp_path),
                "--connection-id",
                "prod",
                "--connector-id",
                "aws-posture",
                "--source-account-id",
                "account-a",
                "--name",
                "Production",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert cli.main(["connections", "list", "--lake", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["connections"][0]["connection_id"] == "prod"


def test_mcp_named_connection_sync_and_history(tmp_path, monkeypatch):
    from security_lakehouse import connector_runner
    from test_named_connections import event

    server = mcp_server.build_server(tmp_path)
    asyncio.run(
        server.call_tool(
            "create_connection",
            {
                "connection_id": "prod",
                "connector_id": "aws-posture",
                "source_account_id": "account-a",
                "name": "Production",
            },
        )
    )
    child, _ = connection_context(tmp_path, "prod")
    append_config_event(child, connector_id="aws-posture", state="enabled", actor="test")
    monkeypatch.setattr(connector_runner, "_collect", lambda *a, **kw: [event("account-a")])
    result = call_tool_payload(
        server, "sync_connector", connector_id="aws-posture", connection_id="prod", materialize=False
    )
    assert result["connection_id"] == "prod"
    assert call_tool(server, "list_connections")[0]["connection_id"] == "prod"
    assert (
        call_tool(server, "list_connector_runs", connector_id="aws-posture", connection_id="prod")[0]["kind"] == "sync"
    )


def test_hosted_connections_keep_tenant_identity_and_secret_boundary(tmp_path):
    from fastapi.testclient import TestClient

    from security_lakehouse.db.base import session_scope
    from security_lakehouse.db.repository import create_api_key, create_tenant, create_user
    from security_lakehouse.server_app import create_app

    app = create_app(tmp_path)
    tokens = []
    with session_scope(app.state.sessionmaker) as session:
        for slug in ["one", "two"]:
            tenant = create_tenant(session, slug=slug, name=slug)
            user = create_user(session, tenant_id=tenant.id, email=f"admin@{slug}.example", role="security_admin")
            _, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
            tokens.append(token)
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {tokens[0]}"}
        response = client.post(
            "/api/v1/connections",
            headers=headers,
            json={
                "connection_id": "prod",
                "connector_id": "jamf-devices",
                "source_account_id": "example",
                "name": "Production",
            },
        )
        assert response.status_code == 201, response.text
        response = client.post(
            "/api/v1/connections/prod/configure",
            headers=headers,
            json={
                "state": "disabled",
                "credentials": {
                    "base_url": "https://example.jamfcloud.com",
                    "client_id": "cid",
                    "client_secret_ref": "DATABASE_URL",
                },
            },
        )
        assert response.status_code == 400
        response = client.get("/api/v1/connections", headers={"Authorization": f"Bearer {tokens[1]}"})
        assert response.status_code == 200
        assert response.json()["data"] == []
        response = client.post(
            "/api/v1/connections/prod/sync", headers={"Authorization": f"Bearer {tokens[1]}"}, json={}
        )
        assert response.status_code == 404
