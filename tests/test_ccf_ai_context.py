"""Source-backed proposed CCF coverage and evidence evaluation boundaries."""

import pytest

from security_lakehouse.policy import ControlContext, evaluate_control
from security_lakehouse.safeguards import (
    coverage_by_framework,
    load_safeguards,
    safeguards_by_requirement,
    validate_safeguards,
)

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")

EXPECTED = {
    "SG-AIINVENTORY-001": ["NIST-AI-RMF-GOVERN-1.6"],
    "SG-AICONTEXT-001": ["NIST-AI-RMF-MAP-1.1"],
    "SG-AICATEGORIZATION-001": ["NIST-AI-RMF-MAP-2.1"],
}


def test_new_safeguards_have_provenance_and_no_reviewed_coverage():
    payload = load_safeguards()
    entries = {s["safeguard_id"]: s for s in payload["safeguards"]}
    for sid, controls in EXPECTED.items():
        entry = entries[sid]
        assert [m["control_id"] for m in entry["satisfies"]] == controls
        assert all(m["review_status"] == "proposed" for m in entry["satisfies"])
        assert entry["reviewed_by"] is None and entry["reviewed_at"] is None
        assert entry["mapping_source"]["url"].startswith("https://nvlpubs.nist.gov/")
        assert len(entry["mapping_source"]["sha256"]) == 64
        assert entry["mapping_source"]["locator"]
        for cid in controls:
            assert sid not in safeguards_by_requirement(payload, reviewed_only=True).get(cid, [])
    assert validate_safeguards(payload) == []
    before = {**payload, "safeguards": [s for s in payload["safeguards"] if s["safeguard_id"] not in EXPECTED]}
    after_coverage, before_coverage = coverage_by_framework(payload), coverage_by_framework(before)
    assert after_coverage["covered"] - before_coverage["covered"] == 2
    assert after_coverage["reviewed"] == before_coverage["reviewed"]


@pytest.mark.parametrize(
    "facts,expected",
    [
        ({"event_count": 0, "evidence_count": 0}, "fail"),
        ({"event_count": 1, "evidence_count": 1, "evidence_status": "stale"}, "fail"),
        ({"event_count": 1, "evidence_count": 1, "open_violation_count": 1}, "fail"),
        ({"event_count": 1, "evidence_count": 1, "evidence_status": "fresh"}, "pass"),
    ],
)
def test_new_safeguards_require_current_evidence_without_open_findings(facts, expected):
    entries = {s["safeguard_id"]: s for s in load_safeguards()["safeguards"]}
    for sid in EXPECTED:
        assert (
            evaluate_control(ControlContext(control_id=sid, **facts), entries[sid]["evaluation_rule"]).status
            == expected
        )
