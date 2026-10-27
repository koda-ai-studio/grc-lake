"""Bound provider response bytes before decoding them."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_RUN_RESPONSE_BYTES = 128 * 1024 * 1024


@dataclass
class _Budget:
    remaining: int
    exhausted: bool = False


_budget: ContextVar[_Budget | None] = ContextVar("http_response_budget", default=None)


@contextmanager
def response_budget(*, max_bytes: int | None = None) -> Iterator[None]:
    ceiling = MAX_RUN_RESPONSE_BYTES if max_bytes is None else max_bytes
    if type(ceiling) is not int or ceiling < 1:
        raise ValueError("run response byte limit must be a positive integer")
    token = _budget.set(_Budget(ceiling))
    try:
        yield
    finally:
        _budget.reset(token)


class ResponseLimitError(CollectionGapError):
    """A provider read exceeded its byte budget; it is not empty evidence."""

    def __init__(self, *, aggregate: bool = False) -> None:
        super().__init__(
            "provider run response byte limit exceeded" if aggregate else "provider response byte limit exceeded",
            collection="http_response",
            reason="run_response_byte_limit" if aggregate else "response_byte_limit",
        )


def read_bytes(response: Any, *, limit: int | None = None) -> bytes:
    ceiling = MAX_RESPONSE_BYTES if limit is None else limit
    if type(ceiling) is not int or ceiling < 1:
        raise ValueError("response byte limit must be a positive integer")
    budget = _budget.get()
    if budget is not None and budget.exhausted:
        raise ResponseLimitError(aggregate=True)
    data = bytearray()
    while True:
        size = min(64 * 1024, ceiling - len(data) + 1)
        if budget is not None:
            size = min(size, budget.remaining + 1)
        chunk = response.read(size)
        if not chunk:
            return bytes(data)
        if budget is not None:
            budget.remaining -= len(chunk)
            if budget.remaining < 0:
                budget.exhausted = True
                raise ResponseLimitError(aggregate=True)
        if len(chunk) > ceiling - len(data):
            raise ResponseLimitError()
        data.extend(chunk)


def read_json_response(response: Any, *, limit: int | None = None) -> Any:
    return json.loads(read_bytes(response, limit=limit).decode("utf-8"))


__all__ = ["ResponseLimitError", "read_bytes", "read_json_response", "response_budget"]
