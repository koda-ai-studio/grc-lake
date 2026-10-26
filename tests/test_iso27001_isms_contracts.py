"""Management clauses are distinct from Annex A and never inherit its reviews."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from security_lakehouse.catalog import load_control_catalog, load_framework_registry
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards, validate_safeguards
from test_ccf_operational_assessment import normalized

FRAMEWORK = "iso-27001-isms-2022"
CLAUSES = {
    "4.1",
    "4.2",
    "4.3",
    "4.4",
    "5.1",
    "5.2",
    "5.3",
    "6.1.1",
    "6.1.2",
    "6.1.3",
    "6.2",
    "6.3",
    "7.1",
    "7.2",
    "7.3",
    "7.4",
    "7.5.1",
    "7.5.2",
    "7.5.3",
    "8.1",
    "8.2",
    "8.3",
    "9.1",
    "9.2.1",
    "9.2.2",
    "9.3.1",
    "9.3.2",
    "9.3.3",
    "10.1",
    "10.2",
}


def entries():
    return [s for s in load_safeguards()["safeguards"] if s["safeguard_id"].startswith("SG-ISMS-")]


def test_management_clause_catalog_is_distinct_and_complete_at_leaf_level():
    catalog = load_control_catalog()
    assert {cid for cid, row in catalog.items() if row["framework_id"] == FRAMEWORK} == {
        "ISO27001-" + clause for clause in CLAUSES
    }
    assert sum(row["framework_id"] == "iso-27001-2022" for row in catalog.values()) == 93
    assert "30" in load_framework_registry()[FRAMEWORK]["coverage_boundary"]


def test_new_mapping_coverage_does_not_grant_review_credit():
    coverage = coverage_by_framework(load_safeguards())
    row = coverage["frameworks"][FRAMEWORK]
    assert (row["controls"], row["covered"], row["reviewed"]) == (30, 30, 0)
    assert coverage["frameworks"]["iso-27001-2022"]["reviewed"] == 53
    assert validate_safeguards(load_safeguards()) == []
    assert len(entries()) == 30
    assert len({s["required_evidence_types"][0] for s in entries()}) == 30


@pytest.mark.parametrize("case", ["pass", "failed", "observed", "unbound", "wrong_type", "stale"])
def test_clauses_require_their_own_assessment_and_keep_proposed_status(case):
    catalog = load_control_catalog()
    assert entries()
    for safeguard in entries():
        mapping = safeguard["satisfies"][0]
        cid = mapping["control_id"]
        assert len(safeguard["satisfies"]) == 1
        assert mapping["review_status"] == "proposed"
        assert safeguard["reviewed_by"] is None
        row = normalized(
            asset_type="service",
            bindings=[] if case == "unbound" else [safeguard["safeguard_id"]],
            status=case if case in {"failed", "observed"} else "pass",
            control_ids=[cid],
            evidence_types=["generic_policy"] if case == "wrong_type" else safeguard["required_evidence_types"],
        )
        if case == "stale":
            row.update(event_time="2000-01-01T00:00:00Z", evidence_collected_at="2000-01-01T00:00:00Z")
        result = evaluate_safeguards(
            [row], {"review_log_verified": True, "safeguards": [safeguard]}, {cid: catalog[cid]}
        )
        assert (
            result["safeguards"][0]["status"]
            == {
                "pass": "pass",
                "failed": "fail",
                "observed": "not_evaluated",
                "unbound": "not_evaluated",
                "wrong_type": "stale",
                "stale": "stale",
            }[case]
        )
        assert result["requirements"][0]["status"] != "pass"


def test_generator_replays_without_overwriting_existing_contracts():
    from tools.sync_iso27001_isms import MANIFEST, build_entries, updated_payload, verify_source

    manifest = json.loads(MANIFEST.read_text())
    generated = build_entries(manifest, load_control_catalog())
    payload = json.loads((MANIFEST.parents[3] / "controls/safeguards.json").read_text())
    assert updated_payload(payload, generated) == payload
    changed = deepcopy(generated)
    changed[0]["objective"] = "An unreviewed semantic change"
    with pytest.raises(ValueError, match="explicit reconciliation"):
        updated_payload(payload, changed)
    duplicate = deepcopy(manifest)
    duplicate["rows"][-1] = duplicate["rows"][0]
    with pytest.raises(ValueError, match="distinct"):
        build_entries(duplicate, load_control_catalog())
    fixture = b"synthetic public preview"
    pinned = {
        "source": {"preview_sha256": hashlib.sha256(fixture).hexdigest()},
        "references": [{"sha256": hashlib.sha256(fixture).hexdigest()}],
    }
    verify_source(fixture, pinned, fixture)
    with pytest.raises(ValueError, match="pinned source"):
        verify_source(fixture + b"changed", pinned, fixture)
    with pytest.raises(ValueError, match="clause 6.3"):
        verify_source(fixture, pinned, fixture + b"changed")


def test_public_source_limits_and_amendment_context_remain_explicit():
    path = Path(__file__).resolve().parents[1] / "frameworks/packs/data/iso_27001_isms_2022.json"
    manifest = json.loads(path.read_text())
    assert "omits 6.3" in manifest["source"]["source_limit"]
    assert "not reproduced normative" in manifest["source"]["copyright"]
    rows = {r["id"]: r for r in manifest["rows"]}
    assert "climate relevance" in rows["4.1"]["evidence_checks"]
    assert "climate-related" in rows["4.2"]["evidence_checks"]


def test_graph_routes_management_clauses_separately_from_annex_a():
    from security_lakehouse.graph import _framework_from_control

    for clause in CLAUSES:
        assert _framework_from_control("ISO27001-" + clause) == FRAMEWORK
    assert _framework_from_control("ISO27001-A.5.1") == "iso-27001-2022"
