"""The artifact probe must fail on auth/isolation regressions, not just HTTP errors."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def probe():
    path = Path(__file__).resolve().parents[1] / "tools/authenticated_smoke.py"
    spec = importlib.util.spec_from_file_location("authenticated_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unexpected_success_on_protected_route_fails(monkeypatch):
    module = probe()
    monkeypatch.setattr(module, "request", lambda *a, **kw: (200, {}, {}))
    with pytest.raises(AssertionError, match="expected 401"):
        module.expect("http://localhost", "GET", "/api/v1/controls", 401)


def test_other_tenant_marker_fails_even_when_own_marker_exists():
    module = probe()
    with pytest.raises(AssertionError, match="cross-tenant"):
        module.assert_isolated({"data": ["probe-alpha", "probe-beta"]}, "probe-alpha", "probe-beta")


def test_empty_evidence_cannot_pass_isolation():
    module = probe()
    with pytest.raises(AssertionError, match="own tenant"):
        module.assert_isolated({"data": []}, "probe-alpha", "probe-beta")


def test_failed_startup_cleans_secrets_and_disposable_volume(tmp_path, monkeypatch):
    module = probe()
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if "up" in args:
            raise RuntimeError("startup failed")
        return "diagnostic"

    monkeypatch.setattr(module, "run", run)
    output = tmp_path / "receipt"
    with pytest.raises(RuntimeError, match="startup failed"):
        module.qualify("grc-lake:ci", output)
    assert any(c[-2:] == ("down", "--volumes") for c in calls)
    assert not (output / "grc-lake.env").exists()
    assert '"ok": false' in (output / "result.json").read_text()


def test_empty_seed_cannot_pass_authenticated_probe(monkeypatch):
    module = probe()
    monkeypatch.setattr(module, "request", lambda *a, **kw: (401, {}, {}))
    with pytest.raises(AssertionError, match="two distinct tenants"):
        module.exercise("http://localhost", [])


def test_cleanup_failure_preserves_primary_failure(tmp_path, monkeypatch):
    module = probe()

    def run(*args, **kwargs):
        if "up" in args:
            raise RuntimeError("startup failed")
        if "down" in args or "logs" in args:
            raise RuntimeError("daemon unavailable")
        return "diagnostic"

    monkeypatch.setattr(module, "run", run)
    output = tmp_path / "receipt"
    with pytest.raises(RuntimeError, match="startup failed"):
        module.qualify("grc-lake:ci", output)
    import json

    result = json.loads((output / "result.json").read_text())
    assert result["cleanup"] == "failed; remove this project when Docker is available"
    assert result["ok"] is False
    assert not (output / "grc-lake.env").exists()


def test_cleanup_cannot_target_either_operator_volume(tmp_path, monkeypatch):
    module = probe()

    def run(*args, **kwargs):
        if "up" in args:
            raise RuntimeError("stop before startup")
        return "diagnostic"

    monkeypatch.setattr(module, "run", run)
    output = tmp_path / "receipt"
    with pytest.raises(RuntimeError, match="stop before startup"):
        module.qualify("grc-lake:ci", output)
    import yaml

    overrides = yaml.safe_load((output / "override.yaml").read_text().replace("!override", ""))
    project = (output / "project-name.txt").read_text().strip()
    assert overrides["volumes"]["grc-lake-lake"]["name"] == project + "-server"
    assert overrides["volumes"]["grc-lake-demo-lake"]["name"] == project + "-demo"


def test_bootstrap_uses_operator_command_and_private_file(monkeypatch):
    module = probe()
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if "bootstrap" in args:
            return '{"token_file":"/lake/server/credentials/synthetic.token"}'
        return "synthetic-token"

    monkeypatch.setattr(module, "run", run)
    assert module.bootstrap(["docker", "compose"]) == "synthetic-token"
    assert "bootstrap" in calls[0]
    assert "--email" in calls[0] and "admin@example.com" in calls[0]
    assert calls[1][-1] == "/lake/server/credentials/synthetic.token"


def test_bootstrap_session_rejects_anonymous_success(monkeypatch):
    module = probe()
    monkeypatch.setattr(module, "request", lambda *a, **kw: (200, {}, {}))
    with pytest.raises(AssertionError, match="expected 401"):
        module.bootstrap_session("http://localhost", "synthetic-token")


@pytest.mark.parametrize("cookie", ["", "session=synthetic; HttpOnly; SameSite=Lax"])
def test_bootstrap_session_requires_secure_cookie(cookie, monkeypatch):
    module = probe()

    def request(base, method, path, **kwargs):
        if path.endswith("whoami"):
            return 401, {}, {}
        if path.endswith("login/"):
            return 200, b"<html>", {}
        return 200, {}, {"Set-Cookie": cookie}

    monkeypatch.setattr(module, "request", request)
    with pytest.raises(AssertionError, match="cookie"):
        module.bootstrap_session("http://localhost", "synthetic-token")


def test_bootstrap_session_verifies_identity_using_cookie(monkeypatch):
    module = probe()
    calls = []
    identity = {
        "email": "admin@example.com",
        "role": "admin",
        "auth_method": "session:api_key",
        "tenant_id": "synthetic",
    }

    def request(base, method, path, **kwargs):
        calls.append((path, kwargs))
        if path.endswith("login/"):
            return 200, b"<html>", {}
        if path.endswith("session-from-key"):
            assert kwargs["body"] == {"api_key": "synthetic-token"}
            return 200, {}, {"Set-Cookie": "session=synthetic; Secure; HttpOnly; SameSite=Lax"}
        if kwargs.get("headers") == {"Cookie": "session=synthetic"}:
            return 200, {"data": identity}, {}
        return 401, {}, {}

    monkeypatch.setattr(module, "request", request)
    assert module.bootstrap_session("http://localhost", "synthetic-token") == ("session=synthetic", identity)
    assert calls[-1][1] == {"headers": {"Cookie": "session=synthetic"}}


@pytest.mark.parametrize(
    "field,value", [("email", "other@example.com"), ("role", "read_only"), ("auth_method", "api_key")]
)
def test_bootstrap_session_rejects_wrong_identity(field, value, monkeypatch):
    module = probe()
    identity = {"email": "admin@example.com", "role": "admin", "auth_method": "session:api_key"}
    identity[field] = value
    monkeypatch.setattr(module, "request", lambda *a, **kw: (200, {"data": identity}, {}))
    with pytest.raises(AssertionError):
        module.session_identity("http://localhost", "session=synthetic")


def test_bootstrap_failure_cannot_pass_or_skip_cleanup(tmp_path, monkeypatch):
    import json

    module = probe()
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if "port" in args:
            return "127.0.0.1:1234"
        if "inspect" in args:
            return '[{"Config":{"Image":"grc-lake:ci"},"Image":"synthetic-image"}]'
        if "-c" in args:
            return '{"uid":1000,"machine":"aarch64","version":"synthetic"}'
        if "bootstrap" in args:
            raise RuntimeError("bootstrap failed")
        return "synthetic"

    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module, "wait_ready", lambda *a, **kw: None)
    monkeypatch.setattr(module, "request", lambda *a, **kw: (200, b"<html>", {}))
    output = tmp_path / "receipt"
    with pytest.raises(RuntimeError, match="bootstrap failed"):
        module.qualify("grc-lake:ci", output)
    assert any(c[-2:] == ("down", "--volumes") for c in calls)
    assert not (output / "grc-lake.env").exists()
    assert json.loads((output / "result.json").read_text())["ok"] is False
