"""The maintainer's batch approval covers the presented SOC 2 and ISO 27001 queue only."""

import json
from pathlib import Path

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.io import canonical_sha256
from security_lakehouse.mapping_review_packet import build_review_packet
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards
from test_soc2_iso_review_receipt import BATCH_RECEIPT, without_repair_approvals

ROOT = Path(__file__).resolve().parents[1]
PACKET = "docs/reviews/2026-10-25-soc2-iso27001-pending-queue.json"
FRAMEWORKS = {"soc2", "iso-27001-2022"}
RATIONALE = (
    "Maintainer batch approval on 2026-10-25 after reviewing the SOC 2 and ISO 27001 pending queue "
    "against the requirement text; recorded as one decision for all listed mappings, not per-mapping rationales."
)


def _receipt():
    return json.loads((ROOT / BATCH_RECEIPT).read_text())


def _packet():
    return json.loads((ROOT / PACKET).read_text())


def _queue(payload, framework_id, lake_dir):
    packet = build_review_packet(lake_dir, payload=payload, framework_id=framework_id, batch_size=100)
    return {
        (candidate["safeguard_id"], requirement["control_id"]): candidate["review_basis_sha256"]
        for batch in packet["batches"]
        for requirement in batch["requirements"]
        for candidate in requirement["candidates"]
    }


def test_receipt_discloses_a_single_batch_decision_by_the_maintainer():
    receipt = _receipt()
    packet = _packet()
    assert receipt["schema"] == "grc-lake.maintainer-mapping-review.v1"
    assert receipt["reviewer"] == "msaad00"
    assert receipt["decision"] == "approve"
    assert receipt["rationale"] == RATIONALE
    assert receipt["recorded_at"].startswith("2026-10-25T")
    assert "Mapping approval only." in receipt["limitations"]
    assert "Cisco and Oracle references" in receipt["limitations"]
    assert "Operating effectiveness and certification require separate evidence." in receipt["limitations"]
    assert receipt["parent_packet"] == PACKET
    assert receipt["parent_packet_sha256"] == canonical_sha256(packet)
    assert {row["framework_id"] for row in receipt["mappings"]} == FRAMEWORKS
    assert sum(row["framework_id"] == "soc2" for row in receipt["mappings"]) == 35
    assert sum(row["framework_id"] == "iso-27001-2022" for row in receipt["mappings"]) == 36
    expected = {(x["safeguard_id"], x["control_id"]): x["review_basis_sha256"] for x in packet["items"]}
    assert len(expected) == len(packet["items"]) == 123
    assert {x["framework_id"] for x in packet["items"]} == FRAMEWORKS
    approved = {(x["safeguard_id"], x["control_id"]): x["inspected_basis_sha256"] for x in receipt["mappings"]}
    excluded = {(x["safeguard_id"], x["control_id"]): x["inspected_basis_sha256"] for x in receipt["excluded"]}
    assert len(approved) == 71 and len(excluded) == 52
    assert approved.keys().isdisjoint(excluded) and approved | excluded == expected
    assert all(x["decision"] is x["reviewer"] is x["rationale"] is None for x in packet["items"])


def test_title_theme_and_open_recommendation_candidates_are_excluded_and_stay_proposed():
    receipt = _receipt()
    basis = {(x["safeguard_id"], x["control_id"]): x["mapping_basis"] for x in _packet()["items"]}
    excluded = {(x["safeguard_id"], x["control_id"]) for x in receipt["excluded"]}
    open_recommendations = {("SG-AVAILABILITY-001", "SOC2-A1.3"), ("SG-DATAINVENTORY-001", "SOC2-C1.1")}
    assert excluded == {key for key, value in basis.items() if value == "title_theme"} | open_recommendations
    for x in receipt["excluded"]:
        if (x["safeguard_id"], x["control_id"]) in open_recommendations:
            assert "RECOVERY_CONFIDENTIALITY.md" in x["reason"]
        else:
            assert x["framework_id"] == "iso-27001-2022" and "title_theme" in x["reason"]
    for entry in load_safeguards()["safeguards"]:
        for member in entry["satisfies"]:
            if (entry["safeguard_id"], member["control_id"]) in excluded:
                assert member["review_status"] == "proposed"
                assert "maintainer_review_ref" not in member and "reviewed_by" not in member


