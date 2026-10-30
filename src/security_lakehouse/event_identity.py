"""Versioned identities for account-local provider event IDs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["event_identity", "source_event_key"]


def source_event_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("connector_id") or ""),
        str(row.get("tenant_id") or ""),
        str(row.get("event_id") or ""),
    )


def event_identity(row: dict[str, Any], *, version: int = 2) -> str:
    """Namespace connector events; retain v1 for historical evidence verification."""
    if version not in {1, 2}:
        raise ValueError("unsupported connector event identity version")
    connector, account, source_id = source_event_key(row)
    if not connector:
        return source_id
    key = [connector, source_id] if version == 1 else [connector, account, source_id]
    encoded = json.dumps(key, separators=(",", ":")).encode("utf-8")
    return f"trustops:connector-event:v{version}:" + hashlib.sha256(encoded).hexdigest()
