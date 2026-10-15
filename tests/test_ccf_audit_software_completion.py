"""Source-backed CCF contracts for audit-event review and software authorization."""

import pytest

from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")

CROSSWALK_SOURCE = {
    "name": "NIST SP 800-171 Rev. 2",
    "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
    "sha256": "298bdbfcf6a4890a564b225c893230a0b32b2e69e3b98dd898aaeb1d544c5e12",
}


def test_audit_and_software_safeguards_use_published_nist_sources() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}

    audit = safeguards["SG-AUDITEVENTREVIEW-001"]
    assert audit["title"] == "Audit event review and updates"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in audit["satisfies"]
    } == {
        ("CMMC-3.3.3", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-AU-2", "fedramp-moderate", "proposed"),
        ("NIST-800-53-AU-2", "nist-800-53-rev5", "proposed"),
    }
    assert audit["mapping_source"] == {
        **CROSSWALK_SOURCE,
        "locator": "Appendix D, Table D-3, requirement 3.3.3 maps to AU-2(3)",
    }
    fedramp_audit = next(member for member in audit["satisfies"] if member["control_id"] == "FEDRAMP-AU-2")
    assert fedramp_audit["mapping_source"] == {
        "name": "NIST SP 800-53 Rev. 5",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf",
        "sha256": "fc63bcd61715d0181dd8e85998b1e6201ae3515fc6626102101cab1841e11ec6",
        "locator": "Chapter 3, AU-2(e), review and update the event types selected for logging",
    }

    software = safeguards["SG-SOFTWAREAUTHORIZATION-001"]
    assert software["title"] == "Software execution authorization"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in software["satisfies"]
    } == {
        ("CMMC-3.4.8", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-CM-7.5", "fedramp-moderate", "proposed"),
        ("NIST-800-53-CM-7.5", "nist-800-53-rev5", "proposed"),
    }
    assert software["mapping_source"] == {
        **CROSSWALK_SOURCE,
        "locator": "Appendix D, Table D-4, requirement 3.4.8 maps to CM-7(4) and CM-7(5)",
    }

    mappings = safeguards_by_requirement()
    assert mappings["CMMC-3.3.3"] == ["SG-AUDITEVENTREVIEW-001"]
    assert mappings["CMMC-3.4.8"] == ["SG-SOFTWAREAUTHORIZATION-001"]
    assert "SG-AUDITEVENTREVIEW-001" in mappings["FEDRAMP-AU-2"]
    assert mappings["FEDRAMP-CM-7.5"] == ["SG-SOFTWAREAUTHORIZATION-001"]


def test_audit_and_software_lane_closes_three_gaps_without_attestation() -> None:
    payload = load_safeguards()
    new_ids = {"SG-AUDITEVENTREVIEW-001", "SG-SOFTWAREAUTHORIZATION-001"}
    payload["safeguards"] = [entry for entry in payload["safeguards"] if entry["safeguard_id"] not in new_ids]

    without_lane = coverage_by_framework(payload)
    coverage = coverage_by_framework()

    assert coverage["safeguards"] == without_lane["safeguards"] + 2
    assert coverage["covered"] == without_lane["covered"] + 4
    assert coverage["uncovered"] == without_lane["uncovered"] - 4
    assert coverage["reviewed"] == without_lane["reviewed"]
    assert coverage["proposed"] == without_lane["proposed"] + 4
    assert (
        coverage["frameworks"]["cmmc-2-level2"]["covered"] == without_lane["frameworks"]["cmmc-2-level2"]["covered"] + 2
    )
    assert (
        coverage["frameworks"]["fedramp-moderate"]["covered"]
        == without_lane["frameworks"]["fedramp-moderate"]["covered"] + 1
    )
