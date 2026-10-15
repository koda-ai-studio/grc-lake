"""Read-only, version-bound batches for human mapping review."""

from __future__ import annotations

from collections import defaultdict
from math import ceil
from pathlib import Path
from typing import Any

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.io import canonical_sha256
from security_lakehouse.mapping_review import effective_safeguards, list_review_items
from security_lakehouse.safeguards import ATTESTABLE_STATES, coverage_by_framework, load_safeguards


def build_review_packet(
    lake_dir: str | Path | None = None,
    *,
    payload: dict[str, Any] | None = None,
    framework_id: str | None = None,
    batch_size: int = 25,
    target_mapped_pct: int = 80,
    target_reviewed_pct: int = 50,
) -> dict[str, Any]:
    """Group distinct unreviewed requirements; never write or infer a decision.

    Multiple candidate mappings remain visible under one requirement so they
    cannot inflate its potential contribution. Citation presence is not source
    verification, equivalence, applicability, or approval.
    """
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100 requirements")
    if not 1 <= target_mapped_pct <= 100 or not 1 <= target_reviewed_pct <= 100:
        raise ValueError("coverage targets must be percentages between 1 and 100")
    shipped = payload if payload is not None else load_safeguards()
    effective = effective_safeguards(lake_dir, payload=shipped)
    coverage = coverage_by_framework(effective)
    items = list_review_items(lake_dir, payload=shipped)
    reviewed = {
        item["control_id"]
        for item in items
        if item["review_basis_sha256"] and item["contributes_to_coverage"] and item["review_state"] in ATTESTABLE_STATES
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if framework_id and item["framework_id"] != framework_id:
            continue
        if item["control_id"] in reviewed or not item["contributes_to_coverage"]:
            continue
        if item["review_state"] not in {"proposed", "needs_changes"}:
            continue
        grouped[item["control_id"]].append(item)
    catalog = load_control_catalog()
    requirements = []
    for control_id, candidates in grouped.items():
        requirements.append(
            {
                "control_id": control_id,
                "framework_id": candidates[0]["framework_id"],
                "control_title": candidates[0]["control_title"],
                "requirement": catalog.get(control_id),
                "candidates": [
                    {
                        **item,
                        "decision": None,
                        "reviewer": None,
                        "rationale": None,
                        "source_reference_present": bool(item["mapping_source"]),
                        "requires_catalog_repair": item["review_basis_sha256"] is None,
                    }
                    for item in sorted(candidates, key=lambda row: row["safeguard_id"])
                ],
            }
        )
    requirements.sort(key=lambda row: (row["framework_id"], row["control_id"]))
    total = coverage["controls"]
    batches = []
    for offset in range(0, len(requirements), batch_size):
        rows = requirements[offset : offset + batch_size]
        batches.append(
            {
                "batch_id": f"review-{offset // batch_size + 1:03d}",
                "requirements": rows,
                "requirement_count": len(rows),
                "mapping_count": sum(len(row["candidates"]) for row in rows),
                "basis_sha256": canonical_sha256(rows),
            }
        )
    body = {
        "schema": "grc_lake.mapping_review_packet.v1",
        "scope": "organization" if lake_dir is not None else "catalog",
        "framework_filter": framework_id,
        "summary": {
            "catalog_requirements": total,
            "mapped_requirements": coverage["covered"],
            "reviewed_requirements": coverage["reviewed"],
            "mapped_pct": coverage["coverage_pct"],
            "reviewed_pct": coverage["reviewed_pct"],
            "mapped_target": ceil(total * target_mapped_pct / 100),
            "reviewed_target": ceil(total * target_reviewed_pct / 100),
            "additional_mapped_needed": max(0, ceil(total * target_mapped_pct / 100) - coverage["covered"]),
            "additional_reviewed_needed": max(0, ceil(total * target_reviewed_pct / 100) - coverage["reviewed"]),
            "distinct_requirements_in_packet": len(requirements),
            "requirements_with_source_references": sum(
                any(c["source_reference_present"] for c in row["candidates"]) for row in requirements
            ),
            "requirements_needing_catalog_repair": sum(
                any(c["requires_catalog_repair"] for c in row["candidates"]) for row in requirements
            ),
            "batch_count": len(batches),
        },
        "review_checklist": [
            "Compare the complete requirement and source with the safeguard operating contract; a related topic is not equivalence.",
            "Check evidence specificity, applicability, parameters, prerequisites and limitations.",
            "Record your actual approve, needs_changes or reject decision with reviewer identity and rationale; no default is approval.",
            "Refresh the queue if a source, definition or another review decision changes before submission.",
        ],
        "boundaries": [
            "This packet records no decisions and grants no review or assessment credit.",
            "Source-reference presence is not verification of the source or mapping correctness.",
            "Counts are distinct catalog requirements; alternate mappings are not additional coverage.",
            "Organization decisions affect that organization's coverage, not the shipped catalog's maintainer-reviewed count.",
        ],
        "batches": batches,
    }
    return {**body, "packet_sha256": canonical_sha256(body)}
