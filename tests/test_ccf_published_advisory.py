"""GHSA-76q3-wh53-hvv2 stays blocked through the shipped catalog and public outputs."""

from datetime import UTC, datetime

import pytest

from security_lakehouse import api_v1
from security_lakehouse.assessment import load_snapshot, write_assessment_snapshot
from security_lakehouse.generations import active_generation
from security_lakehouse.io import read_json, write_jsonl
from security_lakehouse.oscal import build_assessment_results
from security_lakehouse.pipeline import run_pipeline, run_pipeline_incremental


@pytest.mark.parametrize("status", ["pass", "open"])
def test_unrelated_mfa_cannot_assess_physical_safeguard_with_shipped_catalog(tmp_path, status):
    now = datetime.now(UTC).isoformat()
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(
        raw,
        [
            {
                "event_id": "synthetic-unrelated-mfa",
                "tenant_id": "synthetic-audit",
                "event_time": now,
                "source": "synthetic-qualification",
                "event_type": "identity.mfa",
                "entity": {"asset_id": "synthetic-role", "asset_type": "iam_role"},
                "severity": "high" if status == "open" else "info",
                "status": status,
                "controls": ["NIST-CSF-PR.AA-06"],
                "safeguard_ids": ["SG-PHYSICAL-001"],
                "evidence": {"uri": "fixture://synthetic-mfa", "collected_at": now},
                "attributes": {"synthetic": True},
            }
        ],
    )
    run_pipeline(raw, lake, tenant_id="synthetic-audit")
    assessment = read_json(lake / "gold/ccf_assessment.json")
    safeguard = next(row for row in assessment["safeguards"] if row["safeguard_id"] == "SG-PHYSICAL-001")
    requirement = next(row for row in assessment["requirements"] if row["control_id"] == "NIST-CSF-PR.AA-06")
    assert safeguard["status"] == requirement["status"] == "not_evaluated"
    bound = next(row for row in assessment["asset_results"] if row["safeguard_id"] == "SG-PHYSICAL-001")
    assert bound["status"] == "not_evaluated"
    assert bound["reasons"]
    assert bound["event_ids"] == ["synthetic-unrelated-mfa"]
    assert bound["evidence_hashes"]

    code, body = api_v1.handle_get("/api/v1/ccf/assessment", {}, lake)
    assert code == 200
    assert next(row for row in body["data"]["safeguards"] if row["safeguard_id"] == "SG-PHYSICAL-001") == safeguard
    assert next(row for row in body["data"]["requirements"] if row["control_id"] == "NIST-CSF-PR.AA-06") == requirement
    findings = build_assessment_results(lake)["assessment-results"]["results"][0]["findings"]
    finding = next(
        row
        for row in findings
        if {prop["name"]: prop["value"] for prop in row["props"]}["trustops-control-id"] == "NIST-CSF-PR.AA-06"
    )
    assert finding["target"]["status"]["state"] == "not-satisfied"
    assert {row["name"]: row["value"] for row in finding["props"]}["trustops-ccf-status"] == "not_evaluated"

    generation = active_generation(lake)
    frozen_generation = (generation / "gold/ccf_assessment.json").read_bytes()
    snapshot = write_assessment_snapshot(lake)
    frozen_snapshot = load_snapshot(lake, snapshot.stem)
    run_pipeline_incremental(raw, lake, tenant_id="synthetic-audit")
    assert read_json(lake / "gold/ccf_assessment.json") == assessment
    assert (generation / "gold/ccf_assessment.json").read_bytes() == frozen_generation
    assert load_snapshot(lake, snapshot.stem) == frozen_snapshot
