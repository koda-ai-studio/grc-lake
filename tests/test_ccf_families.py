"""CCF control families: one governed taxonomy for safeguards."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from security_lakehouse.safeguards import coverage_by_family, load_ccf_families, load_safeguards, validate_safeguards

ROOT = Path(__file__).resolve().parents[1]


def test_focused_families_keep_broad_contracts_and_source_assignments():
    entries = {e["safeguard_id"]: e for e in load_safeguards()["safeguards"]}
    expected = {
        "SG-IDENTITY-001": "identity",
        "SG-IDENTITY-002": "access-review",
        "SG-IDENTITY-003": "authentication",
        "SG-NIST53-AC-6.5": "privileged-access",
        "SG-NIST53-IA-4": "identity-lifecycle",
        "SG-SUPPLIERINVENTORY-001": "supplier-inventory",
        "SG-AIPROVENANCE-001": "supply-chain-integrity",
        "SG-NIST53-SR-6": "supplier-assurance",
        "SG-AIEVALUATION-001": "ai-evaluation",
        "SG-AIINVENTORY-001": "ai-inventory-context",
        "SG-AIMONITORING-001": "ai-monitoring",
        "SG-AIOVERSIGHT-001": "ai-oversight-transparency",
        "SG-AIDATAGOVERNANCE-001": "ai-data-governance",
        "SG-AIGOVERNANCE-001": "ai-governance",
    }
    for sid, family in expected.items():
        assert entries[sid]["risk_domain"] == family
    plan = json.loads((ROOT / "controls/nist53_assessment_expansion.json").read_text())
    for cid, family in plan["control_families"].items():
        assert entries["SG-NIST53-" + cid]["risk_domain"] == family


def test_source_regrouping_retains_review_receipts_and_semantics():
    from copy import deepcopy

    from tools.sync_nist53_assessment_safeguards import reconcile_entries, source_contract

    from security_lakehouse.ccf_contracts import definition_digest

    old = deepcopy(next(e for e in load_safeguards()["safeguards"] if e["safeguard_id"] == "SG-NIST53-IA-4.1"))
    old["risk_domain"] = "identity"
    assert old["satisfies"][0]["review_status"] == "reviewed"
    proposed = source_contract(old)
    proposed["risk_domain"] = "identity-lifecycle"
    result = reconcile_entries([old], [proposed])[0]
    assert result["risk_domain"] == "identity-lifecycle"
    assert result["satisfies"] == old["satisfies"]
    assert definition_digest(result) == definition_digest(old)
    changed = deepcopy(proposed)
    changed["objective"] = "weakened contract"
    import pytest

    with pytest.raises(ValueError, match="refusing to change"):
        reconcile_entries([old], [changed])


def test_every_family_is_defined_and_used() -> None:
    families = load_ccf_families()
    used = Counter(entry["risk_domain"] for entry in load_safeguards()["safeguards"])

    assert set(used) == set(families), "families.json and safeguard risk_domains must agree exactly"
    for family in families.values():
        assert family["label"]
        assert family["description"]


def test_no_catch_all_family() -> None:
    entries = load_safeguards()["safeguards"]
    # Reusable safeguards retain their anti-catch-all guard. Source-native
    # contracts follow the standard's obligation counts, not an equal quota:
    # AC and IA contain many clauses; SOC 2 governance has distinct criteria.
    # ISMS management clauses are also explicit single-clause contracts, checked
    # against their manifest below; the prefix alone grants no exemption.
    # Only the explicit repair plan can exempt vendor-guided contracts. A new
    # SG-REVIEW prefix alone must not bypass the reusable-family guard.
    repairs = json.loads((ROOT / "controls/soc2_iso_review_plan.json").read_text())["repairs"]
    scoped = {"SG-REVIEW-" + repair["control_id"].replace(".", "-"): repair for repair in repairs}
    isms_rows = json.loads((ROOT / "frameworks/packs/data/iso_27001_isms_2022.json").read_text())["rows"]
    isms = {"SG-ISMS-" + row["id"].replace(".", "-"): row for row in isms_rows}
    common = [
        entry
        for entry in entries
        if not entry["safeguard_id"].startswith("SG-NIST53-")
        and entry["safeguard_id"] not in scoped
        and entry["safeguard_id"] not in isms
    ]
    used = Counter(entry["risk_domain"] for entry in common)
    total = sum(used.values())
    taxonomy = load_ccf_families()
    for entry in entries:
        if entry["safeguard_id"].startswith("SG-NIST53-"):
            source_id = entry["safeguard_id"].removeprefix("SG-NIST53-")
            assert len(entry["satisfies"]) == 1
            assert entry["satisfies"][0]["control_id"] == "NIST-800-53-" + source_id
            assert source_id.split("-")[0] in taxonomy[entry["risk_domain"]]["nist_800_53_families"]
        elif entry["safeguard_id"] in isms:
            clause = isms[entry["safeguard_id"]]
            assert entry["risk_domain"] == clause["risk_domain"]
            assert len(entry["satisfies"]) == 1
            assert entry["satisfies"][0]["control_id"] == "ISO27001-" + clause["id"]
            assert entry["satisfies"][0]["mapping_basis"] == "internal_assessment_proposal"
            assert entry["required_evidence_types"] == clause["required_evidence_types"]
        elif entry["safeguard_id"] in scoped:
            repair = scoped[entry["safeguard_id"]]
            assert entry["risk_domain"] == repair["risk_domain"]
            assert len(entry["satisfies"]) == 1
            member = entry["satisfies"][0]
            assert member["control_id"] == repair["control_id"]
            assert member["role"] == "primary"
            assert member["mapping_basis"] == "vendor_guided_proposal"
            assert entry["required_evidence_types"] == [
                "review_" + repair["control_id"].lower().replace("-", "_").replace(".", "_")
            ]
    assert "controls-operations" not in used
    assert max(used.values()) <= total * 0.15


def test_family_crosswalks_use_real_identifiers() -> None:
    manifest = json.loads((ROOT / "frameworks/packs/data/nist_800_53_rev5_catalog.json").read_text())
    nist_families = {row["family"] for row in manifest["rows"]}
    cis_controls = {
        row["id"] for row in json.loads((ROOT / "frameworks/packs/data/cis_controls_v8_1.json").read_text())["rows"]
    }
    for family in load_ccf_families().values():
        assert set(family["nist_800_53_families"]) <= nist_families
        assert set(family["cis_controls"]) <= cis_controls


def test_unknown_family_is_rejected() -> None:
    payload = json.loads(json.dumps(load_safeguards()))
    payload["safeguards"][0]["risk_domain"] = "not-a-family"
    assert any("unknown CCF family" in problem for problem in validate_safeguards(payload))


def test_family_ledger_carries_definitions() -> None:
    families = load_ccf_families()
    document = (ROOT / "docs/COMMON_CONTROL_FRAMEWORK.md").read_text()
    for row in coverage_by_family():
        assert f"`{row['family_id']}`" in document
        assert row["label"] == families[row["family_id"]]["label"]
        assert row["description"] == families[row["family_id"]]["description"]
        assert row["nist_800_53_families"] == families[row["family_id"]]["nist_800_53_families"]


def test_title_theme_members_never_inherit_a_safeguard_citation() -> None:
    from security_lakehouse.safeguards import mapping_review_items, mapping_review_queue

    safeguards = {entry["safeguard_id"]: entry for entry in load_safeguards()["safeguards"]}
    queue = mapping_review_queue()
    themed = [
        item
        for item in queue
        if any(
            m["control_id"] == item["control_id"] and m.get("mapping_basis") == "title_theme"
            for m in safeguards[item["safeguard_id"]]["satisfies"]
        )
    ]
    assert themed
    assert all("mapping_source" not in item for item in themed)
    inherited = next(item for item in mapping_review_items() if item["control_id"] == "CMMC-3.1.4")
    assert inherited["mapping_source"] == safeguards["SG-SEPARATIONOFDUTIES-001"]["mapping_source"]


# A broad safeguard answers many requirements with one generic evidence rule,
# so each extra requirement gets shallower assurance. Existing umbrellas may
# only shrink; any other safeguard, new ones included, stays at or under the cap.
FANOUT_CAP = 20
FANOUT_CEILINGS = {
    "SG-IDENTITY-001": 153,
    "SG-LOGGING-001": 78,
    "SG-DATAPROTECTION-001": 77,
    "SG-PHYSICAL-001": 75,
    "SG-AVAILABILITY-001": 73,
    "SG-GOVERNANCE-002": 72,
    "SG-DETECTION-001": 71,
    "SG-NETWORK-001": 62,
    "SG-THIRDPARTYRISK-001": 55,
    "SG-POLICYMANAGEMENT-001": 51,
    "SG-CHANGEMANAGEMENT-001": 48,
    "SG-AIGOVERNANCE-001": 38,
    "SG-INCIDENTHANDLING-001": 37,
    "SG-VULNERABILITYMANAGEMENT-001": 32,
    "SG-RISKMANAGEMENT-001": 31,
    "SG-INCIDENTRESPONSE-001": 30,
    "SG-INCIDENTNOTIFICATION-001": 30,
    "SG-DATAINVENTORY-001": 30,
    "SG-TRAINING-001": 29,
    "SG-IDENTITY-002": 28,
    "SG-INCIDENTPLAN-001": 25,
    "SG-DATARETENTION-001": 22,
    "SG-SUPPLYCHAINPROGRAM-001": 21,
}


def fanout_problems(entries: list[dict]) -> list[str]:
    problems = []
    for entry in entries:
        sid, count = entry["safeguard_id"], len(entry["satisfies"])
        limit = FANOUT_CEILINGS.get(sid, FANOUT_CAP)
        if count > limit:
            problems.append(f"{sid} satisfies {count} requirements; its ceiling is {limit}")
    return problems


def test_safeguard_fanout_never_grows() -> None:
    entries = load_safeguards()["safeguards"]
    assert fanout_problems(entries) == []
    present = {entry["safeguard_id"]: len(entry["satisfies"]) for entry in entries}
    assert set(FANOUT_CEILINGS) <= set(present), "drop ceilings for removed safeguards"
    assert all(limit > FANOUT_CAP for limit in FANOUT_CEILINGS.values())
    lowered = {sid: present[sid] for sid, limit in FANOUT_CEILINGS.items() if present[sid] < limit}
    assert not lowered, f"lower these ceilings to the new counts: {lowered}"


def test_fanout_guard_rejects_growth_and_new_umbrellas() -> None:
    entries = json.loads(json.dumps(load_safeguards()["safeguards"]))
    identity = next(e for e in entries if e["safeguard_id"] == "SG-IDENTITY-001")
    identity["satisfies"].append(dict(identity["satisfies"][0], control_id="EXTRA"))
    member = {"control_id": "X", "framework_id": "soc2", "role": "equivalent"}
    entries.append({"safeguard_id": "SG-NEW-001", "satisfies": [member] * (FANOUT_CAP + 1)})
    assert fanout_problems(entries) == [
        "SG-IDENTITY-001 satisfies 154 requirements; its ceiling is 153",
        f"SG-NEW-001 satisfies {FANOUT_CAP + 1} requirements; its ceiling is {FANOUT_CAP}",
    ]


def test_ccf_doc_lists_the_broadest_safeguards_from_the_data() -> None:
    from security_lakehouse.safeguards import broadest_safeguards

    doc = (ROOT / "docs/COMMON_CONTROL_FRAMEWORK.md").read_text()
    rows = broadest_safeguards()
    assert [row["safeguard_id"] for row in rows[:3]] == ["SG-IDENTITY-001", "SG-LOGGING-001", "SG-DATAPROTECTION-001"]
    assert rows[0]["requirements"] == 153
    assert rows[0]["frameworks"] > 1
    assert rows[0]["reviewed"] + rows[0]["proposed"] + rows[0]["contextual"] == rows[0]["requirements"]
    from tools.sync_ccf_doc import broadest_table

    from security_lakehouse.safeguards import coverage_by_framework

    block = doc.split("<!-- broadest-safeguards:start -->\n", 1)[1].split("<!-- broadest-safeguards:end -->", 1)[0]
    assert block == broadest_table(coverage_by_framework()), (
        "broadest-safeguards table is stale; run tools/sync_ccf_doc.py"
    )
    for row in rows:
        assert f"`{row['safeguard_id']}`" in block
    assert "a pass on one does not demonstrate each requirement" in doc


def test_ccf_doc_headline_matches_the_cli_safeguards_table(capsys) -> None:
    from security_lakehouse.cli import main

    assert main(["frameworks", "safeguards", "--format", "table"]) == 0
    headline = capsys.readouterr().out.splitlines()[0]
    doc = (ROOT / "docs/COMMON_CONTROL_FRAMEWORK.md").read_text()
    assert headline in doc.splitlines(), "CCF doc headline is stale; run tools/sync_ccf_doc.py"
