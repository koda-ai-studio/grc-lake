"""Durable results scoped to the owning lake, published with distributed state.

A receipt is discoverable only through the committed catalog in distributed mode.
No receipt means unknown, never proof that an interrupted operation had no effects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from security_lakehouse.io import canonical_sha256, read_json, write_json

SCHEMA = "grc.operation_result.v1"
MAX_RESULT_BYTES = 16 * 1024**2


def result_path(lake: Path, operation_id: str) -> Path:
    identifier = str(UUID(operation_id))
    if identifier != operation_id:
        raise ValueError("invalid operation identifier")
    return lake / "operations" / "results" / f"{identifier}.json"


def persist_result(lake: Path, operation_id: str, tenant_id: str, code: int, response: dict[str, Any]) -> None:
    response.setdefault("meta", {})["result_url"] = f"/api/v1/operations/{operation_id}/result"
    if len(json.dumps(response, allow_nan=False).encode()) > MAX_RESULT_BYTES:
        response = {
            "data": None,
            "meta": {
                "result_truncated": True,
                "outcome": response.get("meta", {}).get("outcome"),
                "result_url": response["meta"]["result_url"],
                "recovery": "inspect_domain_history",
            },
            "errors": [{"code": "result_limit", "detail": "result exceeded retained response limit"}],
        }
    content = {
        "schema_version": SCHEMA,
        "operation_id": operation_id,
        "tenant_id": tenant_id,
        "http_status": code,
        "response": response,
    }
    record = {**content, "sha256": canonical_sha256(content)}
    path = result_path(lake, operation_id)
    if path.exists():
        previous = read_result(lake, operation_id, tenant_id)
        if previous != record:
            raise ValueError("operation result already exists")
        return
    write_json(path, record, base_dir=lake)


def read_result(lake: Path, operation_id: str, tenant_id: str) -> dict[str, Any] | None:
    path = result_path(lake, operation_id)
    if not path.exists():
        return None
    from security_lakehouse.io import resolve_path

    path = resolve_path(path, base_dir=lake)
    if path.stat().st_size > MAX_RESULT_BYTES * 2:
        raise ValueError("operation result exceeds read limit")
    record = read_json(path, base_dir=lake)
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != SCHEMA
        or record.get("tenant_id") != tenant_id
        or record.get("operation_id") != operation_id
        or set(record) != {"schema_version", "operation_id", "tenant_id", "http_status", "response", "sha256"}
        or canonical_sha256({k: v for k, v in record.items() if k != "sha256"}) != record["sha256"]
    ):
        raise ValueError("operation result failed integrity verification")
    return record


def failure_response(operation_id: str, exc: Exception) -> tuple[int, dict[str, Any]]:
    """Classify an uncertain execution without leaking exception text or replaying it."""
    from sqlalchemy.exc import SQLAlchemyError

    from security_lakehouse.distributed.catalog import Conflict
    from security_lakehouse.distributed.objects import IntegrityError
    from security_lakehouse.distributed.recovery import failure_code

    code = failure_code(exc)
    if isinstance(exc, Conflict):
        code, status = "writer_conflict", 409
    elif isinstance(exc, IntegrityError):
        status = 409
    elif isinstance(exc, (OSError, SQLAlchemyError)) or code == "missing_object":
        status = 503
    else:
        code, status = "operation_failed", 500
    return status, {
        "data": None,
        "errors": [
            {"code": code, "detail": "operation failed; inspect result receipt or domain history before retrying"}
        ],
        "meta": {
            "publication": "unknown",
            "recovery": "inspect_receipt_or_history",
            "result_url": f"/api/v1/operations/{operation_id}/result",
        },
    }
