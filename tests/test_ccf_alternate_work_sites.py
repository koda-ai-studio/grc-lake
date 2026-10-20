"""Source-backed CCF contract for safeguarding CUI at alternate work sites."""

import pytest

from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")


def test_alternate_work_site_safeguards_use_the_nist_800_171_crosswalk() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}
    safeguard = safeguards["SG-CHANGEMANAGEMENT-002"]

    assert safeguard["title"] == "Alternate work site safeguards"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in safeguard["satisfies"]
    } == {
        ("CMMC-3.10.6", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-PE-17", "fedramp-moderate", "proposed"),
        ("NIST-800-53-PE-17", "nist-800-53-rev5", "proposed"),
    }
    assert safeguard["mapping_source"] == {
        "name": "NIST SP 800-171 Rev. 2",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
        "sha256": "298bdbfcf6a4890a564b225c893230a0b32b2e69e3b98dd898aaeb1d544c5e12",
        "locator": "Appendix D, Table D-10, requirement 3.10.6 maps to PE-17",
    }

    mappings = safeguards_by_requirement()
    assert mappings["CMMC-3.10.6"] == ["SG-CHANGEMANAGEMENT-002"]
    assert mappings["FEDRAMP-PE-17"] == ["SG-CHANGEMANAGEMENT-002"]


def test_alternate_work_site_safeguards_close_two_gaps_without_overstating_attestation() -> None:
    payload = load_safeguards()
    payload["safeguards"] = [
        entry for entry in payload["safeguards"] if entry["safeguard_id"] != "SG-CHANGEMANAGEMENT-002"
    ]

    without_crosswalk = coverage_by_framework(payload)
    coverage = coverage_by_framework()

    # NIST obligations retain their independent source-native assessment
    # contracts when this crosswalk is removed; count each requirement once.
    assert (
        coverage["frameworks"]["nist-800-53-rev5"]["covered"]
        == without_crosswalk["frameworks"]["nist-800-53-rev5"]["covered"]
        == 1014
    )
    assert coverage["safeguards"] == without_crosswalk["safeguards"] + 1
    assert coverage["covered"] == without_crosswalk["covered"] + 2
    assert coverage["uncovered"] == without_crosswalk["uncovered"] - 2
    assert coverage["reviewed"] == without_crosswalk["reviewed"]
    assert coverage["proposed"] == without_crosswalk["proposed"] + 2
    assert (
        coverage["frameworks"]["cmmc-2-level2"]["covered"]
        == without_crosswalk["frameworks"]["cmmc-2-level2"]["covered"] + 1
    )
    assert (
        coverage["frameworks"]["fedramp-moderate"]["covered"]
        == without_crosswalk["frameworks"]["fedramp-moderate"]["covered"] + 1
    )
