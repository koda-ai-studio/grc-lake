"""CCF control families: one governed taxonomy for safeguards."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from security_lakehouse.safeguards import coverage_by_family, load_ccf_families, load_safeguards, validate_safeguards

ROOT = Path(__file__).resolve().parents[1]


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
    # AC and IA legitimately contain many more clauses than other families.
    common = [entry for entry in entries if not entry["safeguard_id"].startswith("SG-NIST53-")]
    used = Counter(entry["risk_domain"] for entry in common)
    total = sum(used.values())
    taxonomy = load_ccf_families()
    for entry in entries:
        if entry["safeguard_id"].startswith("SG-NIST53-"):
            source_id = entry["safeguard_id"].removeprefix("SG-NIST53-")
            assert len(entry["satisfies"]) == 1
            assert entry["satisfies"][0]["control_id"] == "NIST-800-53-" + source_id
            assert source_id.split("-")[0] in taxonomy[entry["risk_domain"]]["nist_800_53_families"]
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
    for row in coverage_by_family():
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
