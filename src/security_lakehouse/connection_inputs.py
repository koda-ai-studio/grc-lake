"""Compose independently published connection inputs for assessment."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from security_lakehouse.connection_registry import connection_context, connection_records
from security_lakehouse.connector_state import build_catalog_view
from security_lakehouse.io import read_jsonl, write_jsonl
from security_lakehouse.ledger import chain_lock

__all__ = ["connection_input", "connection_snapshot"]


@contextmanager
def connection_input(lake: str | Path, legacy_raw: Path) -> Iterator[Path]:
    """Copy each independently committed intake into one stable evaluation input."""

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
    for _child, info in records:
        account_rows, _ = connection_snapshot(lake, info["connection_id"])
        rows.extend(account_rows)
    with tempfile.TemporaryDirectory(prefix="grc-connection-input-") as directory:
        path = Path(directory) / "events.jsonl"
        write_jsonl(path, rows)
        yield path


def connection_snapshot(lake: str | Path, connection_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Capture input, availability and provenance under the collector's publication lock."""
    from security_lakehouse.connector_paths import CONNECTOR_RAW_FILE
    from security_lakehouse.connector_state import CONFIG_FILE, latest_config
    from security_lakehouse.io import canonical_sha256

    child, info = connection_context(lake, connection_id)
    with chain_lock(child / "gold" / CONFIG_FILE):
        account_rows = read_jsonl(child / CONNECTOR_RAW_FILE, missing_ok=True, base_dir=child)
        view = next(row for row in build_catalog_view(child) if row["connector_id"] == info["connector_id"])
        config = latest_config(child, info["connector_id"], fresh=True)
        run = view.get("last_sync") or {}
        available = bool(
            account_rows
            and run.get("result") == "ok"
            and view.get("last_successful_sync")
            and not (run.get("metadata") or {}).get("partial")
            and view.get("freshness_state") != "stale"
        )
        receipt = {
            **info,
            "raw_sha256": canonical_sha256(account_rows),
            "config_sha256": canonical_sha256(config),
            "run_id": canonical_sha256(run) if run else None,
            "run": run,
            "available": available,
        }
    if not available:
        at = run.get("occurred_at") or info["created_at"]
        account_rows.append(
            {
                "connector_id": info["connector_id"],
                "event_id": f"connection-gap-{connection_id}",
                "tenant_id": info["source_account_id"],
                "source": account_rows[0]["source"] if account_rows else info["connector_id"].split("-")[0],
                "event_time": at,
                "event_type": "connection.collection_gap",
                "entity": {"id": connection_id, "type": "collection_scope"},
                "status": "not_evaluated",
                "controls": [],
                "evidence": {"ref": f"connection:{connection_id}", "collected_at": at},
                "attributes": {
                    "connection_id": connection_id,
                    "collection_gap": True,
                    "reason": "collection_unavailable",
                },
            }
        )
    return account_rows, receipt
