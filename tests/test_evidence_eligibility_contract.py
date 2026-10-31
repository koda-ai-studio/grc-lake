"""Evidence freshness and workpapers must use the evidence supporting the verdict."""

from datetime import UTC, datetime, timedelta

import pytest

from security_lakehouse import mapping_review
from security_lakehouse.io import read_json, read_jsonl, write_jsonl
from security_lakehouse.pipeline import run_pipeline
from test_assurance_truth import complete_events
from test_control_assurance import case, evaluate


@pytest.mark.parametrize("new_status,expected", [("observed", "stale"), ("pass", "pass"), ("unknown", "not_evaluated")])
def test_current_verdict_cannot_borrow_freshness_from_observations(tmp_path, monkeypatch, new_status, expected):
    old = complete_events()
    monkeypatch.setattr(
        mapping_review,
        "effective_safeguards",
        lambda _: {
            "review_log_verified": True,
            "safeguards": [
                {
                    "safeguard_id": "SG-FRESHNESS",
                    "title": "Synthetic freshness contract",
                    "asset_types": sorted({row["entity"]["asset_type"] for row in old}),
                    "required_evidence_types": sorted({row["event_type"] for row in old}),
                    "evaluation_rule": "fail_when_open_violation_or_stale_evidence",
                    "satisfies": [],
                }
            ],
        },
    )
    for row in old:
        row["safeguard_ids"] = ["SG-FRESHNESS"]
        row["event_time"] = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        row["evidence"]["collected_at"] = row["event_time"]
    new = complete_events(new_status)
    for row in new:
        row["event_id"] += "-new"
        row["safeguard_ids"] = ["SG-FRESHNESS"]
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, old + new)
    run_pipeline(raw, lake, tenant_id="audit")
    assert (
        next(r["status"] for r in read_jsonl(lake / "gold/control_posture.jsonl") if r["control_id"] == "SOC2-CC6.1")
        == expected
    )
    assert (
        next(
            r["status"]
            for r in read_json(lake / "gold/ccf_assessment.json")["safeguards"]
            if r["safeguard_id"] == "SG-FRESHNESS"
        )
        == expected
    )
    tests = read_jsonl(lake / "gold/control_tests.jsonl")
    assert (
        all(r["result"] != "pass" for r in tests) if expected != "pass" else any(r["result"] == "pass" for r in tests)
    )
    # Observations remain inspectable even though they cannot renew a verdict.
    assert len(read_jsonl(lake / "silver/normalized_events.jsonl")) == len(old + new)
    assert len(read_jsonl(lake / "gold/evidence_freshness.jsonl")) == len(old + new)


def test_workpaper_requires_available_evidence_for_design_and_operating_samples(tmp_path):
    plan, rows = case(tmp_path)
    for row in rows:
        row.pop("evidence", None)
    paper = evaluate(tmp_path, plan, rows)["controls"][0]
    assert paper["design"]["status"] == "insufficient_evidence"
    assert paper["operating"]["status"] == "insufficient_evidence"
    assert paper["operating"]["samples"] == []
    assert len(paper["operating"]["gaps"]) == 2


def test_internal_bronze_references_remain_valid_evidence(tmp_path):
    plan, rows = case(tmp_path)
    for row in rows:
        row["evidence"] = {"collected_at": row["event_time"]}
    paper = evaluate(tmp_path, plan, rows)["controls"][0]
    assert paper["design"]["status"] == "documented"
    assert paper["operating"]["status"] == "sample_pass"
