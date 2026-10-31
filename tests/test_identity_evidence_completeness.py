"""Identity evidence must cover every scoped asset and assessment window."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.evidence_freshness import (
    build_evidence_freshness,
    current_evidence_is_stale,
    summarize_control_freshness,
)
from test_ccf_operational_assessment import normalized
from test_control_assurance import case, evaluate

KINDS = ["identity.mfa", "identity.privileged_access", "identity.access_review"]


def population(*, split=False, tenants=False):
    return [
        normalized(
            asset="principal" if tenants else f"principal-{index if split else 0}",
            tenant_id=f"tenant-{index if tenants else 0}",
            event_id=f"event-{index}",
            evidence_types=[kind],
        )
        for index, kind in enumerate(KINDS)
    ]


@pytest.mark.parametrize("tenants", [False, True])
def test_identity_requirements_cannot_borrow_types_from_another_scope(tenants):
    rows = population(split=True, tenants=tenants)
    records = build_evidence_freshness(rows)
    assert current_evidence_is_stale(records, required_types=KINDS)
    summary = summarize_control_freshness(rows, required_evidence_types=KINDS)
    assert summary["status"] != "fresh"
    assert summary["missing_evidence_types"] == sorted(KINDS)
    payload = {
        "review_log_verified": True,
        "safeguards": [
            {
                "safeguard_id": "SG-0",
                "title": "Identity",
                "asset_types": ["iam_role"],
                "required_evidence_types": KINDS,
                "evaluation_rule": "fail_when_open_violation",
                "satisfies": [{"control_id": "REQ", "effective_review_state": "maintainer_reviewed"}],
            }
        ],
    }
    result = evaluate_safeguards(
        rows, payload, {"REQ": {"framework_id": "fixture", "required_evidence_types": KINDS}}, now=datetime.now(UTC)
    )
    assert result["requirements"][0]["status"] == "not_evaluated"


def test_identity_complete_types_can_arrive_from_different_sources():
    rows = population()
    for index, row in enumerate(rows):
        row["source"] = f"source-{index}"
    assert not current_evidence_is_stale(build_evidence_freshness(rows), required_types=KINDS)
    assert summarize_control_freshness(rows, required_evidence_types=KINDS)["status"] == "fresh"


@pytest.mark.parametrize("missing", ["type", "window", "asset", "tenant", "observed", "future", "unbound"])
def test_identity_workpaper_needs_each_type_in_every_asset_window(tmp_path, missing):
    plan, events = case(tmp_path)
    plan["controls"][0]["required_evidence_types"] = KINDS
    rows = [events[0]]
    for original in events[1:]:
        for index, kind in enumerate(KINDS):
            row = deepcopy(original)
            row["event_id"] += f"-{index}"
            row["evidence"]["evidence_id"] = row["event_id"]
            row["event_type"] = kind
            rows.append(row)
    target = rows[-1]
    if missing == "type":
        target["event_type"] = "unrelated"
    if missing == "window":
        rows.pop()
    if missing == "asset":
        target["entity"]["asset_id"] = "other-principal"
    if missing == "tenant":
        target["tenant_id"] = "other-source-tenant"
    if missing == "observed":
        target["status"] = "observed"
    if missing == "future":
        target["evidence"]["collected_at"] = "2027-01-01T00:00:00Z"
    if missing == "unbound":
        target["safeguard_ids"] = []
    result = evaluate(tmp_path, plan, rows)["controls"][0]["operating"]
    assert result["status"] == "insufficient_evidence"
    assert any(KINDS[-1] in gap["missing_evidence_types"] for gap in result["gaps"])


def test_identity_workpaper_samples_each_type_and_retains_failures(tmp_path):
    plan, events = case(tmp_path)
    plan["controls"][0]["required_evidence_types"] = KINDS
    rows = [events[0]]
    for original in events[1:]:
        for index, kind in enumerate(KINDS):
            row = deepcopy(original)
            row["event_id"] += f"-{index}"
            row["evidence"]["evidence_id"] = row["event_id"]
            row["event_type"] = kind
            rows.append(row)
    result = evaluate(tmp_path, plan, rows)["controls"][0]["operating"]
    assert result["status"] == "sample_pass"
    assert len(result["samples"]) == 6
    assert all("evidence_types" in row for row in result["samples"])
    rows[-1]["status"] = "fail"
    failed = evaluate(tmp_path, plan, rows)["controls"][0]["operating"]
    assert failed["status"] == "sample_fail"
    assert rows[-1]["event_id"] in failed["deviation_event_ids"]


@pytest.mark.parametrize("kinds", [[], ["identity.mfa", "identity.mfa"], [" "], "identity.mfa", [True], ["x"] * 21])
def test_malformed_type_obligations_are_rejected(tmp_path, kinds):
    from security_lakehouse.control_assurance import validate_plan

    plan, _ = case(tmp_path)
    plan["controls"][0]["required_evidence_types"] = kinds
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_incomplete_identity_scope_stays_incomplete_across_api_snapshot_and_oscal(tmp_path):
    from security_lakehouse.api_v1 import handle_get
    from security_lakehouse.assessment import write_assessment_snapshot
    from security_lakehouse.io import read_jsonl, write_jsonl
    from security_lakehouse.oscal import build_assessment_results
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import complete_events

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    rows = complete_events()
    for index, row in enumerate(rows):
        row["entity"] = {**row["entity"], "asset_id": f"principal-{index}"}
        row["safeguard_ids"] = ["SG-IDENTITY-001"]
    write_jsonl(raw, rows)
    run_pipeline(raw, lake, tenant_id="audit")
    assert read_jsonl(lake / "gold/control_posture.jsonl")[0]["status"] == "stale"
    code, body = handle_get("/api/v1/control-tests", {}, lake)
    assert code == 200
    test = next(row for row in body["data"] if row["control_id"] == "SOC2-CC6.1")
    assert test["result"] == "needs_evidence"
    assert set(test["missing_evidence_types"]) == set(test["required_evidence_types"])
    assert test["confidence_inputs"]["freshness"] == 0
    code, body = handle_get("/api/v1/ccf/assessment", {}, lake)
    assert code == 200
    assert next(row for row in body["data"]["requirements"] if row["control_id"] == "SOC2-CC6.1")["status"] != "pass"
    snapshot = write_assessment_snapshot(lake)
    before = build_assessment_results(lake, snapshot_id=snapshot.stem)
    finding = before["assessment-results"]["results"][0]["findings"][0]
    assert finding["target"]["status"]["state"] == "not-satisfied"
    write_jsonl(raw, complete_events())
    run_pipeline(raw, lake, tenant_id="audit")
    assert read_jsonl(lake / "gold/control_posture.jsonl")[0]["status"] == "pass"
    assert build_assessment_results(lake, snapshot_id=snapshot.stem) == before


def test_published_identity_example_exposes_the_missing_review(tmp_path):
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "examples/control-assurance"
    plan = json.loads((root / "identity-plan.json").read_text())
    rows = [json.loads(line) for line in (root / "identity-events.jsonl").read_text().splitlines()]
    result = evaluate(tmp_path, plan, rows)["controls"][0]["operating"]
    assert result["status"] == "insufficient_evidence"
    assert result["expected_asset_windows"] == 4
    assert len(result["gaps"]) == 1
    assert result["gaps"][0]["asset_id"] == "principal-b"
    assert result["gaps"][0]["missing_evidence_types"] == ["identity.access_review"]


def test_plan_cannot_remove_pinned_safeguard_evidence_types(tmp_path, monkeypatch):
    from security_lakehouse import mapping_review

    original = mapping_review.effective_safeguards

    def typed_catalog(*args, **kwargs):
        payload = original(*args, **kwargs)
        identity = next(row for row in payload["safeguards"] if row["safeguard_id"] == "SG-IDENTITY-001")
        identity["required_evidence_types"] = ["identity.privileged_access"]
        return payload

    monkeypatch.setattr(mapping_review, "effective_safeguards", typed_catalog)
    plan, rows = case(tmp_path)
    plan["controls"][0]["required_evidence_types"] = ["identity.mfa"]
    for row in rows[1:]:
        row["event_type"] = "identity.mfa"
    result = evaluate(tmp_path, plan, rows)["controls"][0]["operating"]
    assert result["required_evidence_types"] == ["identity.mfa", "identity.privileged_access"]
    assert result["status"] == "insufficient_evidence"
    assert all(gap["missing_evidence_types"] == ["identity.privileged_access"] for gap in result["gaps"])