def test_every_listed_mapping_is_reviewed_and_bound_to_its_inspected_fingerprint(tmp_path):
    receipt = _receipt()
    listed = {(x["safeguard_id"], x["control_id"]): x for x in receipt["mappings"]}
    payload = load_safeguards()
    actual = set()
    for entry in payload["safeguards"]:
        for member in entry["satisfies"]:
            if member.get("maintainer_review_ref") != BATCH_RECEIPT:
                continue
            actual.add((entry["safeguard_id"], member["control_id"]))
            assert member["framework_id"] in FRAMEWORKS
            assert member["review_status"] == "reviewed"
            assert member["reviewed_by"] == "msaad00"
            assert member["reviewed_at"] == receipt["recorded_at"]
    assert actual == set(listed)
    before = without_repair_approvals(payload, receipts=(BATCH_RECEIPT,))
    inspected = {}
    for framework in FRAMEWORKS:
        inspected |= _queue(before, framework, tmp_path)
    presented = [*receipt["mappings"], *receipt["excluded"]]
    expected = {(x["safeguard_id"], x["control_id"]): x["inspected_basis_sha256"] for x in presented}
    assert {key: inspected[key] for key in expected} == expected
    # Demoted historical mappings add candidates; they were not in this decision.
    assert len(inspected.keys() - expected.keys()) == 26


def test_pending_queues_preserve_excluded_items_and_include_demoted_mappings(tmp_path):
    payload = load_safeguards()
    receipt = _receipt()
    excluded = {(x["safeguard_id"], x["control_id"]): x["inspected_basis_sha256"] for x in receipt["excluded"]}
    reviewed_ids = {x["control_id"] for x in receipt["mappings"]}
    open_recommendations = {("SG-AVAILABILITY-001", "SOC2-A1.3"), ("SG-DATAINVENTORY-001", "SOC2-C1.1")}
    soc2_queue = _queue(payload, "soc2", tmp_path)
    assert {k: soc2_queue[k] for k in open_recommendations} == {
        k: v for k, v in excluded.items() if k in open_recommendations
    }
    assert len(soc2_queue) == 15
    iso = _queue(payload, "iso-27001-2022", tmp_path)
    expected = {
        key: value for key, value in excluded.items() if key[1] not in reviewed_ids and key not in open_recommendations
    }
    assert {key: iso[key] for key in expected} == expected
    assert len({key[1] for key in iso}) == 50
    before = without_repair_approvals(payload, receipts=(BATCH_RECEIPT,))
    assert _queue(payload, "iso-42001-2023", tmp_path) == _queue(before, "iso-42001-2023", tmp_path)
    assert len(_queue(payload, "iso-42001-2023", tmp_path)) == 51
    assert not any(
        member.get("maintainer_review_ref") == BATCH_RECEIPT
        for entry in payload["safeguards"]
        for member in entry["satisfies"]
        if member["framework_id"] not in FRAMEWORKS
    )
    soc2 = json.loads((ROOT / "docs/reviews/soc2-batches.json").read_text())
    pending = {r["control_id"] for f in soc2["frameworks"] for b in f["batches"] for r in b["requirements"]}
    assert pending == {cid for _, cid in soc2_queue}
    published = json.loads((ROOT / "docs/reviews/iso-27001-2022-batches.json").read_text())
    rows = [r for f in published["frameworks"] for b in f["batches"] for r in b["requirements"]]
    assert {(c["safeguard_id"], r["control_id"]) for r in rows for c in r["candidates"]} == set(iso)


def test_review_credit_changes_reviewed_counts_only_not_mapping_or_evidence():
    payload = load_safeguards()
    old = coverage_by_framework(without_repair_approvals(payload, receipts=(BATCH_RECEIPT,)))
    new = coverage_by_framework(payload)
    assert old["covered"] == new["covered"] == 2196
    assert old["reviewed"] == 824
    assert new["reviewed"] == 824 + 26 + 36
    frameworks = new["frameworks"]
    assert (frameworks["soc2"]["reviewed"], frameworks["soc2"]["controls"]) == (49, 61)
    assert frameworks["iso-27001-2022"]["reviewed"] == 7 + 36
    assert frameworks["iso-42001-2023"]["reviewed"] == 5
    result = evaluate_safeguards([], {**payload, "review_log_verified": True}, load_control_catalog())
    assert not any(row["status"] == "pass" for row in result["requirements"])
