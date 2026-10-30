"""Tenant-local named connections with independent collector state and snapshots."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from security_lakehouse.connector_state import build_catalog_view, load_connector_catalog
from security_lakehouse.io import read_json, read_jsonl, write_json, write_jsonl
from security_lakehouse.ledger import chain_lock
from security_lakehouse.timeutil import utc_now_iso_z

__all__ = [
    "connection_context",
    "bind_connection_account",
    "create_connection",
    "evaluate_connections",
    "list_connections",
    "connection_input",
    "sync_connection",
    "tick_connections",
]


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
    root = Path(lake).resolve() / "connections"
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("connection storage must remain inside its tenant lake")
    return root


def connection_context(lake: str | Path, connection_id: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(connection_id, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", connection_id) is None:
        raise ValueError("connection_id must contain 1-64 letters, numbers, underscores or hyphens")
    child = _root(lake) / connection_id
    if child.is_symlink() or child.resolve() != child:
        raise ValueError("connection storage must remain inside its tenant lake")
    info = read_json(child / "connection.json", base_dir=child)
    if info.get("connection_id") != connection_id or info.get("connector_id") not in load_connector_catalog():
        raise ValueError("invalid stored connection")
    return child, info


def _records(lake: str | Path) -> Iterator[tuple[Path, dict[str, Any]]]:
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
        child = root / connection_id
        if child.exists() or child.is_symlink():
            raise ValueError("connection already exists; its source account binding is immutable")
        if any(
            info["connector_id"] == connector_id and info["source_account_id"] == source_account_id
            for _, info in _records(lake)
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


def list_connections(lake: str | Path) -> list[dict[str, Any]]:
    result = []
    for child, info in _records(lake):
        connector = next(row for row in build_catalog_view(child) if row["connector_id"] == info["connector_id"])
        result.append({**info, "connector": connector})
    return result


def sync_connection(
    lake: str | Path,
    connection_id: str,
    *,
    materialize: bool = True,
    actor: str = "system",
    repo: str | None = None,
    fixture_dir: str | Path | None = None,
    token_env: str = "__provider_default__",
) -> dict[str, Any]:
    from security_lakehouse.connector_runner import run_connector_sync

    child, info = connection_context(lake, connection_id)
    result = run_connector_sync(
        child,
        connector_id=info["connector_id"],
        actor=actor,
        materialize=False,
        repo=repo,
        fixture_dir=fixture_dir,
        token_env=token_env,
        connection_id=connection_id,
        expected_source_account_id=info["source_account_id"],
    )
    evaluation = evaluate_connections(lake, actor=actor) if materialize else None
    return {
        "connection_id": connection_id,
        "connector_id": info["connector_id"],
        "result": evaluation.result if evaluation else result.result,
        "evidence_count": result.evidence_count,
        "run": result.run,
        "materialized": bool(evaluation and evaluation.result == "ok"),
        "evaluation": evaluation.to_dict() if evaluation else None,
    }


def evaluate_connections(lake: str | Path, *, actor: str = "system"):
    from security_lakehouse.lake_eval import run_lake_eval

    return run_lake_eval(lake, actor=actor)


@contextmanager
def connection_input(lake: str | Path, legacy_raw: Path) -> Iterator[Path]:
    """Copy each independently committed intake into one stable evaluation input."""
    from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE

    records = list(_records(lake))
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


def tick_connections(lake: str | Path, moment) -> list[dict[str, Any]]:
    """Attempt each due named connection once; parent scheduling owns evaluation."""
    from security_lakehouse.connector_runner import ConnectorSyncError
    from security_lakehouse.connector_state import latest_config
    from security_lakehouse.ingestion.watermark import collection_scope
    from security_lakehouse.lake_scale import connector_materialize_on_sync
    from security_lakehouse.schedule_expr import parse_schedule
    from security_lakehouse.scheduler import _read_state, _state_key, _write_state

    results = []
    for child, info in _records(lake):
        config = latest_config(child, info["connector_id"])
        if not config or config.get("state") != "enabled":
            continue
        options = config.get("options") or {}
        period = parse_schedule(str(options.get("sync_schedule") or ""))
        if period is None:
            continue
        scope = collection_scope(
            config,
            repo=options.get("repo"),
            fixture_dir=options.get("fixture_dir"),
            token_env=str(options.get("token_env") or "__provider_default__"),
        )
        target = f"{info['connection_id']}:{info['connector_id']}:{scope}"
        with chain_lock(child / "gold" / ".named-scheduler"):
            prior = _read_state(child).get(_state_key("connector", target))
            if prior is not None and moment < prior + period:
                continue
            _write_state(child, target_kind="connector", target_id=target, fired_at=moment, result="started")
            try:
                row = sync_connection(
                    lake, info["connection_id"], actor="scheduler", materialize=connector_materialize_on_sync(options)
                )
            except ConnectorSyncError:
                row = {
                    "connection_id": info["connection_id"],
                    "result": "error",
                    "error": "collection failed; inspect connection history",
                }
            results.append({"target_kind": "connection", **row})
            _write_state(child, target_kind="connector", target_id=target, fired_at=moment, result=row["result"])
    return results
