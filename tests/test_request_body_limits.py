"""Mutation bodies are bounded before handlers run, regardless of media type."""

from __future__ import annotations

import asyncio
import json

import pytest

from security_lakehouse.auth import json_body


def _exchange(chunks, *, method="POST", media_type=b"text/plain", path="/mutation", headers=()):
    sent, consumed, handled = [], [], []
    messages = iter(chunks)

    async def receive():
        message = next(messages)
        consumed.append(message)
        return message

    async def send(message):
        sent.append(message)

    async def endpoint(scope, receive, send):
        handled.append(None)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        handled[-1] = bytes(body)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": bytes(body)})

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(b"content-type", media_type), *headers],
    }
    asyncio.run(json_body.StrictJSONMiddleware(endpoint)(scope, receive, send))
    return sent, consumed, handled


def _chunk(body, more=False):
    return {"type": "http.request", "body": body, "more_body": more}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize(
    "media_type",
    [
        b"text/plain",
        b"application/x-www-form-urlencoded",
        b"multipart/form-data; boundary=x",
        b"application/octet-stream",
    ],
)
def test_non_json_stream_is_rejected_before_handler_or_remaining_chunks(monkeypatch, method, media_type):
    monkeypatch.setattr(json_body, "MAX_BODY_BYTES", 8)
    sent, consumed, handled = _exchange(
        [_chunk(b"1234", True), _chunk(b"56789", True), _chunk(b"unread")],
        method=method,
        media_type=media_type,
        headers=[(b"content-length", b"1")],
    )
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["errors"][0]["code"] == "payload_too_large"
    assert len(consumed) == 2
    assert handled == []


@pytest.mark.parametrize("path", ["/api/v1/auth/saml/acs", "/api/v1/auth/saml/acs/"])
def test_saml_chunked_form_has_smaller_ceiling(path):
    chunk = b"x" * (64 * 1024)
    sent, consumed, handled = _exchange(
        [_chunk(chunk, True) for _ in range(4)] + [_chunk(b"x", True), _chunk(b"unread")],
        path=path,
        media_type=b"application/x-www-form-urlencoded",
        headers=[(b"transfer-encoding", b"chunked")],
    )
    assert sent[0]["status"] == 413
    assert len(consumed) == 5
    assert handled == []


@pytest.mark.parametrize("media_type", [b"text/plain", b"application/x-www-form-urlencoded"])
def test_non_json_at_limit_replays_exact_bytes(monkeypatch, media_type):
    monkeypatch.setattr(json_body, "MAX_BODY_BYTES", 8)
    sent, _, handled = _exchange([_chunk(b"a=1&", True), _chunk(b"b=2 ")], media_type=media_type)
    assert sent[0]["status"] == 200
    assert handled == [b"a=1&b=2 "]
    assert sent[1]["body"] == handled[0]


def test_saml_form_at_limit_is_preserved():
    body = b"x" * (256 * 1024)
    sent, _, handled = _exchange([_chunk(body)], path="/api/v1/auth/saml/acs")
    assert sent[0]["status"] == 200
    assert handled == [body]


@pytest.mark.parametrize("media_type", [b"", b"application/json", b"application/problem+json"])
def test_json_validation_still_precedes_handler(media_type):
    sent, _, handled = _exchange([_chunk(b'{"x":1,"x":2}')], media_type=media_type)
    assert sent[0]["status"] == 400
    assert handled == []


def test_disconnected_non_json_stream_never_invokes_handler():
    sent, _, handled = _exchange([_chunk(b"a=1", True), {"type": "http.disconnect"}])
    assert sent == []
    assert handled == []
