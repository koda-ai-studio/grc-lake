"""A second review needs current reviewed mappings without a new decision."""

import json
from copy import deepcopy

import pytest

from security_lakehouse.cli import main
from security_lakehouse.io import canonical_sha256
from security_lakehouse.mapping_review import list_decisions, list_review_items
from security_lakehouse.mapping_review_packet import build_review_packet
from security_lakehouse.safeguards import ATTESTABLE_STATES, load_safeguards


def reviewed_target():
    return next(
        item for item in list_review_items(None, framework_id="soc2") if item["review_state"] in ATTESTABLE_STATES
    )


def test_second_review_packet_preserves_attribution_without_granting_credit(tmp_path):
    target = reviewed_target()
    payload = load_safeguards()
    before = deepcopy(payload)
    default = build_review_packet(payload=payload)
    packet = build_review_packet(
        tmp_path,
        payload=payload,
        reviewed_only=True,
        framework_id="soc2",
        control_ids=[target["control_id"]],
        safeguard_ids=[target["safeguard_id"]],
    )
    assert packet["review_mode"] == "second_review"
    assert packet["summary"]["additional_coverage_candidates"] == 0
    assert packet["summary"]["reviewed_requirements"] == default["summary"]["reviewed_requirements"]
    candidates = [c for b in packet["batches"] for r in b["requirements"] for c in r["candidates"]]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["review_state"] in ATTESTABLE_STATES
    assert candidate["review_basis_sha256"] == target["review_basis_sha256"]
    assert candidate["maintainer_review"]["reviewed_by"]
    assert candidate["maintainer_review"]["maintainer_review_ref"].startswith("controls/reviews/")
    assert candidate["decision"] is candidate["reviewer"] is candidate["rationale"] is None
    assert list_decisions(tmp_path) == []
    assert list(tmp_path.iterdir()) == []
    assert payload == before
    assert packet["packet_sha256"] == canonical_sha256({k: v for k, v in packet.items() if k != "packet_sha256"})


def test_second_review_cli_selects_only_reviewed_mappings(tmp_path):
    target = reviewed_target()
    out = tmp_path / "review.json"
    assert (
        main(
            [
                "frameworks",
                "review",
                "packet",
                "--reviewed-only",
                "--framework",
                "soc2",
                "--control",
                target["control_id"],
                "--out",
                str(out),
            ]
        )
        == 0
    )
    packet = json.loads(out.read_text())
    assert all(
        c["review_state"] in ATTESTABLE_STATES
        for b in packet["batches"]
        for r in b["requirements"]
        for c in r["candidates"]
    )


def test_second_review_rejects_proposed_scope_before_writing(tmp_path):
    out = tmp_path / "review.json"
    assert main(["frameworks", "review", "packet", "--reviewed-only", "--control", "SOC2-C1.1", "--out", str(out)]) == 1
    assert not out.exists()


def test_default_packet_still_rejects_reviewed_requirement():
    with pytest.raises(ValueError, match="not pending"):
        build_review_packet(control_ids=[reviewed_target()["control_id"]])


@pytest.mark.parametrize("decision", ["approve", "needs_changes", "reject"])
def test_second_review_respects_current_organization_decision(tmp_path, decision):
    from security_lakehouse.mapping_review import record_decisions

    target = reviewed_target()
    record_decisions(
        tmp_path,
        items=[target],
        decision=decision,
        rationale="Synthetic second-review regression.",
        reviewer="reviewer@example.test",
    )
    before = list_decisions(tmp_path)
    options = dict(reviewed_only=True, control_ids=[target["control_id"]], safeguard_ids=[target["safeguard_id"]])
    if decision == "approve":
        packet = build_review_packet(tmp_path, **options)
        candidate = packet["batches"][0]["requirements"][0]["candidates"][0]
        assert candidate["latest_decision"]["reviewer"] == "reviewer@example.test"
        assert candidate["expected_decision_id"] == before[0]["decision_id"]
        assert candidate["reviewer"] is candidate["decision"] is None
    else:
        with pytest.raises(ValueError, match="not reviewed"):
            build_review_packet(tmp_path, **options)
    assert list_decisions(tmp_path) == before
