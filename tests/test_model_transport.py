"""Optional models use guarded transport without leaking credentials or buffering unlimited replies."""

import io
import urllib.request

import pytest

from security_lakehouse import netguard
from security_lakehouse.agents import model_client


@pytest.mark.parametrize("header", ["x-api-key", "private-token", "X-ClickHouse-Key", "X-ClickHouse-User"])
def test_cross_origin_redirect_strips_provider_api_key(header):
    request = urllib.request.Request("https://model.example/start", data=b"{}", headers={header: "synthetic-key"})
    redirected = netguard._GuardedRedirectHandler(lambda url: None).redirect_request(
        request, None, 302, "Found", {}, "https://other.example/result"
    )
    assert redirected.get_header(header.capitalize()) is None


def test_model_posts_through_public_guard(monkeypatch):
    calls = []
    response = io.BytesIO(b'{"result":1}')

    def guarded(request, **kwargs):
        calls.append((request, kwargs))
        return response

    def unguarded(*args, **kwargs):
        pytest.fail("model used unguarded urlopen")

    monkeypatch.setattr(netguard, "open_public", guarded)
    monkeypatch.setattr(urllib.request, "urlopen", unguarded)
    assert model_client._post_json(
        "https://model.example/result", {}, headers={"Authorization": "Bearer synthetic-key"}, timeout=3
    ) == {"result": 1}
    assert len(calls) == 1
    assert calls[0][0].get_method() == "POST"
    assert calls[0][1]["timeout"] == 3
    assert response.closed


def test_model_response_has_byte_ceiling(monkeypatch):
    response = io.BytesIO(b'{"data":"' + b"x" * (1024 * 1024) + b'"}')
    monkeypatch.setattr(netguard, "open_public", lambda *a, **k: response)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: response)
    with pytest.raises(model_client.ModelClientError, match="limit"):
        model_client._post_json("https://model.example", {}, headers={}, timeout=3)
    assert response.closed


def test_same_origin_redirect_keeps_provider_credentials():
    request = urllib.request.Request("https://model.example/start", headers={"X-API-KEY": "synthetic"})
    redirected = netguard._GuardedRedirectHandler(lambda url: None).redirect_request(
        request, None, 302, "Found", {}, "https://model.example/result"
    )
    assert redirected.get_header("X-api-key") == "synthetic"


def test_model_dns_rebinding_does_not_connect(monkeypatch):
    from test_netguard import PRIVATE_IP, PUBLIC_IP, _patch_connect, _sequenced_dns

    _sequenced_dns(monkeypatch, {"model.example": [PUBLIC_IP, PRIVATE_IP]})
    connected = _patch_connect(monkeypatch, [])
    with pytest.raises(model_client.ModelClientError):
        model_client._post_json("http://model.example/chat", {}, headers={}, timeout=3)
    assert connected == []


def test_model_redirect_to_private_address_is_rejected(monkeypatch):
    from test_netguard import PRIVATE_IP, PUBLIC_IP, _patch_connect, _sequenced_dns

    _sequenced_dns(monkeypatch, {"model.example": [PUBLIC_IP], "private.example": [PRIVATE_IP]})
    redirect = b"HTTP/1.1 302 Found\r\nLocation: http://private.example/chat\r\nContent-Length: 0\r\n\r\n"
    connected = _patch_connect(monkeypatch, [redirect])
    with pytest.raises(model_client.ModelClientError):
        model_client._post_json("http://model.example/chat", {}, headers={}, timeout=3)
    assert connected == [(PUBLIC_IP, 80)]


def test_redirect_body_is_bounded_and_closed(monkeypatch):
    from security_lakehouse import http_response

    monkeypatch.setattr(http_response, "MAX_RESPONSE_BYTES", 16)
    response = io.BytesIO(b"x" * 17)
    handler = netguard._GuardedRedirectHandler(lambda url: None)
    with pytest.raises(http_response.ResponseLimitError):
        handler.http_error_302(
            urllib.request.Request("https://model.example/start"),
            response,
            302,
            "Found",
            {"location": "https://model.example/end"},
        )
    assert response.closed


def test_explicit_local_ollama_works_without_proxy_or_redirects(monkeypatch):
    from security_lakehouse.agents.providers import ModelProviderConfig

    handlers = []

    class Opener:
        def open(self, request, *, timeout):
            assert request.full_url == "http://127.0.0.1:11434/api/chat"
            return io.BytesIO(b'{"message":{"content":"{}"}}')

    def build(*items):
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    result = model_client.call_model_json(
        {}, ModelProviderConfig(provider="ollama", model="test", base_url="http://127.0.0.1:11434")
    )
    assert result == {}
    assert next(h for h in handlers if isinstance(h, urllib.request.ProxyHandler)).proxies == {}
    redirect = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    with pytest.raises(ValueError, match="redirects"):
        redirect.redirect_request(None, None, 302, "Found", {}, "http://other.example")


@pytest.mark.parametrize("provider", ["openai", "openai_compatible", "anthropic", "vertex"])
def test_cloud_model_provider_dispatch_uses_guard(monkeypatch, provider):
    from security_lakehouse.agents.providers import ModelProviderConfig

    monkeypatch.setenv("GRC_LAKE_TEST_MODEL_KEY", "synthetic-key")
    monkeypatch.setattr(netguard, "assert_url_is_public", lambda *a, **k: None)
    monkeypatch.setattr(model_client, "_vertex_access_token", lambda: "synthetic-access-token")
    replies = {
        "openai": b'{"choices":[{"message":{"content":"{}"}}]}',
        "openai_compatible": b'{"choices":[{"message":{"content":"{}"}}]}',
        "anthropic": b'{"content":[{"text":"{}"}]}',
        "vertex": b'{"candidates":[{"content":{"parts":[{"text":"{}"}]}}]}',
    }
    calls = []

    def guarded(request, **kwargs):
        calls.append(request)
        return io.BytesIO(replies[provider])

    monkeypatch.setattr(netguard, "open_public", guarded)
    result = model_client.call_model_json(
        {},
        ModelProviderConfig(
            provider=provider, model="test", api_key_env="GRC_LAKE_TEST_MODEL_KEY", project="synthetic"
        ),
    )
    assert result == {}
    assert len(calls) == 1


def test_http_error_is_closed_without_exposing_provider_url(monkeypatch):
    import urllib.error

    response = io.BytesIO(b"synthetic-private-error")
    error = urllib.error.HTTPError("https://model.example/?secret=synthetic", 403, "private detail", {}, response)

    def denied(*args, **kwargs):
        raise error

    monkeypatch.setattr(netguard, "open_public", denied)
    with pytest.raises(model_client.ModelClientError, match="HTTP 403") as caught:
        model_client._post_json("https://model.example", {}, headers={}, timeout=3)
    assert "synthetic" not in str(caught.value)
    assert "private" not in str(caught.value)
    assert response.closed
