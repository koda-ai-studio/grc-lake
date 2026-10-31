"""Readiness retains collection gaps independently of observed test scores."""

import json

import pytest

from security_lakehouse.assessment import build_current_posture, load_snapshot, write_assessment_snapshot
from security_lakehouse.io import read_json, read_jsonl, write_jsonl
from security_lakehouse.pipeline import run_pipeline
from test_assurance_truth import complete_events, event


def evidence(status="pass"):
    return [
        dict(row, source="aws", tenant_id="source-a", safeguard_ids=["SG-NIST53-AC-10"])
        for row in [
            *complete_events(status),
            dict(event(status), event_id="typed-assessment", event_type="nist53_ac_10_assessment"),
        ]
    ]


def gap(source="aws"):
    return dict(
        event("not_evaluated"),
        source=source,
        tenant_id="source-b",
        event_id="gap-b",
        entity={"asset_id": "collection-b", "asset_type": "collection_scope"},
        controls=[],
        attributes={"collection_gap": True},
    )


@pytest.mark.parametrize("source", ["aws", "gcp"])
def test_gap_blocks_aggregate_readiness_but_only_its_provider_framework(tmp_path, source):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, evidence() + [gap(source)])
    run_pipeline(raw, lake, tenant_id="platform-org")
    current = build_current_posture(lake)
    assert current["posture"]["state"] == "attention_required"
    assert current["posture"]["score"] == 100
    assert current["posture"]["collection_gap_count"] == 1
    assert current["collection_gaps"] == {
        "sources": [source],
        "affected_control_ids": ["SOC2-CC6.1"] if source == "aws" else [],
    }
    [framework] = current["frameworks"]
    assert framework["state"] == ("attention_required" if source == "aws" else "ready")
    assert framework["score"] == 100
    assert framework["passing_control_count"] == 1
    assert framework["collection_gap_control_count"] == (1 if source == "aws" else 0)
    assert read_jsonl(lake / "gold/control_posture.jsonl")[0]["status"] == "pass"
    ccf = read_json(lake / "gold/ccf_assessment.json")
    [safeguard] = [row for row in ccf["safeguards"] if row["safeguard_id"] == "SG-NIST53-AC-10"]
    assert safeguard["status"] == ("not_evaluated" if source == "aws" else "pass")


def test_gap_preserves_failures_and_critical_state(tmp_path):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    rows = [dict(row, severity="critical") for row in evidence("open")]
    write_jsonl(raw, rows + [gap()])
    run_pipeline(raw, lake, tenant_id="platform-org")
    current = build_current_posture(lake)
    assert current["posture"]["state"] == "critical"
    assert current["posture"]["score"] == 0
    assert current["frameworks"][0]["failing_control_count"] == 1
    assert current["frameworks"][0]["collection_gap_control_count"] == 1
    ccf = read_json(lake / "gold/ccf_assessment.json")
    assert next(row for row in ccf["safeguards"] if row["safeguard_id"] == "SG-NIST53-AC-10")["status"] == "fail"


def test_gap_clearing_refreshes_live_surfaces_but_preserves_snapshot(tmp_path, capsys):
    from security_lakehouse.api_v1 import handle_get
    from security_lakehouse.cli import main

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, evidence() + [gap()])
    run_pipeline(raw, lake, tenant_id="platform-org")
    current = build_current_posture(lake)
    assert current["posture"]["state"] == "attention_required"
    status, response = handle_get("/api/v1/posture/current", {}, lake)
    assert status == 200
    assert response["data"]["posture"] == current["posture"]
    assert response["data"]["frameworks"] == current["frameworks"]
    assert main(["assessment", "status", "--lake", str(lake)]) == 0
    cli = json.loads(capsys.readouterr().out)
    assert cli["posture"] == current["posture"]
    assert main(["assessment", "status", "--lake", str(lake), "--format", "summary"]) == 0
    assert "attention_required" in capsys.readouterr().out
    snapshot = write_assessment_snapshot(lake)
    frozen = load_snapshot(lake, snapshot.stem)
    assert frozen["posture"] == current["posture"]
    write_jsonl(raw, evidence())
    run_pipeline(raw, lake, tenant_id="platform-org")
    updated = build_current_posture(lake)
    assert updated["posture"]["state"] == "ready"
    assert updated["posture"]["collection_gap_count"] == 0
    assert updated["frameworks"][0]["state"] == "ready"
    assert updated["collection_gaps"] == {"sources": [], "affected_control_ids": []}
    assert load_snapshot(lake, snapshot.stem) == frozen
