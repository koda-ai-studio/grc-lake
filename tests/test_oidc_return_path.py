"""Return navigation is bounded to the console and bound to each OIDC flow."""

from secrets import token_urlsafe
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from security_lakehouse import server_app
from security_lakehouse.auth.oidc import OIDCConfig
from security_lakehouse.db import repository
from security_lakehouse.db.base import session_scope


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = OIDCConfig(
        issuer="https://idp.example.test", client_id="synthetic", client_secret="synthetic", tenant_slug="example"
    )

    class Provider:
        async def authorize_redirect(self, request, redirect_uri, **kwargs):
            state = kwargs.get("state", token_urlsafe(32))
            request.session["synthetic:" + state] = True
            return RedirectResponse("https://idp.example.test/login?state=" + state)

        async def authorize_access_token(self, request):
            state = request.query_params.get("state", "")
            if not request.session.pop("synthetic:" + state, False):
                raise ValueError("invalid state")
            return {"userinfo": {"email": "admin@example.com", "email_verified": True}}

    monkeypatch.setenv("GRC_LAKE_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("GRC_LAKE_COOKIE_SIGNING_KEY", "c" * 48)
    monkeypatch.setattr(server_app, "load_oidc_config", lambda: config)
    monkeypatch.setattr(server_app, "build_oauth", lambda _: SimpleNamespace(oidc=Provider()))
    app = server_app.create_app(tmp_path)
    with session_scope(app.state.sessionmaker) as session:
        tenant = repository.create_tenant(session, slug="example", name="Example")
        repository.create_user(session, tenant_id=tenant.id, email="admin@example.com", role="admin")
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as result:
        yield result


def start(client, target):
    response = client.get("/api/v1/auth/login", params={"return_to": target})
    assert response.status_code in {302, 307}
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def test_oidc_returns_to_graph_after_successful_login(client):
    target = "/console/graph/?root=safeguard%3ASG-IDENTITY-001#details"
    state = start(client, target)
    response = client.get("/api/v1/auth/callback", params={"state": state})
    assert response.status_code == 302
    assert response.headers["location"] == target
    assert client.get("/api/v1/auth/whoami").json()["data"]["email"] == "admin@example.com"
    assert client.get("/api/v1/auth/callback", params={"state": state}).status_code == 401


def test_two_oidc_flows_keep_their_own_return_paths(client):
    first = start(client, "/console/graph/?root=control%3Aone")
    second = start(client, "/console/evidence/?id=two")
    assert first != second
    for state, target in [(second, "/console/evidence/?id=two"), (first, "/console/graph/?root=control%3Aone")]:
        response = client.get("/api/v1/auth/callback", params={"state": state})
        assert response.headers["location"] == target


@pytest.mark.parametrize(
    "target",
    [
        "https://example.com",
        "//example.com",
        "/console-elsewhere/",
        "/console/../api/",
        "/console/%2e%2e/api/",
        "/console/%252e%252e/api/",
        "/console/\\example.com",
        "/console/%0d%0aLocation:evil",
        "/console/login/",
        "/console/" + "x" * 2100,
    ],
)
def test_invalid_return_targets_fall_back_to_console(client, target):
    state = start(client, target)
    response = client.get("/api/v1/auth/callback", params={"state": state})
    assert response.status_code == 302
    assert response.headers["location"] == "/console"


def test_callback_query_cannot_override_signed_return_target(client):
    state = start(client, "/console/evidence/?id=one")
    response = client.get("/api/v1/auth/callback", params={"state": state, "return_to": "https://example.com"})
    assert response.headers["location"] == "/console/evidence/?id=one"


def test_unknown_state_does_not_redirect_or_authenticate(client):
    start(client, "/console/graph/")
    response = client.get("/api/v1/auth/callback", params={"state": "not-issued", "return_to": "/console/graph/"})
    assert response.status_code == 401
    assert "location" not in response.headers
    assert client.get("/api/v1/auth/whoami").status_code == 401


def test_evicted_destination_falls_back_without_reusing_another_flow(client):
    first = start(client, "/console/evidence/?id=first")
    for index in range(8):
        start(client, f"/console/graph/?root={index}")
    response = client.get("/api/v1/auth/callback", params={"state": first})
    assert response.status_code == 302
    assert response.headers["location"] == "/console"


def test_real_oauth_client_preserves_state_and_nonce(client, monkeypatch):
    from security_lakehouse.auth.oidc import build_oauth

    oauth = build_oauth(client.app.state.oidc_config)

    async def metadata():
        return {
            "issuer": "https://idp.example.test",
            "authorization_endpoint": "https://idp.example.test/authorize",
            "token_endpoint": "https://idp.example.test/token",
        }

    monkeypatch.setattr(oauth.oidc, "load_server_metadata", metadata)
    client.app.state.oauth = oauth
    response = client.get("/api/v1/auth/login", params={"return_to": "/console/graph/"})
    assert response.status_code == 302
    params = parse_qs(urlsplit(response.headers["location"]).query)
    assert len(params["state"][0]) >= 32
    assert params["nonce"][0]
    assert params["redirect_uri"] == ["https://testserver/api/v1/auth/callback"]
    assert "return_to" not in params
