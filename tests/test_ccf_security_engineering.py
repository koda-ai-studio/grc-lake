"""Source-backed CCF contract for security engineering principles."""

import pytest

from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")


def test_security_engineering_uses_the_nist_800_171_crosswalk() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}
    safeguard = safeguards["SG-SECURITYENGINEERING-001"]

    assert safeguard["title"] == "Security engineering principles"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in safeguard["satisfies"]
    } == {
        ("CMMC-3.13.2", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-SA-8", "fedramp-moderate", "proposed"),
        ("NIST-800-53-SA-8", "nist-800-53-rev5", "proposed"),
    }
    assert safeguard["mapping_source"] == {
        "name": "NIST SP 800-171 Rev. 2",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
        "sha256": "298bdbfcf6a4890a564b225c893230a0b32b2e69e3b98dd898aaeb1d544c5e12",
        "locator": "Appendix D, Table D-13, requirement 3.13.2 maps to SA-8",
    }

    mappings = safeguards_by_requirement()
    assert mappings["CMMC-3.13.2"] == ["SG-SECURITYENGINEERING-001"]
    assert mappings["FEDRAMP-SA-8"] == ["SG-SECURITYENGINEERING-001"]


def test_security_engineering_closes_two_gaps_without_overstating_attestation() -> None:
    payload = load_safeguards()
    payload["safeguards"] = [
        entry for entry in payload["safeguards"] if entry["safeguard_id"] != "SG-SECURITYENGINEERING-001"
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
