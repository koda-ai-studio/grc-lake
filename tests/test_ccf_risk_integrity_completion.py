"""Source-backed CCF contracts for the remaining risk and integrity practices."""

import pytest

from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")

SOURCE = {
    "name": "NIST SP 800-171 Rev. 2",
    "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
    "sha256": "298bdbfcf6a4890a564b225c893230a0b32b2e69e3b98dd898aaeb1d544c5e12",
}


def test_risk_and_integrity_safeguards_use_the_published_nist_crosswalk() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}

    risk = safeguards["SG-RISKASSESSMENT-002"]
    assert risk["title"] == "Organizational risk assessments"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in risk["satisfies"]
    } == {
        ("CMMC-3.11.1", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-RA-3", "fedramp-moderate", "proposed"),
        ("NIST-800-53-RA-3", "nist-800-53-rev5", "proposed"),
    }
    assert risk["mapping_source"] == {
        **SOURCE,
        "locator": "Appendix D, Table D-11, requirement 3.11.1 maps to RA-3",
    }

    scanning = safeguards["SG-MALWARESCANNING-001"]
    assert scanning["title"] == "Periodic and real-time malware scanning"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in scanning["satisfies"]
    } == {
        ("CMMC-3.14.5", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-SI-3", "fedramp-moderate", "proposed"),
        ("NIST-800-53-SI-3", "nist-800-53-rev5", "proposed"),
    }
    assert scanning["mapping_source"] == {
        **SOURCE,
        "locator": "Appendix D, Table D-14, requirement 3.14.5 maps to SI-3",
    }

    mappings = safeguards_by_requirement()
    assert mappings["CMMC-3.11.1"] == ["SG-RISKASSESSMENT-002"]
    assert mappings["CMMC-3.14.5"] == ["SG-MALWARESCANNING-001"]
    assert "SG-RISKASSESSMENT-002" in mappings["FEDRAMP-RA-3"]
    assert "SG-MALWARESCANNING-001" in mappings["FEDRAMP-SI-3"]


def test_risk_and_integrity_lane_closes_two_cmmc_gaps_without_attestation() -> None:
    payload = load_safeguards()
    new_ids = {"SG-RISKASSESSMENT-002", "SG-MALWARESCANNING-001"}
    payload["safeguards"] = [entry for entry in payload["safeguards"] if entry["safeguard_id"] not in new_ids]

    without_lane = coverage_by_framework(payload)
    coverage = coverage_by_framework()

    assert coverage["safeguards"] == without_lane["safeguards"] + 2
    assert coverage["covered"] == without_lane["covered"] + 2
    assert coverage["uncovered"] == without_lane["uncovered"] - 2
    assert coverage["reviewed"] == without_lane["reviewed"]
    assert coverage["proposed"] == without_lane["proposed"] + 2
    assert (
        coverage["frameworks"]["cmmc-2-level2"]["covered"] == without_lane["frameworks"]["cmmc-2-level2"]["covered"] + 2
    )
    assert (
        coverage["frameworks"]["fedramp-moderate"]["covered"]
        == without_lane["frameworks"]["fedramp-moderate"]["covered"]
    )
