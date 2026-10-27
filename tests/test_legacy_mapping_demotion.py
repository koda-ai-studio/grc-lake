"""Unattributed shipped mappings cannot turn operating evidence into attestation."""

import json
from pathlib import Path

from security_lakehouse.io import read_json, write_jsonl
from security_lakehouse.oscal import build_component_definition
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.safeguards import LEGACY_REVIEW_RECORD, load_safeguards
from test_assurance_truth import complete_events

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_reviewed_mappings_all_name_a_receipt():
    for entry in load_safeguards()["safeguards"]:
        for member in entry["satisfies"]:
            if member["review_status"] == "reviewed":
                assert member.get("maintainer_review_ref"), (entry["safeguard_id"], member["control_id"])


def test_legacy_mapping_does_not_attest_passing_evidence_or_enter_oscal(tmp_path):
    control = "CIS-AWS-1.10"
    raw = tmp_path / "raw.jsonl"
    write_jsonl(
        raw,
        [
            {**row, "source": "aws", "controls": [control], "safeguard_ids": ["SG-IDENTITY-001"]}
            for row in complete_events()
        ],
    )
    lake = tmp_path / "lake"
    run_pipeline(raw, lake, tenant_id="audit")
    assessment = read_json(lake / "gold/ccf_assessment.json")
    safeguard = next(row for row in assessment["safeguards"] if row["safeguard_id"] == "SG-IDENTITY-001")
    assert safeguard["status"] == "pass"
    requirement = next(row for row in assessment["requirements"] if row["control_id"] == control)
    assert requirement["status"] == "not_evaluated"
    assert requirement["reviewed_safeguard_ids"] == []
    component = build_component_definition()
    exported = {
        prop["value"]
        for row in component["component-definition"]["components"]
        for implementation in row.get("control-implementations", [])
        for requirement in implementation["implemented-requirements"]
        for prop in requirement["props"]
        if prop["name"] == "trustops-control-id"
    }
    assert control not in exported


def test_historical_legacy_inventory_is_retained_without_review_credit():
    record = json.loads((ROOT / LEGACY_REVIEW_RECORD).read_text())
    assert record["status"] == "demoted_to_proposed"
    assert len(record["mappings"]) == 354
    members = {
        (entry["safeguard_id"], member["control_id"]): member
        for entry in load_safeguards()["safeguards"]
        for member in entry["satisfies"]
    }
    assert all(
        members[(row["safeguard_id"], row["control_id"])]["review_status"] == "proposed" for row in record["mappings"]
    )


def test_review_queue_can_reopen_legacy_requirements_without_inventing_a_decision():
    from tools.sync_soc2_iso_review import review_artifacts

    plan = json.loads((ROOT / "controls/soc2_iso_review_plan.json").read_text())
    packet, _ = review_artifacts(load_safeguards(), plan, {})
    rows = [r for f in packet["frameworks"] for b in f["batches"] for r in b["requirements"]]
    row = next(r for r in rows if r["control_id"] == "SOC2-A1.2")
    assert "SOC2-A1.2" in row["question"]
    assert "requirement text" in row["question"]
    assert all(c["decision"] is c["reviewer"] is c["rationale"] is None for c in row["candidates"])
