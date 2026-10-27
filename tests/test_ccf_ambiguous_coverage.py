"""Ambiguous mapping identities must not earn coverage or export review credit."""

from copy import deepcopy

import pytest

from security_lakehouse.oscal import build_component_definition
from security_lakehouse.safeguards import (
    coverage_by_category,
    coverage_by_family,
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
)


def ambiguous_payload(kind, role="primary"):
    entry = deepcopy(load_safeguards()["safeguards"][0])
    entry["satisfies"] = [{**entry["satisfies"][0], "role": role, "review_status": "reviewed"}]
    payload = {"safeguards": [entry], "review_log_verified": True}
    if kind == "mapping":
        entry["satisfies"].append({**entry["satisfies"][0], "review_status": "proposed"})
    else:
        payload["safeguards"].append(deepcopy(entry))
    return payload


@pytest.mark.parametrize("kind", ["mapping", "safeguard"])
@pytest.mark.parametrize("role", ["primary", "supporting"])
def test_ambiguous_identity_earns_no_requirement_link_or_context_credit(kind, role):
    payload = ambiguous_payload(kind, role)
    before = deepcopy(payload)
    result = coverage_by_framework(payload)
    assert result["covered"] == result["reviewed"] == 0
    assert result["maintainer_reviewed_mappings"] == result["contextual_mappings"] == 0
    for rows in (coverage_by_family(payload), coverage_by_category(payload)):
        assert sum(row["mapping_count"] for row in rows) == 0
        assert sum(row["reviewed_mapping_count"] for row in rows) == 0
    assert safeguards_by_requirement(payload, reviewed_only=True) == {}
    assert payload == before


@pytest.mark.parametrize("kind", ["mapping", "safeguard"])
def test_ambiguous_review_cannot_promote_an_independent_valid_proposal(kind):
    payload = ambiguous_payload(kind)
    valid = deepcopy(payload["safeguards"][0])
    valid["safeguard_id"] = "SG-VALID"
    valid["satisfies"] = [{**valid["satisfies"][0], "review_status": "proposed"}]
    payload["safeguards"].append(valid)
    result = coverage_by_framework(payload)
    assert result["covered"] == result["proposed"] == 1
    assert result["reviewed"] == result["maintainer_reviewed_mappings"] == 0
    assert safeguards_by_requirement(payload) == {valid["satisfies"][0]["control_id"]: ["SG-VALID"]}


@pytest.mark.parametrize("kind", ["mapping", "safeguard"])
def test_ambiguous_mapping_cannot_export_an_implemented_requirement(kind):
    result = build_component_definition(safeguards_payload=ambiguous_payload(kind))
    assert not any(
        impl["implemented-requirements"]
        for component in result["component-definition"]["components"]
        for impl in component.get("control-implementations", [])
    )


def test_distinct_safeguards_may_cover_the_same_requirement():
    payload = ambiguous_payload("safeguard")
    payload["safeguards"][1]["safeguard_id"] = "SG-INDEPENDENT"
    result = coverage_by_framework(payload)
    assert result["covered"] == result["reviewed"] == 1
    assert result["maintainer_reviewed_mappings"] == 2


def test_unique_sibling_mapping_survives_a_duplicate_target():
    payload = ambiguous_payload("mapping")
    sibling = deepcopy(load_safeguards()["safeguards"][0]["satisfies"][1])
    sibling["review_status"] = "reviewed"
    payload["safeguards"][0]["satisfies"].append(sibling)
    result = coverage_by_framework(payload)
    assert result["covered"] == result["reviewed"] == 1
    assert result["maintainer_reviewed_mappings"] == 1
    assert safeguards_by_requirement(payload) == {sibling["control_id"]: [payload["safeguards"][0]["safeguard_id"]]}


@pytest.mark.parametrize("kind", ["mapping", "safeguard"])
def test_ccf_and_framework_api_counts_agree_on_ambiguous_identities(tmp_path, monkeypatch, kind):
    from fastapi.testclient import TestClient

    from security_lakehouse import mapping_review
    from security_lakehouse.server_app import create_app

    payload = ambiguous_payload(kind)
    monkeypatch.setattr(mapping_review, "load_safeguards", lambda: deepcopy(payload))
    client = TestClient(create_app(tmp_path, require_auth=False))
    response = client.get("/api/v1/ccf/coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["frameworks"]["reviewed"] == body["data"]["frameworks"]["covered"] == 0
    assert sum(row["reviewed_mapping_count"] for row in body["data"]["families"]) == 0
    response = client.get("/api/v1/frameworks/coverage")
    assert response.status_code == 200
    body = response.json()
    summary = body["data"]["summary"]
    assert summary["attestable_requirement_count"] == summary["evaluatable_requirement_count"] == 0
    attestation = mapping_review.review_attestation(tmp_path)["summary"]
    assert attestation["mapped"] == attestation["maintainer_reviewed"] == attestation["org_reviewed"] == 0
