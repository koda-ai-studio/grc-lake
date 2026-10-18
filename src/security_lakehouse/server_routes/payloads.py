"""Shared response shaping and pagination for authenticated server routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status

from security_lakehouse import api_v1
from security_lakehouse.auth.rbac import Identity
from security_lakehouse.data_policy import redact_payload
from security_lakehouse.server_routes.deps import (
    page_meta as _page_meta,
)
from security_lakehouse.server_routes.deps import (
    pagination as _pagination,
)
from security_lakehouse.server_routes.deps import (
    query_params as _params,
)

__all__ = ["_page_meta", "_pagination", "_params"]


def _page_window(params: dict[str, list[str]], *, maximum: int = 1000) -> tuple[int, int]:
    """Read ``limit``/``offset``/``cursor`` with the evidence/controls contract.

    A malformed or out-of-range value is a 400 rather than a silent default.
    ``maximum`` lowers the served page size for database-backed lists; the
    applied value is what ``meta.limit`` reports.
    """
    try:
        _rows, limit, offset = api_v1.paginate_collection([], params)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return min(limit, maximum), offset


def _applied_filters(**values: str | None) -> dict[str, list[str]]:
    return {name: [value] for name, value in values.items() if value}


def _portable_references(payload: object) -> object:
    if isinstance(payload, list):
        return [_portable_references(value) for value in payload]
    if isinstance(payload, dict):
        return {
            key: Path(value).name
            if key.endswith("_path") and isinstance(value, str) and Path(value).is_absolute()
            else _portable_references(value)
            for key, value in payload.items()
        }
    return payload


def _redact_payload(payload: object, identity: Identity) -> object:
    return _portable_references(redact_payload(payload, role=identity.role))
