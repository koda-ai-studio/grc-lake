"""Per-control framework (CCF requirement) results read from the published assessment.

Control posture (``gold/control_posture.jsonl``) is a control test: rules over
events tagged with the control. The framework result comes only from
``gold/ccf_assessment.json``, through reviewed safeguard mappings. Views that
show a control's posture use these fields to show the framework result next to
it, so a control with only proposed mappings never reads as an attested pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from security_lakehouse.ccf_queries import read_summary
from security_lakehouse.generations import pinned_path
from security_lakehouse.io import read_json
from security_lakehouse.jsontypes import JsonObject

__all__ = ["ccf_result_fields", "load_requirement_results", "requirement_results_from", "with_ccf_results"]

RequirementResults = dict[str, JsonObject]


def load_requirement_results(lake: str | Path) -> RequirementResults:
    """Return ``control_id -> ccf fields`` from the lake's published CCF assessment."""
    lake = Path(lake)
    summary: dict[str, Any] | None = read_summary(lake)
    if summary is None:
        path = lake / "gold" / "ccf_assessment.json"
        summary = read_json(path, base_dir=lake) if pinned_path(path).is_file() else {}
    return requirement_results_from(summary)


def requirement_results_from(assessment: Mapping[str, Any]) -> RequirementResults:
    """Return ``control_id -> ccf fields`` from an already-read CCF assessment."""
    return {
        str(row["control_id"]): {
            "ccf_status": str(row.get("status") or "not_evaluated"),
            "reviewed_safeguard_count": len(row.get("reviewed_safeguard_ids") or []),
            "proposed_safeguard_count": int(row.get("pending_mapping_count") or 0),
        }
        for row in assessment.get("requirements") or []
    }


def ccf_result_fields(results: RequirementResults, control_id: str) -> JsonObject:
    """CCF fields for one control; a control absent from the assessment is ``not_evaluated``."""
    found = results.get(control_id)
    if found is None:
        return {"ccf_status": "not_evaluated", "reviewed_safeguard_count": 0, "proposed_safeguard_count": 0}
    return dict(found)


def with_ccf_results(rows: list[JsonObject], results: RequirementResults) -> list[JsonObject]:
    """Copy rows keyed by ``control_id`` with their CCF result fields added."""
    return [{**row, **ccf_result_fields(results, str(row.get("control_id") or ""))} for row in rows]
