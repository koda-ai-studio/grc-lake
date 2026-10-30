"""Versioned organization selections and immutable account-scoped assessments."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from security_lakehouse.connection_inputs import connection_snapshot
from security_lakehouse.connections import connection_context, sync_connection
from security_lakehouse.connector_paths import CONNECTOR_RAW_FILE
from security_lakehouse.connector_runner import ConnectorSyncError
from security_lakehouse.io import canonical_sha256, read_json, read_jsonl, resolve_path, write_json, write_jsonl
from security_lakehouse.ledger import chain_lock
from security_lakehouse.timeutil import utc_now_iso_z

__all__ = [
    "verify_organization_evaluation",
    "save_organization",
    "list_organizations",
    "organization_path",
    "organization_scope",
    "ingest_organization",
    "evaluate_organization",
    "organization_runs",
]


def organization_path(lake: str | Path, organization_id: str) -> Path:
    if not isinstance(organization_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", organization_id) is None:
        raise ValueError("invalid organization_id")
    root = resolve_path(lake) / "organizations"
    if root.is_symlink():
        raise ValueError("organization storage must remain inside its tenant lake")
    path = resolve_path(root / organization_id, base_dir=root)
    if path != root / organization_id:
        raise ValueError("organization storage must remain inside its tenant lake")
    return path


def organization_scope(lake: str | Path, organization_id: str, expected_revision: int | None = None) -> dict[str, Any]:
    path = organization_path(lake, organization_id)
    rows = read_jsonl(path / "scopes.jsonl", base_dir=path)
    if not rows:
        raise FileNotFoundError("organization not found")
    if expected_revision is not None and (
        type(expected_revision) is not int or rows[-1]["revision"] != expected_revision
    ):
        raise ValueError("scope changed; reload before running")
    return rows[-1]


def save_organization(
    lake: str | Path,
    *,
    organization_id: str,
    name: str,
    connection_ids: list[str],
    expected_revision: int = 0,
    actor: str = "system",
) -> dict[str, Any]:
    path = organization_path(lake, organization_id)
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("organization name is required")
    if (
        not isinstance(connection_ids, list)
        or not connection_ids
        or any(not isinstance(item, str) for item in connection_ids)
        or len(set(connection_ids)) != len(connection_ids)
    ):
        raise ValueError("select distinct existing connections")
    for item in connection_ids:
        connection_context(lake, item)
    path.mkdir(parents=True, exist_ok=True)
    with chain_lock(path / "scope"):
        history = read_jsonl(path / "scopes.jsonl", missing_ok=True, base_dir=path)
        revision = history[-1]["revision"] if history else 0
        if type(expected_revision) is not int or expected_revision != revision:
            raise ValueError("scope changed; reload before saving")
        scope = {
            "organization_id": organization_id,
            "name": name.strip(),
            "connection_ids": sorted(connection_ids),
            "revision": revision + 1,
            "actor": actor,
            "occurred_at": utc_now_iso_z(),
        }
        write_jsonl(path / "scopes.jsonl", [*history, scope], base_dir=path)
    return scope


def organization_runs(lake: str | Path, organization_id: str) -> list[dict[str, Any]]:
    path = organization_path(lake, organization_id)
    organization_scope(lake, organization_id)
    return list(reversed(read_jsonl(path / "runs.jsonl", missing_ok=True, base_dir=path)))


def list_organizations(lake: str | Path) -> list[dict[str, Any]]:
    root = organization_path(lake, "validation").parent
    if not root.exists():
        return []
    return [organization_scope(lake, path.name) for path in sorted(root.iterdir()) if path.is_dir()]


def _record(lake: str | Path, organization_id: str, row: dict[str, Any]) -> dict[str, Any]:
    path = organization_path(lake, organization_id)
    with chain_lock(path / "runs"):
        rows = read_jsonl(path / "runs.jsonl", missing_ok=True, base_dir=path)
        write_jsonl(path / "runs.jsonl", [*rows, row], base_dir=path)
    return row


def ingest_organization(
    lake: str | Path, organization_id: str, *, actor: str = "system", expected_revision: int | None = None
) -> dict[str, Any]:
    scope = organization_scope(lake, organization_id, expected_revision)
    results = []
    for connection_id in scope["connection_ids"]:
        try:
            row = sync_connection(lake, connection_id, materialize=False, actor=actor)
            _, receipt = connection_snapshot(lake, connection_id)
            results.append(
                {
                    "connection_id": connection_id,
                    "result": row["result"],
                    "available": receipt["available"],
                    "run_id": receipt["run_id"],
                }
            )
        except (ConnectorSyncError, ValueError, FileNotFoundError):
            results.append(
                {
                    "connection_id": connection_id,
                    "result": "error",
                    "available": False,
                    "error": "collection failed; inspect this connection's history",
                }
            )
    return _record(
        lake,
        organization_id,
        {
            "kind": "ingest",
            "run_id": str(uuid4()),
            "scope": scope,
            "result": "ok" if all(r["available"] for r in results) else "partial",
            "connections": results,
            "actor": actor,
            "occurred_at": utc_now_iso_z(),
        },
    )


def evaluate_organization(
    lake: str | Path, organization_id: str, *, actor: str = "system", expected_revision: int | None = None
) -> dict[str, Any]:
    from security_lakehouse.lake_eval import run_lake_eval

    scope = organization_scope(lake, organization_id, expected_revision)
    rows, receipts = [], []
    for connection_id in scope["connection_ids"]:
        evidence, receipt = connection_snapshot(lake, connection_id)
        rows.extend(evidence)
        receipts.append(receipt)
    evaluation_id = str(uuid4())
    path = organization_path(lake, organization_id)
    run = path / "evaluations" / evaluation_id
    if run.parent.is_symlink() or resolve_path(run, base_dir=path) != run:
        raise ValueError("evaluation storage must remain inside its tenant lake")
    manifest = {"scope": scope, "inputs": receipts, "captured_at": utc_now_iso_z()}
    digest = canonical_sha256(manifest)
    rows = [
        {
            **row,
            "attributes": {
                **row.get("attributes", {}),
                "organization_id": organization_id,
                "organization_scope_digest": digest,
            },
        }
        for row in rows
    ]
    write_json(run / "scope.json", manifest, base_dir=run)
    write_jsonl(run / CONNECTOR_RAW_FILE, rows, base_dir=run)
    result = run_lake_eval(run, actor=actor, env={})
    unavailable = [r["connection_id"] for r in receipts if not r["available"]]
    return _record(
        lake,
        organization_id,
        {
            "kind": "evaluate",
            "evaluation_id": evaluation_id,
            "scope": scope,
            "scope_digest": digest,
            "result": result.result,
            "coverage": "partial" if unavailable else "complete",
            "unavailable_connections": unavailable,
            "evaluation": result.to_dict(),
            "actor": actor,
            "occurred_at": utc_now_iso_z(),
        },
    )


def verify_organization_evaluation(lake: str | Path, organization_id: str, evaluation_id: str) -> Path:
    from security_lakehouse.verification import verify_lake_integrity

    organization_scope(lake, organization_id)
    path = organization_path(lake, organization_id)
    selected = path / "evaluations" / str(UUID(evaluation_id))
    run = resolve_path(selected, base_dir=path)
    if run != selected:
        raise ValueError("evaluation storage must remain inside its tenant lake")
    receipt = read_json(run / "scope.json", base_dir=run)
    digest = canonical_sha256(receipt)
    if not verify_lake_integrity(run)["ok"]:
        raise ValueError("assessment evidence failed verification")
    rows = read_jsonl(run / "bronze/raw_events.jsonl", base_dir=run)
    if not rows or any(row["raw"].get("attributes", {}).get("organization_scope_digest") != digest for row in rows):
        raise ValueError("assessment scope receipt failed verification")
    return run
