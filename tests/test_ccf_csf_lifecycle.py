"""CSF improvement and recovery outcomes require their own operational evidence."""

from copy import deepcopy
from pathlib import Path

import pytest

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.safeguards import (
    coverage_by_family,
    coverage_by_framework,
    load_safeguards,
    validate_safeguards,
)
from test_ccf_operational_assessment import normalized

CASES = {
    "SG-EVALUATIONIMPROVEMENT-001": ("ID.IM-01", "evaluation_improvement_assessment"),
    "SG-OPERATIONALIMPROVEMENT-001": ("ID.IM-03", "operational_improvement_assessment"),
    "SG-RECOVERYINITIATION-001": ("RS.MA-05", "recovery_initiation_assessment"),
    "SG-POSTINCIDENTNORMS-001": ("RC.RP-04", "post_incident_norms_assessment"),
    "SG-RECOVERYCOMPLETION-001": ("RC.RP-06", "recovery_completion_assessment"),
}


def test_documented_family_counts_match_the_expanded_catalog():
    text = (Path(__file__).resolve().parents[1] / "docs/COMMON_CONTROL_FRAMEWORK.md").read_text()
    for row in coverage_by_family():
        line = next(line for line in text.splitlines() if f"`{row['family_id']}`" in line and line.startswith("|"))
        assert int(line.split("|")[4].strip()) == row["safeguard_count"]


def test_five_outcomes_have_independent_source_pinned_proposed_safeguards():
    payload = load_safeguards()
    assert validate_safeguards(payload) == []
    entries = {row["safeguard_id"]: row for row in payload["safeguards"]}
    for sid, (outcome, evidence_type) in CASES.items():
        entry = entries[sid]
        assert entry["required_evidence_types"] == [evidence_type]
        assert entry["reviewed_by"] is None and entry["reviewed_at"] is None
        assert len(entry["satisfies"]) == 1
        member = entry["satisfies"][0]
        assert member["control_id"] == "NIST-CSF-" + outcome
        assert member["framework_id"] == "nist-csf-2.0"
        assert member["role"] == "primary" and member["review_status"] == "proposed"
        assert member["control_version"] == load_control_catalog()[member["control_id"]]["version"]
        assert member["mapping_source"]["sha256"] == "3c31f46fee98cac0c4323453e5109291a213b4de7fef8c058af9bf67f717433c"
        assert outcome in member["mapping_source"]["locator"]


def test_csf_catalog_mapping_gaps_close_without_review_credit():
    payload = load_safeguards()
    without = {**payload, "safeguards": [s for s in payload["safeguards"] if s["safeguard_id"] not in CASES]}
    before, after = coverage_by_framework(without), coverage_by_framework(payload)
    assert after["covered"] == before["covered"] + 5
    assert after["proposed"] == before["proposed"] + 5
    assert after["reviewed"] == before["reviewed"]
    assert after["frameworks"]["nist-csf-2.0"]["uncovered"] == 0


@pytest.mark.parametrize("sid", CASES)
@pytest.mark.parametrize("case", ["pass", "failed", "unknown", "observed", "unbound", "wrong_type", "stale"])
def test_each_outcome_requires_fresh_typed_bound_evidence_and_separate_review(sid, case):
    entry = next(s for s in load_safeguards()["safeguards"] if s["safeguard_id"] == sid)
    control_id = entry["satisfies"][0]["control_id"]
    controls = {control_id: load_control_catalog()[control_id]}
    payload = {"review_log_verified": True, "safeguards": [entry]}
    row = normalized(
        asset_type="service",
        bindings=[] if case == "unbound" else [sid],
        status=case if case in {"failed", "unknown", "observed"} else "pass",
        control_ids=[control_id],
        evidence_types=["unrelated"] if case == "wrong_type" else [CASES[sid][1]],
    )
    if case == "stale":
        row.update(event_time="2000-01-01T00:00:00Z", evidence_collected_at="2000-01-01T00:00:00Z")
    result = evaluate_safeguards([row], payload, controls)
    expected = {"pass": "pass", "failed": "fail", "wrong_type": "stale", "stale": "stale"}.get(case, "not_evaluated")
    assert result["safeguards"][0]["status"] == expected
    assert result["requirements"][0]["status"] != "pass"
    # Synthetic review overlay tests behavior; it never edits shipped review state.
    reviewed = deepcopy(payload)
    reviewed["safeguards"][0]["satisfies"][0]["effective_review_state"] = "org_reviewed"
    assert evaluate_safeguards([row], reviewed, controls)["requirements"][0]["status"] == expected


def test_imported_assessments_remain_proposed_until_an_attributable_review(tmp_path):
    from security_lakehouse.io import read_json, write_jsonl
    from security_lakehouse.mapping_review import record_decisions
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import event

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(
        raw,
        [
            {
                **event(),
                "event_id": sid,
                "event_type": kind,
                "entity": {"asset_id": "incident-service", "asset_type": "service"},
                "controls": ["NIST-CSF-" + outcome],
                "safeguard_ids": [sid],
            }
            for sid, (outcome, kind) in CASES.items()
        ],
    )
    run_pipeline(raw, lake, tenant_id="audit")
    data = read_json(lake / "gold/ccf_assessment.json")
    assert {row["status"] for row in data["safeguards"] if row["safeguard_id"] in CASES} == {"pass"}
    ids = {"NIST-CSF-" + outcome for outcome, _ in CASES.values()}
    assert not any(row["status"] == "pass" for row in data["requirements"] if row["control_id"] in ids)
    record_decisions(
        lake,
        items=[
            {
                "safeguard_id": "SG-RECOVERYCOMPLETION-001",
                "framework_id": "nist-csf-2.0",
                "control_id": "NIST-CSF-RC.RP-06",
            }
        ],
        decision="approve",
        reviewer="synthetic-test-reviewer",
        rationale="Synthetic review transition; not a shipped approval.",
    )
    run_pipeline(raw, lake, tenant_id="audit")
    after = read_json(lake / "gold/ccf_assessment.json")
    assert {
        row["control_id"] for row in after["requirements"] if row["control_id"] in ids and row["status"] == "pass"
    } == {"NIST-CSF-RC.RP-06"}
