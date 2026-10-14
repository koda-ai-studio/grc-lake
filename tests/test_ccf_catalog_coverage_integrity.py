"""Every credited CCF mapping must resolve within its coverage denominator."""

from copy import deepcopy

import pytest

from security_lakehouse.oscal import build_component_definition
from security_lakehouse.safeguards import framework_mapping_coverage

CATALOG = {"A": {"framework_id": "alpha"}, "B": {"framework_id": "beta"}}


def _payload(*members):
    return {"safeguards": [{"safeguard_id": f"SG-{i}", "satisfies": [m]} for i, m in enumerate(members)]}


@pytest.mark.parametrize("role", ["primary", "supporting"])
@pytest.mark.parametrize("control_id,framework_id", [("A", "beta"), ("MISSING", "alpha")])
def test_invalid_catalog_target_cannot_inflate_any_coverage_counter(role, control_id, framework_id):
    member = {"control_id": control_id, "framework_id": framework_id, "role": role, "review_status": "reviewed"}
    result = framework_mapping_coverage(_payload(member), catalog=CATALOG)
    assert result["covered"] == result["reviewed"] == 0
    assert result["maintainer_reviewed_mappings"] == result["contextual_mappings"] == 0
    assert result["uncovered"] == 2
    assert result["covered"] == sum(row["covered"] for row in result["frameworks"].values())
    assert result["maintainer_reviewed_mappings"] == sum(
        row["maintainer_reviewed_mappings"] for row in result["frameworks"].values()
    )


def test_invalid_reviewed_mapping_cannot_promote_a_valid_proposal():
    proposal = {"control_id": "A", "framework_id": "alpha", "review_status": "proposed"}
    wrong_review = {"control_id": "A", "framework_id": "beta", "review_status": "reviewed"}
    payload = _payload(proposal, wrong_review)
    before = deepcopy(payload)
    result = framework_mapping_coverage(payload, catalog=CATALOG)
    assert result["covered"] == result["proposed"] == 1
    assert result["reviewed"] == 0
    assert result["frameworks"]["alpha"]["proposed_mappings"] == 1
    assert payload == before


def test_empty_catalog_has_no_mapping_credits():
    result = framework_mapping_coverage(_payload({"control_id": "A", "framework_id": "alpha"}), catalog={})
    assert result["controls"] == result["covered"] == result["maintainer_reviewed_mappings"] == 0


def test_legacy_framework_omission_and_review_states_remain_supported():
    result = framework_mapping_coverage(
        _payload(
            {"control_id": "A", "review_status": "reviewed"},
            {"control_id": "B", "framework_id": "beta", "effective_review_state": "rejected"},
        ),
        catalog=CATALOG,
    )
    assert result["covered"] == result["reviewed"] == 1
    assert result["rejected_requirements"] == result["rejected_mappings"] == 1
    assert result["covered"] + result["uncovered"] == result["controls"] == 2


@pytest.mark.parametrize("control_id,framework_id", [("A", "beta"), ("MISSING", "alpha")])
def test_oscal_excludes_invalid_catalog_targets_but_preserves_valid_siblings(control_id, framework_id):
    valid = {"control_id": "B", "framework_id": "beta", "review_status": "reviewed"}
    invalid = {"control_id": control_id, "framework_id": framework_id, "review_status": "reviewed"}
    payload = _payload(invalid)
    payload["safeguards"][0]["satisfies"].append(valid)
    before = deepcopy(payload)
    assert framework_mapping_coverage(payload, catalog=CATALOG)["reviewed"] == 1
    document = build_component_definition(payload, catalog=CATALOG)
    exported = {
        prop["value"]
        for component in document["component-definition"]["components"]
        for implementation in component.get("control-implementations", [])
        for requirement in implementation["implemented-requirements"]
        for prop in requirement["props"]
        if prop["name"] == "trustops-control-id"
    }
    assert exported == {"B"}
    assert payload == before


def test_oscal_resolves_legacy_framework_omission_from_the_catalog():
    payload = _payload({"control_id": "A", "review_status": "reviewed"})
    document = build_component_definition(payload, catalog=CATALOG)
    implementation = document["component-definition"]["components"][0]["control-implementations"][0]
    assert implementation["source"] == "urn:grc-lake:framework:alpha"


def test_oscal_empty_catalog_exports_no_implemented_requirements():
    document = build_component_definition(
        _payload({"control_id": "A", "framework_id": "alpha", "review_status": "reviewed"}), catalog={}
    )
    assert all(
        "control-implementations" not in component for component in document["component-definition"]["components"]
    )
