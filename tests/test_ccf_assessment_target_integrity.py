"""Invalid CCF identities must not publish assessment verdicts."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from security_lakehouse.ccf_evaluation import evaluate_safeguards
from test_ccf_operational_assessment import normalized


def payload():
    return {
        "review_log_verified": True,
        "safeguards": [
            {
                "safeguard_id": "SG-0",
                "title": "Fixture",
                "asset_types": ["iam_role"],
                "evaluation_rule": "fail_when_open_violation",
                "required_evidence_types": ["fixture.assessment"],
                "satisfies": [{"control_id": "REQ", "framework_id": "alpha", "review_status": "reviewed"}],
            }
        ],
    }


def mutate(data, kind):
    entry = data["safeguards"][0]
    if kind == "wrong_framework":
        entry["satisfies"][0]["framework_id"] = "beta"
    elif kind == "duplicate_mapping":
        entry["satisfies"].append(deepcopy(entry["satisfies"][0]))
    else:
        data["safeguards"].append(deepcopy(entry))


@pytest.mark.parametrize("kind", ["wrong_framework", "duplicate_mapping", "duplicate_safeguard"])
def test_invalid_identity_cannot_publish_a_pass(kind):
    data = payload()
    mutate(data, kind)
    before = deepcopy(data)
    with pytest.raises(ValueError, match="CCF"):
        evaluate_safeguards([normalized()], data, {"REQ": {"framework_id": "alpha"}}, now=datetime.now(UTC))
    assert data == before


def test_valid_and_legacy_framework_identity_keep_explicit_verdicts():
    for legacy in (False, True):
        data = payload()
        if legacy:
            del data["safeguards"][0]["satisfies"][0]["framework_id"]
        result = evaluate_safeguards([normalized()], data, {"REQ": {"framework_id": "alpha"}})
        assert result["requirements"][0]["status"] == "pass"
        assert result["requirements"][0]["reviewed_safeguard_ids"] == ["SG-0"]


def test_out_of_scope_controls_do_not_enter_assessment():
    result = evaluate_safeguards([normalized()], payload(), {})
    assert result["requirements"] == []


@pytest.mark.parametrize("value", [None, "", 12, ["REQ"]])
def test_mapping_identity_is_a_nonempty_string(value):
    data = payload()
    data["safeguards"][0]["satisfies"][0]["control_id"] = value
    with pytest.raises(ValueError, match="CCF.*control_id"):
        evaluate_safeguards([], data, {})


@pytest.mark.parametrize("kind", ["wrong_framework", "duplicate_mapping", "duplicate_safeguard"])
def test_invalid_mapping_preserves_previous_generation(tmp_path, monkeypatch, kind):
    from security_lakehouse import mapping_review
    from security_lakehouse.generations import active_generation
    from security_lakehouse.io import write_jsonl
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import event

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, [event()])
    run_pipeline(raw, lake, tenant_id="audit")
    before = active_generation(lake)
    data = mapping_review.effective_safeguards(lake)
    mutate(data, kind)
    monkeypatch.setattr(mapping_review, "effective_safeguards", lambda _: data)
    with pytest.raises(ValueError, match="CCF"):
        run_pipeline(raw, lake, tenant_id="audit")
    assert active_generation(lake) == before
