"""Compose independently published connection inputs for assessment."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from security_lakehouse.connection_registry import connection_records
from security_lakehouse.connector_state import build_catalog_view
from security_lakehouse.io import read_jsonl, write_jsonl
from security_lakehouse.ledger import chain_lock

__all__ = ["connection_input"]


@contextmanager
def connection_input(lake: str | Path, legacy_raw: Path) -> Iterator[Path]:
    """Copy each independently committed intake into one stable evaluation input."""
    from security_lakehouse.connector_paths import CONNECTOR_RAW_FILE

    records = list(connection_records(lake))
    if not records:
        yield legacy_raw
        return
    owned = {(info["connector_id"], info["source_account_id"]) for _, info in records}
    rows = []
    for row in read_jsonl(legacy_raw, missing_ok=True):
        account = row.get("tenant_id")
        if account == "customer-managed" and row.get("connector_id") in {"aws-posture", "azure-posture", "gcp-posture"}:
            account = (row.get("entity") or {}).get("org")
        if (row.get("connector_id"), account) not in owned:
            rows.append(row)
    for child, info in records:
        raw = child / CONNECTOR_RAW_FILE
        from security_lakehouse.connector_state import CONFIG_FILE

        with chain_lock(child / "gold" / CONFIG_FILE):
            account_rows = read_jsonl(raw, missing_ok=True, base_dir=child)
            view = next(row for row in build_catalog_view(child) if row["connector_id"] == info["connector_id"])
        rows.extend(account_rows)
        run = view.get("last_sync") or {}
        if not account_rows or run.get("result") != "ok" or not view.get("last_successful_sync"):
            at = run.get("occurred_at") or info["created_at"]
            rows.append(
                {
                    "connector_id": info["connector_id"],
                    "event_id": f"connection-gap-{info['connection_id']}",
                    "tenant_id": info["source_account_id"],
                    "source": account_rows[0]["source"] if account_rows else info["connector_id"].split("-")[0],
                    "event_time": at,
                    "event_type": "connection.collection_gap",
                    "entity": {"id": info["connection_id"], "type": "collection_scope"},
                    "status": "not_evaluated",
                    "controls": [],
                    "evidence": {"ref": f"connection:{info['connection_id']}", "collected_at": at},
                    "attributes": {
                        "connection_id": info["connection_id"],
                        "collection_gap": True,
                        "reason": "collection_unavailable",
                    },
                }
            )
    with tempfile.TemporaryDirectory(prefix="grc-connection-input-") as directory:
        path = Path(directory) / "events.jsonl"
        write_jsonl(path, rows)
        yield path
