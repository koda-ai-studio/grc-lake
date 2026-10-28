"""The maintainer's decision covers only the 35 presented repair contracts."""

import json
from copy import deepcopy
from pathlib import Path

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.ccf_contracts import review_basis
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.io import canonical_sha256
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "controls/reviews/2026-10-15-soc2-iso-repairs.json"
PACKET = "docs/reviews/2026-10-15-repaired-proposals.json"
BATCH_RECEIPT = "controls/reviews/2026-10-25-soc2-iso27001-batch.json"


def without_repair_approvals(payload, receipts=(RECEIPT, BATCH_RECEIPT)):
    result = deepcopy(payload)
    for entry in result["safeguards"]:
        for member in entry["satisfies"]:
            if member.get("maintainer_review_ref") in receipts:
                member["review_status"] = "proposed"
                for field in ("maintainer_review_ref", "reviewed_by", "reviewed_at"):
                    member.pop(field)
    return result


def test_decision_is_bound_to_the_presented_35_contracts_only():
    receipt = json.loads((ROOT / RECEIPT).read_text())
    packet = json.loads((ROOT / PACKET).read_text())
    assert receipt["reviewer"] == "msaad00"
    assert "decision_statement" not in receipt
    assert "rationale" not in receipt
    assert receipt["decision"] == "approve"
    assert receipt["parent_packet_sha256"] == canonical_sha256(packet)
    expected = {(x["safeguard_id"], x["control_id"]): x for x in packet["items"]}
    assert len(expected) == len(receipt["mappings"]) == 35
    assert {(x["safeguard_id"], x["control_id"]) for x in receipt["mappings"]} == set(expected)
    payload = load_safeguards()
    before = {e["safeguard_id"]: e for e in without_repair_approvals(payload)["safeguards"]}
    actual = set()
    catalog = load_control_catalog()
    for entry in payload["safeguards"]:
        for member in entry["satisfies"]:
            if member.get("maintainer_review_ref") != RECEIPT:
                continue
            key = entry["safeguard_id"], member["control_id"]
            actual.add(key)
            assert member["review_status"] == "reviewed"
            assert member["reviewed_by"] == receipt["reviewer"]
            assert member["reviewed_at"] == receipt["recorded_at"]
            original = before[entry["safeguard_id"]]
            assert (
                review_basis(original, original["satisfies"][0], catalog[key[1]])
                == expected[key]["review_basis_sha256"]
            )
    assert actual == set(expected)
    assert all(x["decision"] is x["reviewer"] is x["rationale"] is None for x in packet["items"])


def test_review_credit_changes_only_the_approved_requirements_not_mapping_or_evidence():
    payload = load_safeguards()
    old = coverage_by_framework(without_repair_approvals(payload))
    new = coverage_by_framework(without_repair_approvals(payload, receipts=(BATCH_RECEIPT,)))
    assert old["covered"] == new["covered"] == 2198
    assert old["reviewed"] == 789
    assert new["reviewed"] == 824
    assert new["reviewed_pct"] == 36.1
    result = evaluate_safeguards([], {**payload, "review_log_verified": True}, load_control_catalog())
    assert not any(row["status"] == "pass" for row in result["requirements"])
