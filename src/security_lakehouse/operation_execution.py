"""Execute persisted operations without constructing the HTTP application.

HTTP and spawned workers share this service. Each child opens and disposes its
own database engine; schema migration remains a server startup responsibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from security_lakehouse import api_contract, tenancy
from security_lakehouse.auth.authority import AuthorityError, CredentialReference, resolve_authority
from security_lakehouse.auth.server_mode import assert_insecure_allowed, insecure_requested
from security_lakehouse.db import repository
from security_lakehouse.db.base import create_engine_for, session_factory
from security_lakehouse.db.models import OperationJob
from security_lakehouse.execution_mode import server_execution
from security_lakehouse.services.assessments import GenerationConflict
from security_lakehouse.services.snapshot_events import snapshot_written_hook


def execute_operation(
    root: Path, row: OperationJob, *, factory: sessionmaker, require_auth: bool
) -> tuple[int, dict[str, Any]]:
    try:
        return _execute_operation(root, row, factory=factory, require_auth=require_auth)
    except GenerationConflict as exc:
        return 409, api_contract.error_envelope("generation_conflict", str(exc))


def _execute_operation(
    root: Path, row: OperationJob, *, factory: sessionmaker, require_auth: bool
) -> tuple[int, dict[str, Any]]:
    from security_lakehouse.distributed.config import ClusterConfig
    from security_lakehouse.distributed.context import binding

    cluster = ClusterConfig.from_env()
    if cluster is not None and binding.get() is None:
        from security_lakehouse.distributed.catalog import Catalog
        from security_lakehouse.distributed.objects import ObjectStore
        from security_lakehouse.distributed.workspace import Runtime

        runtime = Runtime(Catalog(factory.kw["bind"], cluster), ObjectStore(cluster), root / "distributed-scratch")

        class RejectedOperation(Exception):
            pass

        try:
            with runtime.write(row.tenant_id, wait_seconds=95):
                result = execute_operation(root, row, factory=factory, require_auth=require_auth)
                if result[0] >= 400:
                    raise RejectedOperation()
            return result
        except RejectedOperation:
            outcome = result[1].get("meta", {}).get("outcome")
            if outcome is not None:
                outcome.update(
                    publication="not_committed", generation_id=None, manifest_sha256=None, recovery="inspect_inputs"
                )
            result[1].get("meta", {}).pop("result_url", None)
            return result
    with factory() as session:
        try:
            identity = resolve_authority(
                session,
                CredentialReference(row.user_id, row.tenant_id, row.auth_method, row.api_key_id, row.session_id),
                allow_insecure=not require_auth,
            )
        except AuthorityError:
            return 403, api_contract.error_envelope("forbidden", "operation authority is no longer active")
        if identity.tenant_id != row.tenant_id or not identity.has_scope(api_contract.required_post_scope(row.path)):
            return 403, api_contract.error_envelope("forbidden", "operation authority is no longer active")
        tenant_ids = repository.list_tenant_ids(session) if require_auth else []
        bound = tenancy.resolve_bound_tenant(root, require_auth=require_auth, tenant_ids=tenant_ids)
        lake = tenancy.tenant_lake(root, identity.tenant_id, bound_tenant=bound)
        with server_execution(identity.tenant_id):
            from security_lakehouse.operation_receipts import persist_result
            from security_lakehouse.services.assessments import (
                AssessmentContext,
                EvaluationCommand,
                SnapshotCommand,
                evaluate,
                snapshot,
            )

            body = json.loads(row.payload_json)
            context = AssessmentContext(
                tenant_id=identity.tenant_id,
                actor=identity.email or identity.user_id,
                authority_reference=row.api_key_id or row.session_id,
                operation_id=row.id,
                expected_generation=body.get("expected_generation"),
            )
            if row.path == "/api/v1/ingestion/eval":
                assessment_result = evaluate(lake, EvaluationCommand(), context)
                code = 201 if assessment_result.succeeded else 500
                payload = api_contract.envelope(
                    "ingestion.eval", assessment_result.data, meta={"outcome": assessment_result.outcome}
                )
            elif row.path == "/api/v1/snapshots":
                assessment_result = snapshot(
                    lake,
                    SnapshotCommand(reason=str(body.get("reason") or "api_request")),
                    context,
                    on_snapshot_written=snapshot_written_hook(session, identity.tenant_id),
                )
                code = 201
                payload = api_contract.envelope(
                    "snapshots", assessment_result.data, meta={"outcome": assessment_result.outcome}
                )
            else:
                from security_lakehouse import api_v1

                code, payload = api_v1.handle_post(
                    row.path, body, lake, on_snapshot_written=snapshot_written_hook(session, identity.tenant_id)
                )
            persist_result(lake, row.id, row.tenant_id, int(code), payload)
        session.commit()
        return int(code), payload


def execute_stored_operation(root: Path, row: OperationJob, *, require_auth: bool) -> tuple[int, dict[str, Any]]:
    """Rebuild database access and current authority in an isolated child."""
    assert_insecure_allowed(require_auth=require_auth)
    require_auth = require_auth and not insecure_requested()
    engine = create_engine_for(root)
    try:
        try:
            return execute_operation(root, row, factory=session_factory(engine), require_auth=require_auth)
        except GenerationConflict as exc:
            return 409, api_contract.error_envelope("generation_conflict", str(exc))
    finally:
        engine.dispose()
