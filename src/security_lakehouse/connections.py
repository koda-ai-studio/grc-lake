"""Operations on independent tenant-local account connections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from security_lakehouse.connection_registry import connection_context, create_connection
from security_lakehouse.connector_state import build_catalog_view

__all__ = ["connection_context", "create_connection", "list_connections", "sync_connection", "evaluate_connections"]


def list_connections(lake: str | Path) -> list[dict[str, Any]]:
    return [
        {
            "connection_id": row["connection_id"],
            "connector_id": row["connector_id"],
            "source_account_id": row["source_account_id"],
            "name": row["name"],
            "connector": row,
        }
        for row in build_catalog_view(lake)
        if row.get("connection_id")
    ]


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
