"""Reviewed coverage separates source-native self-maps from crosswalk mappings."""

from __future__ import annotations

from security_lakehouse import safeguards
from security_lakehouse.framework_coverage import (
    build_framework_coverage,
    framework_coverage_summary,
    render_framework_coverage_markdown,
)

REGISTRY = {"fw-a": {"source_sha256": "a" * 64}, "fw-b": {"source_sha256": None}}
CATALOG = {
    "A1": {"framework_id": "fw-a"},
    "A2": {"framework_id": "fw-a"},
    "A3": {"framework_id": "fw-a"},
    "A4": {"framework_id": "fw-a"},
    "B1": {"framework_id": "fw-b"},
}


def _member(control_id: str, status: str = "reviewed", sha256: str | None = "a" * 64) -> dict:
    member: dict = {"control_id": control_id, "role": "primary", "review_status": status}
    if sha256 is not None:
        member["mapping_source"] = {"name": "own source", "sha256": sha256}
    return member


PAYLOAD = {
    "safeguards": [
        {"safeguard_id": "SG-SELF-A1", "satisfies": [_member("A1")]},
        {"safeguard_id": "SG-SELF-A2", "satisfies": [_member("A2", status="proposed")]},
        {"safeguard_id": "SG-MULTI", "satisfies": [_member("A2"), _member("B1", sha256=None)]},
        {"safeguard_id": "SG-SELF-A3", "satisfies": [_member("A3")]},
        {"safeguard_id": "SG-CROSS-A3", "satisfies": [_member("A3", sha256="b" * 64)]},
    ]
}


def test_self_map_requires_one_target_citing_the_frameworks_pinned_source() -> None:
    entry = PAYLOAD["safeguards"][0]
    assert safeguards.is_source_native_mapping(entry, entry["satisfies"][0], "fw-a", REGISTRY)

    multi = PAYLOAD["safeguards"][2]
    assert not safeguards.is_source_native_mapping(multi, multi["satisfies"][0], "fw-a", REGISTRY)

    other_source = PAYLOAD["safeguards"][4]
    assert not safeguards.is_source_native_mapping(other_source, other_source["satisfies"][0], "fw-a", REGISTRY)

    unpinned = {"satisfies": [_member("B1")]}
    assert not safeguards.is_source_native_mapping(unpinned, unpinned["satisfies"][0], "fw-b", REGISTRY)
    unpinned_match = {"satisfies": [_member("B1", sha256="")]}
    assert not safeguards.is_source_native_mapping(unpinned_match, unpinned_match["satisfies"][0], "fw-b", {})

    no_source = {"satisfies": [_member("A1", sha256=None)]}
    assert not safeguards.is_source_native_mapping(no_source, no_source["satisfies"][0], "fw-a", REGISTRY)
    assert not safeguards.is_source_native_mapping(
        {"satisfies": [{"control_id": "A1", "mapping_source": "free text"}]},
        {"control_id": "A1", "mapping_source": "free text"},
        "fw-a",
        REGISTRY,
    )


def test_reviewed_requirements_split_into_disjoint_self_map_and_crosswalk_counts() -> None:
    result = safeguards.framework_mapping_coverage(PAYLOAD, catalog=CATALOG, registry=REGISTRY)
    fw_a = result["frameworks"]["fw-a"]
    fw_b = result["frameworks"]["fw-b"]

    assert fw_a["reviewed"] == 3
    # A1: only a reviewed self-map. A2: its self-map is proposed, so the reviewed
    # crosswalk credits it. A3: any reviewed crosswalk takes precedence.
    assert fw_a["source_native_reviewed"] == 1
    assert fw_a["crosswalk_reviewed"] == 2
    assert fw_a["source_native_reviewed_mappings"] == 2
    assert fw_a["crosswalk_reviewed_pct"] == 50.0
    assert fw_b["reviewed"] == fw_b["crosswalk_reviewed"] == 1
    assert fw_b["source_native_reviewed"] == 0

    assert result["source_native_reviewed"] == 1
    assert result["crosswalk_reviewed"] == 3
    assert result["source_native_reviewed"] + result["crosswalk_reviewed"] == result["reviewed"]


def test_rejected_or_proposed_self_maps_never_count_as_reviewed() -> None:
    payload = {"safeguards": [{"safeguard_id": "SG-SELF", "satisfies": [_member("A1", status="proposed")]}]}
    result = safeguards.framework_mapping_coverage(payload, catalog=CATALOG, registry=REGISTRY)
    assert result["source_native_reviewed"] == result["crosswalk_reviewed"] == result["reviewed"] == 0
    assert result["frameworks"]["fw-a"]["source_native_reviewed"] == 0


def test_shipped_catalog_splits_every_framework_and_matches_the_nist_expansion() -> None:
    rows = build_framework_coverage()
    by_id = {row["framework_id"]: row for row in rows}
    for row in rows:
        assert (
            row["source_native_reviewed_requirement_count"] + row["crosswalk_reviewed_requirement_count"]
            == row["attestable_requirement_count"]
        ), row["framework_id"]

    # Independent oracle: the NIST 800-53 expansion generates one SG-NIST53-*
    # safeguard per obligation from the pinned OSCAL catalog.
    payload = safeguards.load_safeguards()
    expansion_reviewed = sum(
        1
        for entry in payload["safeguards"]
        if entry["safeguard_id"].startswith("SG-NIST53-")
        and all(member.get("review_status") == "reviewed" for member in entry["satisfies"])
    )
    nist = by_id["nist-800-53-rev5"]
    assert nist["source_native_reviewed_requirement_count"] == expansion_reviewed > 0
    assert nist["crosswalk_reviewed_requirement_count"] == (nist["attestable_requirement_count"] - expansion_reviewed)

    summary = framework_coverage_summary(rows)
    assert summary["source_native_reviewed_requirement_count"] == sum(
        row["source_native_reviewed_requirement_count"] for row in rows
    )
    assert (
        summary["source_native_reviewed_requirement_count"] + summary["crosswalk_reviewed_requirement_count"]
        == summary["attestable_requirement_count"]
    )


def test_coverage_matrix_reports_self_map_and_crosswalk_columns() -> None:
    rows = build_framework_coverage()
    summary = framework_coverage_summary(rows)
    markdown = render_framework_coverage_markdown(rows)
    assert "| Source-native self-maps | Crosswalk reviewed | Crosswalk reviewed % | No recorded reviewer |" in markdown
    nist = next(row for row in rows if row["framework_id"] == "nist-800-53-rev5")
    nist_line = next(line for line in markdown.splitlines() if line.startswith(f"| {nist['name']} |"))
    assert (
        f"| {nist['attestable_requirement_count']} | {nist['attestable_coverage_pct']}% "
        f"| {nist['source_native_reviewed_requirement_count']} | {nist['crosswalk_reviewed_requirement_count']} "
        f"| {nist['crosswalk_reviewed_coverage_pct']}% | {nist['legacy_only_reviewed_requirement_count']} |"
        in nist_line
    )
    assert f"of which {summary['source_native_reviewed_requirement_count']} are source-native self-maps" in markdown
