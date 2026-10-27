"""OAuth refresh-token support for the Google Workspace connector.

A Google OAuth access token expires in ~1 hour, so a long-running or scheduled
sync fails once it expires. These tests pin the refresh contract:

* a request rejected with HTTP 401 triggers exactly one token refresh and a
  single retry, then succeeds;
* a token known to be near/at expiry is refreshed *proactively* before the
  request, so the stale token is never sent;
* a static token with no refresh source still fails closed on 401 (no retry);
* a revoked refresh token (``invalid_grant`` at the token endpoint) fails
  closed rather than looping;
* the token exchange posts the RFC 6749 ``grant_type=refresh_token`` body to
  Google's token endpoint.

The resolved access-token value is held in memory only and never persisted.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

from security_lakehouse import netguard
from security_lakehouse.connectors_google_workspace import (
    GOOGLE_TOKEN_URI,
    GoogleOAuthTokenSource,
    GoogleWorkspaceClient,
)

FIXED_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            result, self._body = self._body, b""
        else:
            result, self._body = self._body[:size], self._body[size:]
        return result

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _json_resp(payload: dict[str, object]) -> _Resp:
    import json

    return _Resp(json.dumps(payload).encode("utf-8"))


def _http_error(code: int) -> urllib.error.HTTPError:
    import email.message

    return urllib.error.HTTPError("https://example", code, "err", email.message.Message(), None)


class _FakeGoogle:
    """Fake netguard opener serving Google's token + directory endpoints."""

    def __init__(
        self,
        *,
        valid_token: str | None,
        mint: str = "fresh-token",
        expires_in: int = 3600,
        revoked: bool = False,
    ) -> None:
        self.valid_token = valid_token
        self.mint = mint
        self.expires_in = expires_in
        self.revoked = revoked
        self.refresh_calls = 0
        self.directory_calls = 0
        self.directory_tokens: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float | None = None, **_kw: object) -> _Resp:
        url = request.full_url
        if url.startswith(GOOGLE_TOKEN_URI):
            self.refresh_calls += 1
            if self.revoked:
                raise _http_error(400)  # invalid_grant on a revoked/expired refresh token
            self.valid_token = self.mint
            return _json_resp({"access_token": self.mint, "expires_in": self.expires_in, "token_type": "Bearer"})
        # Directory API: accept only the currently valid bearer, else 401.
        self.directory_calls += 1
        auth = request.get_header("Authorization") or ""
        token = auth.split(" ", 1)[-1]
        self.directory_tokens.append(token)
        if self.valid_token is not None and token == self.valid_token:
            return _json_resp({"users": [{"id": "u1"}]})
        raise _http_error(401)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", lambda _s: None)


def test_401_triggers_exactly_one_refresh_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeGoogle(valid_token=None, mint="fresh")  # directory rejects the stale token
    monkeypatch.setattr(netguard, "open_public", fake)
    source = GoogleOAuthTokenSource(
        refresh_token="rt",
        client_id="cid",
        client_secret="sec",
        access_token="stale",  # no expiry known -> used as-is until rejected
    )
    client = GoogleWorkspaceClient("C00acme", token_source=source)

    assert client.users() == [{"id": "u1"}]
    assert fake.refresh_calls == 1  # exactly one refresh
    assert fake.directory_calls == 2  # 401, then one retry with the fresh token
    assert fake.directory_tokens == ["stale", "fresh"]


def test_expired_token_is_refreshed_proactively(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeGoogle(valid_token=None, mint="fresh")
    monkeypatch.setattr(netguard, "open_public", fake)
    source = GoogleOAuthTokenSource(
        refresh_token="rt",
        client_id="cid",
        client_secret="sec",
        access_token="stale",
        expires_at=FIXED_NOW - timedelta(seconds=1),  # already expired
        clock=lambda: FIXED_NOW,
    )
    client = GoogleWorkspaceClient("C00acme", token_source=source)

    assert client.users() == [{"id": "u1"}]
    assert fake.refresh_calls == 1  # refreshed before issuing the request
    assert fake.directory_calls == 1  # no 401 round-trip needed
    assert fake.directory_tokens == ["fresh"]  # stale token was never sent


def test_token_refreshed_within_skew_window(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeGoogle(valid_token="stale", mint="fresh")
    monkeypatch.setattr(netguard, "open_public", fake)
    # Token still technically valid but inside the refresh skew window.
    source = GoogleOAuthTokenSource(
        refresh_token="rt",
        client_id="cid",
        client_secret="sec",
        access_token="stale",
        expires_at=FIXED_NOW + timedelta(seconds=30),
        skew_seconds=300,
        clock=lambda: FIXED_NOW,
    )
    client = GoogleWorkspaceClient("C00acme", token_source=source)

    assert client.users() == [{"id": "u1"}]
    assert fake.refresh_calls == 1
    assert fake.directory_tokens == ["fresh"]


def test_static_token_fails_closed_on_401_without_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeGoogle(valid_token="other")  # directory rejects the static token
    monkeypatch.setattr(netguard, "open_public", fake)
    client = GoogleWorkspaceClient("C00acme", access_token="static")

    with pytest.raises(urllib.error.HTTPError) as exc:
        client.users()
    assert exc.value.code == 401
    assert fake.refresh_calls == 0
    assert fake.directory_calls == 1  # no retry without a refresh source


def test_revoked_refresh_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeGoogle(valid_token=None, mint="fresh", revoked=True)
    monkeypatch.setattr(netguard, "open_public", fake)
    source = GoogleOAuthTokenSource(
        refresh_token="rt",
        client_id="cid",
        client_secret="sec",
        access_token="stale",
    )
    client = GoogleWorkspaceClient("C00acme", token_source=source)

    with pytest.raises(urllib.error.HTTPError) as exc:
        client.users()
    assert exc.value.code == 400  # invalid_grant surfaced, not retried into a loop
    assert fake.refresh_calls == 1
    assert fake.directory_calls == 1


def test_token_exchange_posts_refresh_grant(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def _open(request: urllib.request.Request, timeout: float | None = None, **_kw: object) -> _Resp:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = (request.data or b"").decode("ascii")
        return _json_resp({"access_token": "fresh", "expires_in": 3600})

    monkeypatch.setattr(netguard, "open_public", _open)
    source = GoogleOAuthTokenSource(refresh_token="rt", client_id="cid", client_secret="sec")

    assert source.bearer() == "fresh"
    assert captured["url"] == GOOGLE_TOKEN_URI
    assert captured["method"] == "POST"
    params = dict(urllib.parse.parse_qsl(captured["data"]))
    assert params == {
        "grant_type": "refresh_token",
        "refresh_token": "rt",
        "client_id": "cid",
        "client_secret": "sec",
    }


def test_refresh_without_access_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _open(request: urllib.request.Request, timeout: float | None = None, **_kw: object) -> _Resp:
        return _json_resp({"expires_in": 3600})  # no access_token in the response

    monkeypatch.setattr(netguard, "open_public", _open)
    source = GoogleOAuthTokenSource(refresh_token="rt", client_id="cid", client_secret="sec")

    with pytest.raises(ValueError, match="no access_token"):
        source.bearer()


def test_token_source_requires_all_refresh_material() -> None:
    with pytest.raises(ValueError, match="refresh_token"):
        GoogleOAuthTokenSource(refresh_token="", client_id="cid", client_secret="sec")


def test_client_requires_a_token_or_source() -> None:
    with pytest.raises(ValueError, match="access_token or a token_source"):
        GoogleWorkspaceClient("C00acme")
