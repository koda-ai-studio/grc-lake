"""Explain frozen requirement blockers without inventing evidence or decisions."""

from __future__ import annotations

from typing import Any


def requirement_gaps(assessment: dict[str, Any]) -> list[dict[str, Any]]:
    """Project catalog-sized summary data; never load per-asset evidence arrays.

    Only facts retained in the assessment can explain a gap. Missing historical
    details are explicit, and the stored verdict remains unchanged.
    """
    safeguards = {row["safeguard_id"]: row for row in assessment["safeguards"]}
    rows = []
    for requirement in assessment["requirements"]:
        reviewed = requirement["reviewed_safeguard_ids"]
        pending = requirement["pending_mapping_count"]
        contextual = requirement["contextual_mappings"]
        codes: set[str] = set()
        blockers = []
        if not assessment["review_log_verified"]:
            codes.add("review_log_unverified")
        if pending:
            codes.add("mapping_review_pending")
        if not reviewed:
            codes.add("no_reviewed_implementation")
            if contextual and not pending:
                codes.add("context_only")
        for safeguard_id in reviewed:
            safeguard = safeguards.get(safeguard_id)
            if safeguard is None:
                codes.add("assessment_detail_missing")
                continue
            status = safeguard["status"]
            unassessed = safeguard["unassessed_asset_count"]
            invalid = safeguard["invalid_binding_count"]
            if status != "pass" or unassessed or invalid:
                blockers.append(
                    {
                        "safeguard_id": safeguard_id,
                        "status": status,
                        "unassessed_asset_count": unassessed,
                        "invalid_binding_count": invalid,
                    }
                )
                codes.add(
                    {
                        "fail": "safeguard_failed",
                        "stale": "safeguard_stale",
                        "not_evaluated": "safeguard_not_evaluated",
                    }.get(status, "assessment_detail_missing")
                )
            if unassessed:
                codes.add("unassessed_assets")
            if invalid:
                codes.add("invalid_evidence_bindings")
        if requirement["status"] == "stale":
            codes.add("requirement_stale")
        if not codes and requirement["status"] != "pass":
            codes.add("assessment_detail_missing")
        rows.append(
            {
                "control_id": requirement["control_id"],
                "framework_id": requirement["framework_id"],
                "status": requirement["status"],
                "gap_codes": sorted(codes),
                "has_gaps": bool(codes),
                "reviewed_safeguard_count": len(reviewed),
                "pending_mapping_count": pending,
                "contextual_mapping_count": len(contextual),
                "blocking_safeguards": sorted(blockers, key=lambda row: row["safeguard_id"]),
                "population_completeness": assessment["population_completeness"],
            }
        )
    return sorted(rows, key=lambda row: (row["framework_id"], row["control_id"]))
