"""Every reviewed mapping names its provenance; nothing rests on a placeholder reviewer."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from security_lakehouse.safeguards import (
    LEGACY_REVIEW_RECORD,
    coverage_by_framework,
    load_safeguards,
    mapping_review_items,
    review_provenance,
)

ROOT = Path(__file__).resolve().parents[1]
# The legacy set may only shrink: a row leaves it when a receipt-bound review
# replaces it, or when it is demoted to proposed. Never add to it.
LEGACY_CEILING = 354


def _record() -> dict:
    return json.loads((ROOT / LEGACY_REVIEW_RECORD).read_text())


def _unreceipted_reviewed(payload: dict) -> set[tuple[str, str]]:
    return {
        (entry["safeguard_id"], member["control_id"])
        for entry in payload["safeguards"]
        for member in entry["satisfies"]
        if member.get("review_status", "reviewed") == "reviewed" and not member.get("maintainer_review_ref")
    }


def test_no_safeguard_names_a_placeholder_reviewer() -> None:
    for entry in load_safeguards()["safeguards"]:
        assert entry.get("reviewed_by") is None, entry["safeguard_id"]
        assert entry.get("reviewed_at") is None, entry["safeguard_id"]


def test_legacy_record_lists_exactly_the_unreceipted_reviewed_mappings() -> None:
    record = _record()
    assert record["schema"] == "grc-lake.legacy-mapping-review.v1"
    assert record["reviewer"] is None
    assert record["decision"] is None
    listed = {(row["safeguard_id"], row["control_id"]) for row in record["mappings"]}
    assert len(listed) == len(record["mappings"])
    assert len(listed) <= LEGACY_CEILING
    actual = _unreceipted_reviewed(load_safeguards())
    assert actual - listed == set(), "new reviewed mappings need a decision receipt, not a legacy entry"
    assert listed - actual == set(), "remove rows that now carry a receipt or are no longer reviewed"
    origins = {row["commit"] for row in record["origins"]}
    assert all(row["origin_commit"] in origins for row in record["mappings"])
    assert sum(row["mapping_count"] for row in record["origins"]) == len(listed)


def test_provenance_separates_receipts_from_legacy_and_org_decisions() -> None:
    assert review_provenance({"review_status": "reviewed", "maintainer_review_ref": "controls/reviews/x.json"}) == (
        "maintainer_receipt"
    )
    assert review_provenance({"review_status": "reviewed"}) == "legacy_unattributed"
    assert review_provenance({"review_status": "proposed"}) is None
    assert review_provenance({"review_status": "proposed", "effective_review_state": "org_reviewed"}) == (
        "org_decision"
    )
    stale = {"review_status": "reviewed", "control_version": "1.0.0", "current_control_version": "2.0.0"}
    assert review_provenance(stale) is None


def test_coverage_reports_requirements_resting_only_on_legacy_reviews() -> None:
    cov = coverage_by_framework()
    assert cov["reviewed"] == 1227
    # 354 listed rows less 13 whose control version is stale (already proposed)
    # and 1 supporting relationship that never earns coverage.
    assert cov["legacy_unattributed_mappings"] == 340
    assert cov["legacy_only_reviewed"] == 339
    assert cov["receipt_reviewed"] == cov["reviewed"] - cov["legacy_only_reviewed"] == 888
    soc2 = cov["frameworks"]["soc2"]
    assert soc2["reviewed"] == 61
    assert soc2["legacy_only_reviewed"] == 10
    assert cov["frameworks"]["cis_aws"]["legacy_only_reviewed"] == cov["frameworks"]["cis_aws"]["reviewed"] == 39
    assert cov["frameworks"]["dora-2022-2554"]["legacy_only_reviewed"] == 0
    assert sum(row["legacy_only_reviewed"] for row in cov["frameworks"].values()) == cov["legacy_only_reviewed"]


def test_a_receipt_moves_a_requirement_out_of_legacy_only() -> None:
    payload = load_safeguards()
    before = coverage_by_framework(payload)
    changed = deepcopy(payload)
    entry = next(e for e in changed["safeguards"] if e["safeguard_id"] == "SG-IDENTITY-001")
    member = next(m for m in entry["satisfies"] if m["control_id"] == "CIS-AWS-1.10")
    member["maintainer_review_ref"] = "controls/reviews/example.json"
    after = coverage_by_framework(changed)
    assert after["reviewed"] == before["reviewed"]
    assert after["legacy_only_reviewed"] == before["legacy_only_reviewed"] - 1
    assert after["frameworks"]["cis_aws"]["legacy_only_reviewed"] == 38


def test_review_items_carry_provenance() -> None:
    items = {(i["safeguard_id"], i["control_id"]): i for i in mapping_review_items()}
    assert items[("SG-IDENTITY-001", "SOC2-CC6.1")]["review_provenance"] == "legacy_unattributed"
    receipt = next(i for i in items.values() if i["review_provenance"] == "maintainer_receipt")
    assert receipt["review_state"] == "maintainer_reviewed"
    assert all(i["review_provenance"] is None for i in items.values() if i["review_state"] == "proposed")
