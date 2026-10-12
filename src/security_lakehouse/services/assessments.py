"""Assessment application boundary. Transport adapters own authentication and envelopes.

A context identifies an already authorized caller; it never grants authority.
Retained generations are read as recorded, never rewritten to the latest schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from security_lakehouse.assessment import SnapshotWrittenHook, write_assessment_snapshot
from security_lakehouse.execution_mode import evaluation_tenant_id
from security_lakehouse.generations import generation_identity, publication_lock
from security_lakehouse.lake_eval import run_lake_eval


class GenerationConflict(ValueError):
    """The caller's expected assessment is no longer current."""


@dataclass(frozen=True)
class AssessmentContext:
    tenant_id: str | None = None
    actor: str = "system"
    authority_reference: str | None = None
    operation_id: str | None = None
    expected_generation: str | None = None


@dataclass(frozen=True)
class EvaluationCommand:
    mapping_path: str | Path | None = None


@dataclass(frozen=True)
class SnapshotCommand:
    reason: str = "api_request"
    output: str | Path | None = None
    freshness_days: int = 7


@dataclass(frozen=True)
class AssessmentResult:
    data: dict[str, Any]
    outcome: dict[str, Any]
    succeeded: bool = True


def _check(lake: Path, context: AssessmentContext) -> str:
    tenant = evaluation_tenant_id(lake, context.tenant_id)
    current = generation_identity(lake)
    if context.expected_generation is not None and (current or {}).get("generation_id") != context.expected_generation:
        raise GenerationConflict("assessment generation changed; reload before submitting work")
    return tenant


def _outcome(
    lake: Path, context: AssessmentContext, *, committed: bool, succeeded: bool, export: str
) -> dict[str, Any]:
    identity = generation_identity(lake) if committed else None
    return {
        "schema_version": "grc.assessment_outcome.v1",
        "operation_id": context.operation_id,
        "execution": "completed" if succeeded else "failed",
        "publication": "committed" if committed else "not_committed",
        "generation_id": (identity or {}).get("generation_id"),
        "manifest_sha256": (identity or {}).get("manifest_sha256"),
        "assessment_verdict": "see_generation" if committed else "not_evaluated",
        "export": export,
        "failure_code": None
        if succeeded
        else "export_failed"
        if committed and export == "error"
        else "assessment_failed",
        "recovery": "inspect_result" if committed else "inspect_inputs",
    }


def evaluate(lake: str | Path, command: EvaluationCommand, context: AssessmentContext) -> AssessmentResult:
    lake = Path(lake)
    with publication_lock(lake):
        tenant = _check(lake, context)
        result = run_lake_eval(lake, mapping_path=command.mapping_path, tenant_id=tenant, actor=context.actor)
        return AssessmentResult(
            result.to_dict(),
            _outcome(
                lake,
                context,
                committed=result.local_result == "ok",
                succeeded=result.result == "ok",
                export=result.export_result,
            ),
            result.result == "ok",
        )


def snapshot(
    lake: str | Path,
    command: SnapshotCommand,
    context: AssessmentContext,
    *,
    on_snapshot_written: SnapshotWrittenHook | None = None,
) -> AssessmentResult:
    lake = Path(lake)
    with publication_lock(lake):
        _check(lake, context)
        path = write_assessment_snapshot(
            lake,
            output=command.output,
            freshness_days=command.freshness_days,
            reason=command.reason,
            on_snapshot_written=on_snapshot_written,
        )
        return AssessmentResult(
            {"snapshot_path": str(path), "reason": command.reason},
            _outcome(lake, context, committed=True, succeeded=True, export="not_configured"),
        )
