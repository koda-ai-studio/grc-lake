"""Source-backed NIST CSF 2.0 coverage contracts for existing CCF safeguards."""

from __future__ import annotations

import copy

import pytest

from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    mapping_review_report,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")

CSF_SOURCE = {
    "name": "NIST Cybersecurity Framework (CSF) 2.0",
    "url": "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf",
    "sha256": "3c31f46fee98cac0c4323453e5109291a213b4de7fef8c058af9bf67f717433c",
}

ASSET_CONTROLS = {
    "NIST-CSF-ID.AM-01",
    "NIST-CSF-ID.AM-02",
    "NIST-CSF-ID.AM-03",
    "NIST-CSF-ID.AM-04",
    "NIST-CSF-ID.AM-05",
    "NIST-CSF-ID.AM-07",
}
ASSET_LOCATOR = "NIST CSF 2.0 Core, Appendix A, ID.AM (Asset Management): ID.AM-01 through ID.AM-05 and ID.AM-07"

GOVERNANCE_CONTROLS = {
    *(f"NIST-CSF-GV.OC-0{i}" for i in range(1, 6)),
    *(f"NIST-CSF-GV.OV-0{i}" for i in range(1, 4)),
    "NIST-CSF-GV.PO-01",
    "NIST-CSF-GV.PO-02",
    *(f"NIST-CSF-GV.RR-0{i}" for i in range(1, 5)),
}
GOVERNANCE_LOCATOR = (
    "NIST CSF 2.0 Core, Appendix A, GV (Govern): "
    "GV.OC-01 through GV.OC-05; GV.OV-01 through GV.OV-03; "
    "GV.PO-01 through GV.PO-02; GV.RR-01 through GV.RR-04"
)


def test_nist_csf_mappings_are_source_linked_and_proposed() -> None:
    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}

    for safeguard_id, expected_ids, locator in (
        ("SG-DATAINVENTORY-001", ASSET_CONTROLS, ASSET_LOCATOR),
        ("SG-GOVERNANCE-002", GOVERNANCE_CONTROLS, GOVERNANCE_LOCATOR),
    ):
        members = {
            member["control_id"]: member
            for member in safeguards[safeguard_id]["satisfies"]
            if member["control_id"] in expected_ids
        }
        assert set(members) == expected_ids
        for member in members.values():
            assert member["framework_id"] == "nist-csf-2.0"
            assert member["role"] == "equivalent"
            assert member["review_status"] == "proposed"
            assert member["mapping_source"] == {**CSF_SOURCE, "locator": locator}


def test_nist_csf_lane_adds_twenty_evaluatable_requirements_not_attestable_ones() -> None:
    target_ids = ASSET_CONTROLS | GOVERNANCE_CONTROLS
    payload_without_lane = copy.deepcopy(load_safeguards())
    for entry in payload_without_lane["safeguards"]:
        entry["satisfies"] = [member for member in entry["satisfies"] if member["control_id"] not in target_ids]

    before = coverage_by_framework(payload_without_lane)
    after = coverage_by_framework()

    assert len(target_ids) == 20
    assert after["covered"] == before["covered"] + len(target_ids)
    assert after["uncovered"] == before["uncovered"] - len(target_ids)
    assert after["reviewed"] == before["reviewed"]
    assert after["proposed"] == before["proposed"] + len(target_ids)
    assert after["frameworks"]["nist-csf-2.0"]["covered"] == before["frameworks"]["nist-csf-2.0"]["covered"] + len(
        target_ids
    )

    report = mapping_review_report()
    assert report["source_backed_by_framework"]["nist-csf-2.0"] >= len(target_ids)
