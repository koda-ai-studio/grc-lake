"""Bound provider response bytes before decoding them."""

from __future__ import annotations

import json
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ResponseLimitError(CollectionGapError):
    """A provider read exceeded its byte budget; it is not empty evidence."""

    def __init__(self) -> None:
        super().__init__(
            "provider response byte limit exceeded",
            collection="http_response",
            reason="response_byte_limit",
        )


def read_bytes(response: Any, *, limit: int | None = None) -> bytes:
    ceiling = MAX_RESPONSE_BYTES if limit is None else limit
    if type(ceiling) is not int or ceiling < 1:
        raise ValueError("response byte limit must be a positive integer")
    data = bytearray()
    while True:
        chunk = response.read(min(64 * 1024, ceiling - len(data) + 1))
        if not chunk:
            return bytes(data)
        if len(chunk) > ceiling - len(data):
            raise ResponseLimitError()
        data.extend(chunk)


def read_json_response(response: Any, *, limit: int | None = None) -> Any:
    return json.loads(read_bytes(response, limit=limit).decode("utf-8"))


__all__ = ["ResponseLimitError", "read_bytes", "read_json_response"]
