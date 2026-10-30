"""Tenant-local immutable connection registry and account identity boundary."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from security_lakehouse.connectors import load_connector_catalog
from security_lakehouse.io import read_json, resolve_path, write_json
from security_lakehouse.ledger import chain_lock
from security_lakehouse.timeutil import utc_now_iso_z

__all__ = ["connection_context", "create_connection", "connection_records", "bind_connection_account"]


def bind_connection_account(connector_id: str, rows: list[dict[str, Any]], account: str) -> list[dict[str, Any]]:
    from security_lakehouse.connector_errors import ConnectorConfigError

    bound = []
    for row in rows:
        observed = row.get("tenant_id")
        if observed == "customer-managed" and connector_id in {"aws-posture", "azure-posture", "gcp-posture"}:
            observed = (row.get("entity") or {}).get("org")
        if observed != account:
            raise ConnectorConfigError("Collected source account does not match this connection")
        bound.append({**row, "tenant_id": account})
    return bound


def _root(lake: str | Path) -> Path:
    root = resolve_path(lake) / "connections"
    if root.is_symlink() or resolve_path(root, base_dir=lake) != root:
        raise ValueError("connection storage must remain inside its tenant lake")
    return root


def connection_context(lake: str | Path, connection_id: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(connection_id, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", connection_id) is None:
        raise ValueError("connection_id must contain 1-64 letters, numbers, underscores or hyphens")
    root = _root(lake)
    child = resolve_path(root / connection_id, base_dir=root)
    if child != root / connection_id:
        raise ValueError("connection storage must remain inside its tenant lake")
    info = read_json(child / "connection.json", base_dir=child)
    if info.get("connection_id") != connection_id or info.get("connector_id") not in load_connector_catalog():
        raise ValueError("invalid stored connection")
    return child, info


def connection_records(lake: str | Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    root = _root(lake)
    if root.exists():
        for path in sorted(root.iterdir()):
            if path.name.startswith("."):
                continue
            if path.is_dir() or path.is_symlink():
                yield connection_context(lake, path.name)


def create_connection(
    lake: str | Path,
    *,
    connection_id: str,
    connector_id: str,
    source_account_id: str,
    name: str,
) -> dict[str, Any]:
    if not isinstance(connection_id, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", connection_id) is None:
        raise ValueError("invalid connection_id")
    if connector_id not in load_connector_catalog():
        raise ValueError("unknown connector_id")
    if not isinstance(source_account_id, str) or not source_account_id.strip() or len(source_account_id) > 256:
        raise ValueError("a source account identifier is required")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("a connection name of at most 120 characters is required")
    root = _root(lake)
    root.mkdir(parents=True, exist_ok=True)
    with chain_lock(root / ".registry"):
        child = resolve_path(root / connection_id, base_dir=root)
        if child != root / connection_id or child.exists():
            raise ValueError("connection already exists; its source account binding is immutable")
        if any(
            info["connector_id"] == connector_id and info["source_account_id"] == source_account_id
            for _, info in connection_records(lake)
        ):
            raise ValueError("this source account already has a connection for that connector")
        info = {
            "connection_id": connection_id,
            "connector_id": connector_id,
            "source_account_id": source_account_id,
            "name": name.strip(),
            "created_at": utc_now_iso_z(),
        }
        child.mkdir(mode=0o700)
        write_json(child / "connection.json", info, base_dir=child)
    return info
