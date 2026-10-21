"""A maintainer batch decision credits only its inspected, source-backed mappings."""

import json
from copy import deepcopy
from pathlib import Path

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.ccf_contracts import review_basis
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards, member_mapping_source
from test_soc2_iso_review_receipt import without_repair_approvals

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "controls/reviews/2026-10-14-source-batches.json"


def test_maintainer_decision_is_bound_to_each_inspected_mapping():
    receipt = json.loads((ROOT / RECEIPT).read_text())
    assert receipt["reviewer"] == "msaad00"
    assert receipt["decision"] == "approve"
    assert "decision_statement" not in receipt
    assert "rationale" not in receipt
    assert len(receipt["batches"]) == 33
    assert len(receipt["mappings"]) == 885
    assert len({row["control_id"] for row in receipt["mappings"]}) == 806
    catalog = load_control_catalog()
    payload = without_repair_approvals(load_safeguards())
    entries = {entry["safeguard_id"]: entry for entry in payload["safeguards"]}
    expected = {(row["safeguard_id"], row["control_id"]) for row in receipt["mappings"]}
    actual = {
        (entry["safeguard_id"], member["control_id"])
        for entry in entries.values()
        for member in entry["satisfies"]
        if member.get("maintainer_review_ref") == RECEIPT
    }
    assert actual == expected
    for row in receipt["mappings"]:
        entry = entries[row["safeguard_id"]]
        member = next(m for m in entry["satisfies"] if m["control_id"] == row["control_id"])
        assert member["review_status"] == "reviewed"
        assert member["reviewed_by"] == receipt["reviewer"]
        assert member["reviewed_at"] == receipt["recorded_at"]
        assert member_mapping_source(entry, member)
        original = deepcopy(member)
        for key in ("maintainer_review_ref", "reviewed_by", "reviewed_at"):
            original.pop(key)
        original["review_status"] = "proposed"
        assert review_basis(entry, original, catalog[row["control_id"]]) == row["inspected_basis_sha256"]


def test_review_credit_is_distinct_and_does_not_expand_mapping_coverage():
    payload = without_repair_approvals(load_safeguards())
    before = deepcopy(payload)
    for entry in before["safeguards"]:
        for member in entry["satisfies"]:
            if member.get("maintainer_review_ref") == RECEIPT:
                member["review_status"] = "proposed"
    old, new = coverage_by_framework(before), coverage_by_framework(payload)
    assert old["covered"] == new["covered"] == 2196
    assert old["controls"] == new["controls"] == 2282
    assert old["reviewed"] == 339
    assert new["reviewed"] == 1128
    assert new["coverage_pct"] == 96.2
    assert new["reviewed_pct"] == 49.4


def test_stale_approvals_remain_uncredited_and_fresh_evidence_is_still_required(tmp_path):
    from security_lakehouse.ccf_evaluation import evaluate_safeguards
    from security_lakehouse.mapping_review_packet import build_review_packet
    from security_lakehouse.safeguards import effective_review_state

    payload = without_repair_approvals(load_safeguards())
    receipt = json.loads((ROOT / RECEIPT).read_text())
    approved_ids = {m["control_id"] for m in receipt["mappings"]}
    credited_ids = {
        m["control_id"]
        for e in payload["safeguards"]
        for m in e["satisfies"]
        if effective_review_state(m) == "maintainer_reviewed"
    }
    assert len(approved_ids - credited_ids) == 17
    packet = build_review_packet(tmp_path, payload=payload)
    assert packet["summary"]["reviewed_requirements"] == 1128
    assert packet["summary"]["additional_reviewed_needed"] == 13
    assert not list(tmp_path.rglob("*"))
    result = evaluate_safeguards([], {**payload, "review_log_verified": True}, load_control_catalog())
    assert not any(r["status"] == "pass" for r in result["requirements"])


def test_nist_source_check_compares_contracts_without_erasing_review_metadata():
    from tools.sync_nist53_assessment_safeguards import source_contract

    entry = next(e for e in load_safeguards()["safeguards"] if e["safeguard_id"] == "SG-NIST53-AC-10")
    original = deepcopy(entry)
    original["satisfies"][0].pop("current_control_version")
    proposed = deepcopy(original)
    member = proposed["satisfies"][0]
    member["review_status"] = "proposed"
    for field in ("maintainer_review_ref", "reviewed_by", "reviewed_at"):
        member.pop(field)
    assert source_contract(original) == proposed
    assert original["satisfies"][0]["review_status"] == "reviewed"
    original["evidence_requirement"] = "weaker evidence"
    assert source_contract(original) != proposed
