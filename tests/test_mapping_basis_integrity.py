"""Review decisions bind both ends of a mapping without rewriting its history."""

import copy

import pytest

from security_lakehouse.mapping_review import effective_safeguards, record_decisions
from security_lakehouse.safeguards import effective_review_state, load_safeguards, validate_safeguards


def approval(tmp_path, decision="approve"):
    payload = load_safeguards()
    entry = payload["safeguards"][0]
    member = next(m for m in entry["satisfies"] if effective_review_state(m) == "proposed")
    record = record_decisions(
        tmp_path,
        items=[
            {
                "safeguard_id": entry["safeguard_id"],
                "control_id": member["control_id"],
                "framework_id": member["framework_id"],
            }
        ],
        decision=decision,
        rationale="Synthetic review contract.",
        reviewer="reviewer@example.test",
        payload=payload,
    )[0]
    return payload, member["control_id"], record


def state(tmp_path, payload, cid):
    entry = effective_safeguards(tmp_path, payload=payload)["safeguards"][0]
    return next(m for m in entry["satisfies"] if m["control_id"] == cid)


@pytest.mark.parametrize(
    "field,value",
    [
        ("evidence_requirement", "Different evidence"),
        ("evaluation_rule", "fail_when_missing_evidence"),
        ("asset_types", ["repository"]),
        ("objective", "Different obligation"),
    ],
)
def test_semantic_change_requires_new_org_review(tmp_path, field, value):
    payload, cid, record = approval(tmp_path)
    assert state(tmp_path, payload, cid)["effective_review_state"] == "org_reviewed"
    payload["safeguards"][0][field] = value
    current = state(tmp_path, payload, cid)
    assert current["effective_review_state"] == "proposed"
    assert current["org_review"]["decision_id"] == record["decision_id"]
    assert current["org_review"]["basis_verified"] is False


def test_title_edit_does_not_invalidate_semantic_approval(tmp_path):
    payload, cid, _ = approval(tmp_path)
    payload["safeguards"][0]["title"] = "Corrected display title"
    assert state(tmp_path, payload, cid)["effective_review_state"] == "org_reviewed"


@pytest.mark.parametrize("decision,expected", [("reject", "rejected"), ("needs_changes", "needs_changes")])
def test_adverse_decisions_survive_definition_changes(tmp_path, decision, expected):
    payload, cid, _ = approval(tmp_path, decision)
    payload["safeguards"][0]["satisfies"][1]["mapping_basis"] = "changed"
    payload["safeguards"][0]["objective"] = "Changed obligation"
    assert state(tmp_path, payload, cid)["effective_review_state"] == expected


@pytest.mark.parametrize(
    "mutation", ["framework", "duplicate", "rule", "asset_types", "required_types", "review", "version"]
)
def test_catalog_publication_rejects_ambiguous_contracts(mutation):
    payload = copy.deepcopy(load_safeguards())
    entry = payload["safeguards"][0]
    member = next(m for m in entry["satisfies"] if m["role"] != "primary")
    if mutation == "framework":
        member["framework_id"] = "incorrect-framework"
    if mutation == "duplicate":
        entry["satisfies"].append(copy.deepcopy(member))
    if mutation == "rule":
        entry["evaluation_rule"] = "unknown-rule"
    if mutation == "asset_types":
        entry["asset_types"] = "iam_role"
    if mutation == "required_types":
        entry["required_evidence_types"] = "identity.access_review"
    if mutation == "review":
        member.pop("review_status")
    if mutation == "version":
        member.pop("control_version")
    assert validate_safeguards(payload)


def test_legacy_approval_stays_visible_but_cannot_attest_a_current_basis(tmp_path, monkeypatch):
    from security_lakehouse import mapping_review

    payload, cid, record = approval(tmp_path)
    legacy = {key: value for key, value in record.items() if not key.startswith("review_basis_")}
    monkeypatch.setattr(
        mapping_review,
        "_verified_latest_decisions",
        lambda lake: (True, {(payload["safeguards"][0]["safeguard_id"], cid): legacy}),
    )
    current = state(tmp_path, payload, cid)
    assert current["effective_review_state"] == "proposed"
    assert current["org_review"]["basis_verified"] is False
    assert current["org_review"]["decision_id"] == record["decision_id"]


@pytest.mark.parametrize("mutation", ["entries", "entry", "identifier", "family", "member", "control", "role", "state"])
def test_catalog_validator_reports_malformed_shapes_without_crashing(mutation):
    payload = copy.deepcopy(load_safeguards())
    entry = payload["safeguards"][0]
    member = entry["satisfies"][0]
    if mutation == "entries":
        payload["safeguards"] = None
    if mutation == "entry":
        payload["safeguards"] = [None]
    if mutation == "identifier":
        entry["safeguard_id"] = ["invalid"]
    if mutation == "family":
        entry["risk_domain"] = ["invalid"]
    if mutation == "member":
        entry["satisfies"] = [None]
    if mutation == "control":
        member["control_id"] = ["invalid"]
    if mutation == "role":
        member["role"] = ["invalid"]
    if mutation == "state":
        member["review_status"] = ["invalid"]
    assert validate_safeguards(payload)
