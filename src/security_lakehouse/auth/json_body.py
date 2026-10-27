"""Bound mutation bodies and validate JSON before route handlers see them."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from security_lakehouse import api_contract as api_v1
from security_lakehouse.strict_json import InvalidJSON, loads

MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_SAML_BODY_BYTES = 256 * 1024


class StrictJSONMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            await self.app(scope, receive, send)
            return
        media_type = dict(scope["headers"]).get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        is_json = not media_type or media_type == b"application/json" or media_type.endswith(b"+json")
        limit = MAX_BODY_BYTES
        if scope.get("path", "").rstrip("/") == "/api/v1/auth/saml/acs":
            limit = min(limit, MAX_SAML_BODY_BYTES)
        raw = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(chunk) > limit - len(raw):
                response = JSONResponse(
                    api_v1.error_envelope("payload_too_large", "request body too large"), status_code=413
                )
                await response(scope, receive, send)
                return
            raw.extend(chunk)
            if not message.get("more_body", False):
                break
        if is_json and raw.strip():
            try:
                loads(bytes(raw))
            except InvalidJSON:
                response = JSONResponse(api_v1.error_envelope("bad_request", "invalid JSON body"), status_code=400)
                await response(scope, receive, send)
                return
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(raw), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
