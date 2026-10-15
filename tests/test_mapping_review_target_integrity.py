"""Decisions require a unique mapping whose target exists in the catalog."""

import copy

import pytest

from security_lakehouse import mapping_review
from security_lakehouse.ccf_contracts import REVIEW_BASIS_VERSION, review_basis


def _payload():
    return {
        "safeguards": [
            {
                "safeguard_id": "SG-TARGET",
                "satisfies": [
                    {"control_id": "SOC2-CC6.1", "framework_id": "soc2", "review_status": "proposed"},
                    {"control_id": "SOC2-CC7.2", "framework_id": "soc2", "review_status": "proposed"},
                ],
            }
        ]
    }


def _items(payload):
    entry = payload["safeguards"][0]
    return [
        {"safeguard_id": entry["safeguard_id"], "control_id": m["control_id"], "framework_id": m["framework_id"]}
        for m in entry["satisfies"][:2]
    ]


def _record(lake, payload, decision="approve"):
    return mapping_review.record_decisions(
        lake,
        items=_items(payload),
        decision=decision,
        reviewer="reviewer@example.test",
        rationale="Synthetic target integrity contract.",
        payload=payload,
    )


def _mutate(payload, mutation):
    entry = payload["safeguards"][0]
    if mutation == "duplicate_member":
        entry["satisfies"].append(copy.deepcopy(entry["satisfies"][1]))
    elif mutation == "duplicate_entry":
        payload["safeguards"].append(copy.deepcopy(entry))
    elif mutation == "unknown_control":
        entry["satisfies"][1]["control_id"] = "MISSING-CONTROL"
    elif mutation == "wrong_framework":
        entry["satisfies"][1]["framework_id"] = "iso27001"


@pytest.mark.parametrize("mutation", ["duplicate_member", "duplicate_entry", "unknown_control", "wrong_framework"])
@pytest.mark.parametrize("decision", ["approve", "reject", "needs_changes"])
def test_invalid_target_rejects_whole_batch_without_changing_history(tmp_path, mutation, decision):
    payload = _payload()
    _record(tmp_path, payload)
    log, tip = mapping_review.review_log_path(tmp_path), mapping_review.review_tip_path(tmp_path)
    before = (log.read_bytes(), tip.read_bytes())
    _mutate(payload, mutation)
    with pytest.raises(mapping_review.MappingReviewError):
        _record(tmp_path, payload, decision)
    assert (log.read_bytes(), tip.read_bytes()) == before
    assert mapping_review.verify_review_log(tmp_path)["ok"] is True


@pytest.mark.parametrize("mutation", ["duplicate_member", "duplicate_entry", "unknown_control", "wrong_framework"])
def test_legacy_approval_cannot_verify_an_invalid_target(tmp_path, monkeypatch, mutation):
    payload = _payload()
    _mutate(payload, mutation)
    entry = payload["safeguards"][0]
    member = entry["satisfies"][1]
    # Model a historical record issued before catalog target validation existed.
    control = mapping_review.load_control_catalog().get(member["control_id"], {})
    record = {
        "decision_id": "historical",
        "decision": "approve",
        "review_basis_version": REVIEW_BASIS_VERSION,
        "review_basis_sha256": review_basis(entry, member, control),
    }
    key = (entry["safeguard_id"], member["control_id"])
    monkeypatch.setattr(mapping_review, "_verified_latest_decisions", lambda _: (True, {key: record}))
    before = copy.deepcopy(payload)
    effective = mapping_review.effective_safeguards(tmp_path, payload=payload)
    for safeguard in effective["safeguards"]:
        for row in safeguard["satisfies"]:
            if row["control_id"] == member["control_id"]:
                assert row["effective_review_state"] == "proposed"
                assert row["org_review"]["basis_verified"] is False
                assert row["org_review"]["decision_id"] == "historical"
    assert payload == before


def test_queue_exposes_the_exact_shipped_semantic_basis(tmp_path):
    payload = _payload()
    items = mapping_review.list_review_items(tmp_path, payload=payload)
    catalog = mapping_review.load_control_catalog()
    for item, member in zip(items, payload["safeguards"][0]["satisfies"], strict=True):
        assert item["review_basis_sha256"] == review_basis(
            payload["safeguards"][0], member, catalog[member["control_id"]]
        )


@pytest.mark.parametrize("decision", ["approve", "reject", "needs_changes"])
def test_changed_basis_between_inspection_and_decision_rejects_the_whole_batch(tmp_path, decision):
    payload = _payload()
    items = _items(payload)
    catalog = mapping_review.load_control_catalog()
    for item, member in zip(items, payload["safeguards"][0]["satisfies"], strict=True):
        item["review_basis_sha256"] = review_basis(payload["safeguards"][0], member, catalog[member["control_id"]])
    _record(tmp_path, payload)
    log, tip = mapping_review.review_log_path(tmp_path), mapping_review.review_tip_path(tmp_path)
    before = log.read_bytes(), tip.read_bytes()
    payload["safeguards"][0]["satisfies"][1]["mapping_source"] = {"locator": "changed source obligation"}
    with pytest.raises(mapping_review.MappingReviewError, match="changed.*refresh"):
        mapping_review.record_decisions(
            tmp_path,
            items=items,
            decision=decision,
            rationale="Reviewed the earlier definitions.",
            reviewer="synthetic-reviewer",
            payload=payload,
        )
    assert (log.read_bytes(), tip.read_bytes()) == before


def test_basis_from_queue_remains_valid_after_an_org_decision_overlay(tmp_path):
    payload = _payload()
    _record(tmp_path, payload)
    items = mapping_review.list_review_items(tmp_path, payload=payload)
    rows = mapping_review.record_decisions(
        tmp_path,
        items=items,
        decision="needs_changes",
        rationale="Synthetic follow-up review.",
        reviewer="synthetic-reviewer",
        payload=payload,
    )
    assert [row["review_basis_sha256"] for row in rows] == [item["review_basis_sha256"] for item in items]


def test_another_reviewers_decision_cannot_be_silently_overwritten(tmp_path):
    payload = _payload()
    items = [{**item, "expected_decision_id": None} for item in _items(payload)]
    _record(tmp_path, payload, "reject")
    before = mapping_review.review_log_path(tmp_path).read_bytes()
    with pytest.raises(mapping_review.MappingReviewError, match="history changed.*refresh"):
        mapping_review.record_decisions(
            tmp_path,
            items=items,
            decision="approve",
            rationale="Inspected before the other review.",
            reviewer="second-synthetic-reviewer",
            payload=payload,
        )
    assert mapping_review.review_log_path(tmp_path).read_bytes() == before
