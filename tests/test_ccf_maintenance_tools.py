"""Source-backed CCF contract for maintenance tool controls."""

import pytest

from security_lakehouse.safeguards import load_safeguards, safeguards_by_requirement

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")


def test_maintenance_tool_controls_use_the_nist_800_171_crosswalk() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}
    safeguard = safeguards["SG-MAINTENANCE-002"]

    assert safeguard["title"] == "Maintenance tool controls"
    assert {
        (member["control_id"], member["framework_id"], member["review_status"]) for member in safeguard["satisfies"]
    } == {
        ("CMMC-3.7.2", "cmmc-2-level2", "proposed"),
        ("FEDRAMP-MA-3", "fedramp-moderate", "proposed"),
        ("NIST-800-53-MA-3", "nist-800-53-rev5", "proposed"),
    }
    assert safeguard["mapping_source"] == {
        "name": "NIST SP 800-171 Rev. 2",
        "url": "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-171r2.pdf",
        "sha256": "298bdbfcf6a4890a564b225c893230a0b32b2e69e3b98dd898aaeb1d544c5e12",
        "locator": "Appendix D, Table D-7, requirement 3.7.2 maps to MA-3",
    }

    mappings = safeguards_by_requirement()
    assert mappings["CMMC-3.7.2"] == ["SG-MAINTENANCE-002"]
    assert mappings["FEDRAMP-MA-3"] == ["SG-MAINTENANCE-002"]
