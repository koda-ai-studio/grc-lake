"""ISO additions are scoped proposals, with reproducible source boundaries."""

import json
from copy import deepcopy

import pytest

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards
from test_soc2_iso_mapping_repairs import GENERATOR, PLAN, ROOT, source_index
from test_soc2_iso_review_receipt import BATCH_RECEIPT, without_repair_approvals

TARGETS = [
    *[
        "ISO27001-A." + suffix
        for suffix in ("5.11", "5.3", "5.32", "5.37", "5.6", "6.1", "6.2", "6.4", "6.5", "6.6", "8.1", "8.34")
    ],
    "ISO42001-10.4",
    "ISO42001-2.3",
    "ISO42001-A.6.1.3",
]


@pytest.mark.parametrize("cid", TARGETS)
def test_iso_gaps_have_distinct_unapproved_assessment_contracts(cid):
    payload = without_repair_approvals(load_safeguards(), receipts=(BATCH_RECEIPT,))
    entries = [(s, m) for s in payload["safeguards"] for m in s["satisfies"] if m["control_id"] == cid]
    assert len(entries) == 1
    safeguard, member = entries[0]
    assert len(safeguard["satisfies"]) == 1
    assert member["review_status"] == "proposed"
    assert not member.get("reviewed_by") and not member.get("maintainer_review_ref")
    assert safeguard["required_evidence_types"] == ["review_" + cid.lower().replace("-", "_").replace(".", "_")]
    assert "population" in safeguard["evidence_requirement"]
    assert "not a published equivalence" in member["mapping_source"]["locator"]
    repair = next(r for r in PLAN["repairs"] if r["control_id"] == cid)
    assert repair["replaces"] == []
    assert len(repair["evidence_checks"].split()) >= 25


def test_iso_additions_change_only_proposed_coverage():
    coverage = coverage_by_framework(without_repair_approvals(load_safeguards(), receipts=(BATCH_RECEIPT,)))
    assert (coverage["covered"], coverage["reviewed"]) == (2196, 824)


def test_new_contract_refuses_unexpected_existing_mapping():
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    cid = TARGETS[0]
    plan = deepcopy(PLAN)
    # Also exercises the guard before the generated contract is first installed.
    sid = "SG-REVIEW-" + cid.replace(".", "-")
    payload["safeguards"] = [s for s in payload["safeguards"] if s["safeguard_id"] != sid]
    payload["safeguards"][0]["satisfies"].append({"control_id": cid, "review_status": "proposed"})
    with pytest.raises(ValueError, match="already mapped"):
        GENERATOR["repaired_payload"](payload, plan, source_index(), load_control_catalog())


def test_cisco_addition_requires_explicit_reference():
    plan = deepcopy(PLAN)
    repair = next(r for r in plan["repairs"] if r["control_id"] == TARGETS[0])
    repair["cisco_controls"] = []
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    with pytest.raises(ValueError, match="explicit Cisco"):
        GENERATOR["repaired_payload"](payload, plan, source_index(), load_control_catalog())
