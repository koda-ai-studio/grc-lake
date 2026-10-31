"""Operator preparation of derived graph indexes before serving large inventories."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

from security_lakehouse.generations import generation_reader

__all__ = ["register", "prepare_index"]


@generation_reader
def prepare_index(lake: Path, *, tenant: str | None = None, vendors=None, timeout: float = 1800) -> dict:
    from security_lakehouse.investigation_graph import _MODEL_FILES, _build_model, _graph_version, _model_key
    from security_lakehouse.investigation_persistence import read

    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("graph preparation timeout must be positive and finite")
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= timeout:
            raise ValueError("graph index preparation timed out")

    if _model_key(lake, vendors, check, tenant) is None:
        raise ValueError("graph preparation requires a frozen assessment generation")
    result = read(
        lake,
        vendors,
        tenant,
        check,
        model_files=_MODEL_FILES,
        build_model=_build_model,
        graph_version=_graph_version,
        root=None,
        view="environment",
        depth=1,
        limit=1,
        layers=None,
        search="",
        root_offset=0,
        framework="",
        control_offset=0,
        expected_version=None,
    )
    return {
        "version": result["version"],
        "counts": result["counts"],
        "platform_tenant_id": tenant,
        "index_bytes": (lake / ".graph-index/index.sqlite").stat().st_size,
        "seconds": time.monotonic() - started,
    }


def _prepare(args: argparse.Namespace) -> int:
    from security_lakehouse.execution_mode import application_database_configured
    from security_lakehouse.runtime_environment import runtime_env

    lake = Path(args.lake).resolve()
    nested = lake.parent.name == "tenants"
    tenant = args.tenant or (lake.name if nested else None)
    if nested and tenant != lake.name:
        raise ValueError("graph tenant conflicts with the lake scope")
    root = lake.parent.parent if nested else lake
    vendors = []
    if application_database_configured(root) or runtime_env().get("GRC_LAKE_DATABASE_URL"):
        if tenant is None:
            raise ValueError("server graph preparation requires --tenant")
        from security_lakehouse.db.base import create_engine_for, session_factory
        from security_lakehouse.db.migrate import require_head
        from security_lakehouse.services.vendor_risk import list_assessments

        require_head(root)
        engine = create_engine_for(root)
        try:
            with session_factory(engine)() as session:
                vendors = list_assessments(session, tenant)
        finally:
            engine.dispose()
    print(json.dumps(prepare_index(lake, tenant=tenant, vendors=vendors, timeout=args.timeout_seconds)))
    return 0


def register(sub) -> None:
    graph = sub.add_parser("graph", help="prepare navigation for large recorded inventories")
    commands = graph.add_subparsers(dest="graph_command", required=True)
    prepare = commands.add_parser("prepare-index", help="build or verify the scoped persistent graph index")
    prepare.add_argument("--lake", required=True, help="existing lake directory")
    prepare.add_argument("--tenant", help="platform tenant ID; inferred for a server tenants/<id> lake")
    prepare.add_argument("--timeout-seconds", type=float, default=1800, help="preparation deadline (default: 1800)")
    prepare.set_defaults(func=_prepare)
