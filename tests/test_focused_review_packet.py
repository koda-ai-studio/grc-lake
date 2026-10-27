"""Focused human review cannot omit requests or invent review credit."""

import json
from pathlib import Path

import pytest

from security_lakehouse.cli import main
from security_lakehouse.mapping_review_packet import build_review_packet

TARGETS = ["SOC2-A1.3", "SOC2-C1.1"]


def test_published_focused_packet_matches_current_basis_and_records_no_decisions():
    path = Path(__file__).resolve().parents[1] / "docs/reviews/stability-review-packet.json"
    assert json.loads(path.read_text()) == build_review_packet(framework_id="soc2", control_ids=TARGETS)


@pytest.mark.parametrize(
    "control,safeguard", [("SOC2-A1.3", "SG-AVAILABILITY-001"), ("SOC2-C1.1", "SG-DATAINVENTORY-001")]
)
def test_passing_operational_evidence_does_not_approve_these_candidates(tmp_path, control, safeguard):
    from security_lakehouse.io import read_json, write_jsonl
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import event

    record = {
        **event(),
        "entity": {"asset_id": "service-1", "asset_type": "service"},
        "controls": [control],
        "safeguard_ids": [safeguard],
    }
    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [record])
    lake = tmp_path / "lake"
    run_pipeline(raw, lake, tenant_id="audit")
    result = read_json(lake / "gold/ccf_assessment.json")
    assert next(row for row in result["safeguards"] if row["safeguard_id"] == safeguard)["status"] == "pass"
    requirement = next(row for row in result["requirements"] if row["control_id"] == control)
    assert requirement["status"] == "not_evaluated"
    assert requirement["reviewed_safeguard_ids"] == []


def test_focused_packet_preserves_basis_and_global_coverage_without_decisions():
    full = build_review_packet(framework_id="soc2")
    focused = build_review_packet(framework_id="soc2", control_ids=TARGETS + TARGETS[:1], batch_size=1)
    rows = [row for batch in focused["batches"] for row in batch["requirements"]]
    expected = [row for batch in full["batches"] for row in batch["requirements"] if row["control_id"] in TARGETS]
    assert rows == expected
    assert focused["control_filter"] == TARGETS
    assert focused["summary"]["distinct_requirements_in_packet"] == 2
    assert focused["summary"]["catalog_requirements"] == full["summary"]["catalog_requirements"]
    assert focused["summary"]["reviewed_requirements"] == full["summary"]["reviewed_requirements"]
    assert all(c["decision"] is c["reviewer"] is c["rationale"] is None for r in rows for c in r["candidates"])


@pytest.mark.parametrize(
    "ids,framework", [([], None), (["missing"], None), (TARGETS, "iso-27001-2022"), (["SOC2-CC1.1"], "soc2")]
)
def test_unavailable_requirements_are_not_silently_omitted(ids, framework):
    with pytest.raises(ValueError):
        build_review_packet(framework_id=framework, control_ids=ids)


def test_cli_exports_exact_requested_packet_and_keeps_output_on_invalid_request(tmp_path):
    output = tmp_path / "packet.json"
    args = ["frameworks", "review", "packet", "--framework", "soc2", "--out", str(output)]
    assert main([*args, "--control", TARGETS[0], "--control", TARGETS[1]]) == 0
    before = output.read_bytes()
    assert json.loads(before)["control_filter"] == TARGETS
    assert main([*args, "--control", "missing"]) == 1
    assert output.read_bytes() == before
