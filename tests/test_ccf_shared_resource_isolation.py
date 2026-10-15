"""Source-backed CCF contract for shared-resource information isolation."""

import pytest

from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")


def test_shared_resource_isolation_uses_the_nist_800_171_crosswalk() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}
    safeguard = safeguards["SG-SHAREDRESOURCEISOLATION-001"]

    assert safeguard["title"] == "Shared-resource information isolation"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in safeguard["satisfies"]
    } == {
        ("CMMC-3.13.4", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-SC-4", "fedramp-moderate", "proposed"),
        ("NIST-800-53-SC-4", "nist-800-53-rev5", "proposed"),
    }
    assert safeguard["mapping_source"] == {
        "name": "NIST SP 800-171 Rev. 2",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
        "sha256": "298bdbfcf6a4890a564b225c893230a0b32b2e69e3b98dd898aaeb1d544c5e12",
        "locator": "Appendix D, Table D-13, requirement 3.13.4 maps to SC-4",
    }

    mappings = safeguards_by_requirement()
    for control_id in ("CMMC-3.13.4", "FEDRAMP-SC-4"):
        assert mappings[control_id] == ["SG-SHAREDRESOURCEISOLATION-001"]


def test_shared_resource_isolation_closes_two_gaps_without_overstating_attestation() -> None:
    payload = load_safeguards()
    payload["safeguards"] = [
        entry for entry in payload["safeguards"] if entry["safeguard_id"] != "SG-SHAREDRESOURCEISOLATION-001"
    ]

    without_crosswalk = coverage_by_framework(payload)
    coverage = coverage_by_framework()

    assert coverage["safeguards"] == without_crosswalk["safeguards"] + 1
    assert coverage["covered"] == without_crosswalk["covered"] + 3
    assert coverage["uncovered"] == without_crosswalk["uncovered"] - 3
    assert coverage["reviewed"] == without_crosswalk["reviewed"]
    assert coverage["proposed"] == without_crosswalk["proposed"] + 3
    assert (
        coverage["frameworks"]["cmmc-2-level2"]["covered"]
        == without_crosswalk["frameworks"]["cmmc-2-level2"]["covered"] + 1
    )
    assert (
        coverage["frameworks"]["fedramp-moderate"]["covered"]
        == without_crosswalk["frameworks"]["fedramp-moderate"]["covered"] + 1
    )
