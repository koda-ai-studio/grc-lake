"""A declared safeguard binding cannot replace its evidence-type contract."""

from copy import deepcopy

import pytest

from security_lakehouse.ccf_evaluation import evaluate_safeguards
from test_ccf_operational_assessment import normalized


def contract(required=("fixture.access_review",)):
    return {
        "review_log_verified": True,
        "safeguards": [
            {
                "safeguard_id": "SG-0",
                "title": "Synthetic access assessment",
                "asset_types": ["iam_role"],
                "required_evidence_types": list(required),
                "evaluation_rule": "fail_when_open_violation",
                "satisfies": [{"control_id": "REQ", "framework_id": "fixture", "review_status": "reviewed"}],
            }
        ],
    }


def row(status="pass", kind="fixture.access_review", event_id="review"):
    return normalized(status=status, event_id=event_id, event_type=kind, evidence_types=[kind])


def assess(rows, payload=None):
    return evaluate_safeguards(rows, payload or contract(), {"REQ": {"framework_id": "fixture"}})


@pytest.mark.parametrize("status", ["pass", "open", "not_evaluated", "observed"])
@pytest.mark.parametrize("missing", [False, True])
def test_missing_evidence_contract_never_asserts_a_verdict(status, missing):
    payload = contract(())
    if missing:
        payload["safeguards"][0].pop("required_evidence_types")
    result = assess([row(status)], payload)
    assert result["safeguards"][0]["status"] == "not_evaluated"
    assert result["requirements"][0]["status"] == "not_evaluated"
    assert result["asset_results"][0]["reasons"]


@pytest.mark.parametrize("status", ["pass", "open"])
def test_unrelated_evidence_cannot_assert_a_safeguard_result(status):
    result = assess([row(status, "fixture.unrelated")])
    assert result["safeguards"][0]["status"] == "not_evaluated"
    assert result["requirements"][0]["status"] == "not_evaluated"


@pytest.mark.parametrize(
    "status,expected",
    [("pass", "pass"), ("open", "fail"), ("not_evaluated", "not_evaluated"), ("observed", "not_evaluated")],
)
@pytest.mark.parametrize("unrelated", ["pass", "open"])
def test_unrelated_rows_do_not_override_the_matching_evidence(status, expected, unrelated):
    rows = [row(status), row(unrelated, "fixture.unrelated", "unrelated")]
    original = deepcopy(rows)
    result = assess(rows)
    assert result["safeguards"][0]["status"] == expected
    assert result["requirements"][0]["status"] == expected
    assert result["asset_results"][0]["event_ids"] == ["review", "unrelated"]
    assert rows == original


def test_matching_evidence_still_respects_asset_scope_and_freshness():
    wrong = {**row(), "asset_type": "unrelated_asset"}
    assert assess([wrong])["safeguards"][0]["status"] == "not_evaluated"
    old = {**row(), "event_time": "2000-01-01T00:00:00Z", "evidence_collected_at": "2000-01-01T00:00:00Z"}
    assert assess([old])["safeguards"][0]["status"] == "stale"


def test_missing_required_type_blocks_pass_without_masking_a_matching_failure():
    payload = contract(("fixture.access_review", "fixture.approval"))
    assert assess([row()], payload)["safeguards"][0]["status"] == "not_evaluated"
    assert assess([row("open")], payload)["safeguards"][0]["status"] == "fail"


def test_pipeline_keeps_technical_results_but_refuses_untyped_safeguard(tmp_path, monkeypatch, capsys):
    from security_lakehouse import api_v1, mapping_review
    from security_lakehouse.cli import main
    from security_lakehouse.investigation_graph import investigation_graph
    from security_lakehouse.io import read_json, read_jsonl, write_jsonl
    from security_lakehouse.oscal import build_assessment_results
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import complete_events

    payload = contract(())
    payload["safeguards"][0]["satisfies"] = [
        {"control_id": "SOC2-CC6.1", "framework_id": "soc2", "review_status": "reviewed"}
    ]
    monkeypatch.setattr(mapping_review, "effective_safeguards", lambda _: deepcopy(payload))
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, [dict(item, safeguard_ids=["SG-0"]) for item in complete_events()])
    run_pipeline(raw, lake, tenant_id="audit")
    ccf = read_json(lake / "gold/ccf_assessment.json")
    assert ccf["safeguards"][0]["status"] == "not_evaluated"
    assert next(r for r in ccf["requirements"] if r["control_id"] == "SOC2-CC6.1")["status"] == "not_evaluated"
    assert read_jsonl(lake / "gold/control_posture.jsonl")[0]["status"] == "pass"
    code, body = api_v1.handle_get("/api/v1/ccf/assessment", {}, lake)
    assert code == 200
    assert body["data"]["safeguards"] == ccf["safeguards"]
    graph = investigation_graph(lake, root="control:SOC2-CC6.1")
    control = next(node for node in graph["nodes"] if node["id"] == "control:SOC2-CC6.1")
    assert control["ccf_status"] == "not_evaluated"
    assert control["status"] == "pass"
    finding = build_assessment_results(lake)["assessment-results"]["results"][0]["findings"][0]
    assert finding["target"]["status"]["state"] == "not-satisfied"
    assert main(["assessment", "status", "--lake", str(lake), "--format", "summary"]) == 0
    assert "0 attested, 0 failing" in capsys.readouterr().out


def test_evaluator_revision_refreshes_incremental_results_without_rewriting_history(tmp_path, monkeypatch):
    from security_lakehouse import ccf_evaluation, pipeline
    from security_lakehouse.assessment import load_snapshot, write_assessment_snapshot
    from security_lakehouse.generations import active_generation
    from security_lakehouse.io import write_jsonl
    from test_assurance_truth import event

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, [event()])
    with monkeypatch.context() as old:
        old.setattr(ccf_evaluation, "EVALUATION_VERSION", "fixture.previous", raising=False)
        pipeline.run_pipeline(raw, lake, tenant_id="audit")
    previous = active_generation(lake)
    before = (previous / "gold/ccf_assessment.json").read_bytes()
    snapshot = write_assessment_snapshot(lake)
    frozen = load_snapshot(lake, snapshot.stem)
    pipeline.run_pipeline_incremental(raw, lake, tenant_id="audit")
    assert active_generation(lake) != previous
    assert (previous / "gold/ccf_assessment.json").read_bytes() == before
    assert load_snapshot(lake, snapshot.stem) == frozen


def test_provider_framework_uses_only_matching_evidence_from_its_own_source():
    payload = contract()
    payload["safeguards"][0]["satisfies"] = [
        {"control_id": key, "framework_id": key, "review_status": "reviewed"} for key in ("AWS", "GCP", "ALL")
    ]
    rows = [dict(row(), source="aws"), dict(row("open", event_id="other"), source="gcp")]
    result = evaluate_safeguards(
        rows,
        payload,
        {key: {"framework_id": key} for key in ("AWS", "GCP", "ALL")},
        provider_sources={"AWS": ["aws"], "GCP": ["gcp"]},
    )
    assert {item["control_id"]: item["status"] for item in result["requirements"]} == {
        "AWS": "pass",
        "GCP": "fail",
        "ALL": "fail",
    }
