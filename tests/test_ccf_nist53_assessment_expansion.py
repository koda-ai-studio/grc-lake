"""Direct NIST assessment contracts preserve obligation and review boundaries."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards, validate_safeguards
from test_ccf_operational_assessment import normalized

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")

ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "controls/nist53_assessment_expansion.json").read_text())
PREFIX = "SG-NIST53-"


def entries():
    return [entry for entry in load_safeguards()["safeguards"] if entry["safeguard_id"].startswith(PREFIX)]


def test_complete_family_expansion_reaches_mapped_target_without_review_credit():
    payload = load_safeguards()
    new = entries()
    assert len(new) == len(PLAN["control_ids"]) == 381
    assert validate_safeguards(payload) == []
    before = coverage_by_framework({**payload, "safeguards": [e for e in payload["safeguards"] if e not in new]})
    after = coverage_by_framework(payload)
    assert after["controls"] == before["controls"] == 2252
    assert after["covered"] == before["covered"] + 381 == 1803
    assert after["reviewed"] == before["reviewed"] == 339
    assert after["coverage_pct"] == 80.1


def test_each_obligation_has_its_own_source_and_typed_assessment_contract():
    catalog = load_control_catalog()
    new = entries()
    assert new
    assert len({e["required_evidence_types"][0] for e in new}) == len(new)
    for entry in new:
        assert entry["reviewed_by"] is None and entry["reviewed_at"] is None
        assert len(entry["satisfies"]) == len(entry["required_evidence_types"]) == 1
        member = entry["satisfies"][0]
        assert member["control_id"] == "NIST-800-53-" + entry["safeguard_id"].removeprefix(PREFIX)
        assert member["framework_id"] == "nist-800-53-rev5"
        assert member["role"] == "primary" and member["review_status"] == "proposed"
        assert member["control_version"] == catalog[member["control_id"]]["version"]
        assert member["mapping_source"]["sha256"] == PLAN["source"]["catalog_sha256"]
        assert "statement" in entry["objective"].lower()
        assert "assessment" in entry["evidence_requirement"].lower()
        assert "{{" not in entry["objective"] + entry["evidence_requirement"]


@pytest.mark.parametrize("family", PLAN["families"])
@pytest.mark.parametrize("case", ["pass", "failed", "unknown", "observed", "unbound", "wrong_type", "stale"])
def test_family_assessments_require_their_own_evidence_and_separate_review(family, case):
    selected = [e for e in entries() if e["safeguard_id"].startswith(PREFIX + family + "-")]
    assert selected
    catalog = load_control_catalog()
    for entry in selected:
        cid = entry["satisfies"][0]["control_id"]
        row = normalized(
            asset_type=entry["asset_types"][0],
            bindings=[] if case == "unbound" else [entry["safeguard_id"]],
            status=case if case in {"failed", "unknown", "observed"} else "pass",
            control_ids=[cid],
            evidence_types=["generic_control_assessment"] if case == "wrong_type" else entry["required_evidence_types"],
        )
        if case == "stale":
            row.update(event_time="2000-01-01T00:00:00Z", evidence_collected_at="2000-01-01T00:00:00Z")
        payload = {"review_log_verified": True, "safeguards": [entry]}
        result = evaluate_safeguards([row], payload, {cid: catalog[cid]})
        expected = {"pass": "pass", "failed": "fail", "wrong_type": "stale", "stale": "stale"}.get(
            case, "not_evaluated"
        )
        assert result["safeguards"][0]["status"] == expected, cid
        assert result["requirements"][0]["status"] != "pass", cid
        reviewed = deepcopy(payload)
        reviewed["safeguards"][0]["satisfies"][0]["effective_review_state"] = "org_reviewed"
        assert evaluate_safeguards([row], reviewed, {cid: catalog[cid]})["requirements"][0]["status"] == expected, cid
