"""Vendor guidance cannot turn unrelated evidence or proposals into assurance."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards, validate_safeguards
from test_ccf_operational_assessment import normalized

TARGETS = [
    "SOC2-A1.1",
    "SOC2-CC6.4",
    "SOC2-CC6.5",
    "SOC2-CC9.1",
    "SOC2-P6.2",
    "SOC2-P6.3",
    "SOC2-P6.4",
    "SOC2-P6.5",
    "SOC2-P6.6",
    "SOC2-P6.7",
    "ISO27001-A.5.13",
    "ISO27001-A.5.28",
    "ISO27001-A.6.7",
    "ISO27001-A.7.7",
    "ISO27001-A.8.11",
    "ISO27001-A.8.17",
    "ISO27001-A.8.6",
    "ISO42001-10.2",
    "ISO42001-4.6",
    "ISO42001-6.1.3",
    "ISO42001-6.2.8",
    "ISO42001-8.2",
]
ROOT = Path(__file__).resolve().parents[1]
GENERATOR = runpy.run_path(str(ROOT / "tools/sync_soc2_iso_review.py"))
PLAN = json.loads((ROOT / "controls/soc2_iso_review_plan.json").read_text())


@pytest.mark.parametrize("cid", TARGETS)
def test_repaired_requirements_have_one_specific_proposed_contract(cid):
    matches = [(e, m) for e in load_safeguards()["safeguards"] for m in e["satisfies"] if m["control_id"] == cid]
    assert len(matches) == 1
    entry, member = matches[0]
    assert entry["safeguard_id"].startswith("SG-REVIEW-")
    assert len(entry["satisfies"]) == 1
    assert member["role"] == "primary" and member["review_status"] == "proposed"
    assert member["mapping_basis"] == "vendor_guided_proposal"
    assert "not a published equivalence" in member["mapping_source"]["locator"]
    assert entry["required_evidence_types"] == ["review_" + cid.lower().replace("-", "_").replace(".", "_")]
    assert "review_basis" not in member and not entry.get("reviewed_by")


@pytest.mark.parametrize("case", ["missing", "wrong_type", "unbound", "observed", "failed", "stale", "pass"])
def test_repaired_contracts_require_scoped_typed_evidence_and_separate_review(case):
    catalog = load_control_catalog()
    entries = [e for e in load_safeguards()["safeguards"] if e["safeguard_id"].startswith("SG-REVIEW-")]
    assert len(entries) == len(PLAN["repairs"])
    for entry in entries:
        cid = entry["satisfies"][0]["control_id"]
        row = normalized(
            asset_type=entry["asset_types"][0],
            bindings=[] if case == "unbound" else [entry["safeguard_id"]],
            status=case if case in {"observed", "failed"} else "pass",
            control_ids=[cid],
            evidence_types=["generic_control_assessment"] if case == "wrong_type" else entry["required_evidence_types"],
        )
        if case == "stale":
            row.update(event_time="2000-01-01T00:00:00Z", evidence_collected_at="2000-01-01T00:00:00Z")
        rows = [] if case == "missing" else [row]
        payload = {"review_log_verified": True, "safeguards": [entry]}
        result = evaluate_safeguards(rows, payload, {cid: catalog[cid]})
        expected = {"pass": "pass", "failed": "fail", "wrong_type": "stale", "stale": "stale"}.get(
            case, "not_evaluated"
        )
        assert result["safeguards"][0]["status"] == expected
        assert result["requirements"][0]["status"] != "pass"
        reviewed = deepcopy(payload)
        reviewed["safeguards"][0]["satisfies"][0]["effective_review_state"] = "org_reviewed"
        assert evaluate_safeguards(rows, reviewed, {cid: catalog[cid]})["requirements"][0]["status"] == expected


def test_repairs_preserve_distinct_coverage_without_adding_reviews():
    payload = load_safeguards()
    assert validate_safeguards(payload) == []
    coverage = coverage_by_framework(payload)
    assert (coverage["controls"], coverage["covered"], coverage["reviewed"]) == (2252, 1803, 1128)


@pytest.mark.parametrize("framework", GENERATOR["FRAMEWORKS"])
def test_published_packets_bind_current_semantics_and_contain_no_decisions(framework):
    from security_lakehouse.io import canonical_sha256
    from security_lakehouse.mapping_review import list_review_items

    packet = json.loads((ROOT / "docs/reviews" / (framework + "-batches.json")).read_text())
    assert packet["sha256"] == canonical_sha256({k: v for k, v in packet.items() if k != "sha256"})
    current = {(r["safeguard_id"], r["control_id"]): r for r in list_review_items(None)}
    requirements = []
    for group in packet["frameworks"]:
        for batch in group["batches"]:
            assert 1 <= len(batch["requirements"]) <= 10
            assert batch["basis_sha256"] == canonical_sha256(batch["requirements"])
            for row in batch["requirements"]:
                requirements.append(row["control_id"])
                assert row["question"] and row["source_scope"]
                for candidate in row["candidates"]:
                    now = current[candidate["safeguard_id"], row["control_id"]]
                    assert candidate["review_basis_sha256"] == now["review_basis_sha256"]
                    assert candidate["operating_contract"] == now["operating_contract"]
                    assert candidate["decision"] is candidate["reviewer"] is candidate["rationale"] is None
    expected = {
        r["control_id"] for r in current.values() if r["framework_id"] == framework and r["review_state"] == "proposed"
    }
    reviewed = {r["control_id"] for r in current.values() if r["review_state"] == "maintainer_reviewed"}
    assert (
        len(requirements)
        == len(set(requirements))
        == {"soc2": 51, "iso-27001-2022": 71, "iso-42001-2023": 28}[framework]
    )
    assert set(requirements) == expected - reviewed


def source_index():
    return {r["control_id"]: [{"control": f"CCF {n}"} for n in r["cisco_controls"]] for r in PLAN["repairs"]}


def test_generator_is_idempotent_and_does_not_mutate_its_input():
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    before = deepcopy(payload)
    assert GENERATOR["repaired_payload"](payload, PLAN, source_index(), load_control_catalog()) == payload
    assert payload == before


@pytest.mark.parametrize("change", ["approved", "source", "duplicate", "unexpected"])
def test_generator_refuses_to_overwrite_changed_history_or_unrelated_entries(change):
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    plan = deepcopy(PLAN)
    index = source_index()
    entry = next(e for e in payload["safeguards"] if e["safeguard_id"].startswith("SG-REVIEW-"))
    if change == "approved":
        entry["satisfies"][0]["review_status"] = "reviewed"
    elif change == "source":
        index[plan["repairs"][0]["control_id"]] = []
    elif change == "duplicate":
        plan["repairs"].append(deepcopy(plan["repairs"][0]))
    else:
        entry["safeguard_id"] = "SG-REVIEW-UNRELATED"
    before = deepcopy(payload)
    with pytest.raises(ValueError):
        GENERATOR["repaired_payload"](payload, plan, index, load_control_catalog())
    assert payload == before


def test_source_digest_mismatch_is_rejected():
    with pytest.raises(ValueError, match="source hash differs"):
        GENERATOR["verify_source"](b"changed source", PLAN["sources"]["cisco"])


def test_repair_preserves_every_existing_operating_contract_and_other_mapping():
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    payload["safeguards"] = [e for e in payload["safeguards"] if not e["safeguard_id"].startswith("SG-REVIEW-")]
    old_entries = {e["safeguard_id"]: e for e in payload["safeguards"]}
    removed = set()
    for repair in PLAN["repairs"]:
        for old in repair["replaces"]:
            old_entries[old["safeguard_id"]]["satisfies"].append(deepcopy(old["member"]))
            removed.add((old["safeguard_id"], repair["control_id"]))
    result = GENERATOR["repaired_payload"](payload, PLAN, source_index(), load_control_catalog())
    for entry in result["safeguards"]:
        old = old_entries.get(entry["safeguard_id"])
        if old is None:
            continue
        assert {k: v for k, v in entry.items() if k != "satisfies"} == {
            k: v for k, v in old.items() if k != "satisfies"
        }
        assert entry["satisfies"] == [
            m for m in old["satisfies"] if (old["safeguard_id"], m["control_id"]) not in removed
        ]


def test_repaired_proposals_are_not_exported_as_implemented_requirements():
    from security_lakehouse.oscal import build_component_definition

    components = build_component_definition()["component-definition"]["components"]
    repaired = [
        c
        for c in components
        if any(p["name"] == "trustops-safeguard-id" and p["value"].startswith("SG-REVIEW-") for p in c["props"])
    ]
    assert len(repaired) == len(PLAN["repairs"])
    assert all("control-implementations" not in c for c in repaired)


def test_repair_refuses_a_new_human_decision_on_an_old_mapping():
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    repair = PLAN["repairs"][0]
    payload["safeguards"] = [
        e for e in payload["safeguards"] if e["safeguard_id"] != "SG-REVIEW-" + repair["control_id"].replace(".", "-")
    ]
    old = repair["replaces"][0]
    owner = next(e for e in payload["safeguards"] if e["safeguard_id"] == old["safeguard_id"])
    member = deepcopy(old["member"])
    member["review_status"] = "reviewed"
    owner["satisfies"].append(member)
    with pytest.raises(ValueError, match="refusing to replace unexpected or reviewed mapping"):
        GENERATOR["repaired_payload"](payload, PLAN, source_index(), load_control_catalog())


def test_cisco_parser_uses_current_explicit_ids_not_old_columns_or_markers():
    import hashlib
    import io
    import zipfile

    ns = GENERATOR["NS"]["s"]
    strings = ["CCF 335", "5.13", "X", "CC6.4; CC6.4", "A1.1", "P6.2", "C1.1", "A.8.6", "8.6.1"]
    cells = {"C": 0, "BH": 1, "BA": 2, "BD": 3, "BE": 4, "BC": 5, "BF": 6, "BI": 7}
    row = "".join(f'<c r="{col}2" t="s"><v>{value}</v></c>' for col, value in cells.items())
    book = io.BytesIO()
    with zipfile.ZipFile(book, "w") as z:
        z.writestr(
            "xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>"
        )
        z.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="CCF V4" r:id="r1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData><row r="2">{row}</row><row r="3"><c r="C3" t="s"><v>0</v></c><c r="BI3" t="s"><v>8</v></c><c r="BD3" t="s"><v>2</v></c></row></sheetData></worksheet>',
        )
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("cisco-ccf-v4.xlsx", book.getvalue())
    pin = {
        "name": "test fixture",
        "sha256": hashlib.sha256(outer.getvalue()).hexdigest(),
        "workbook_sha256": hashlib.sha256(book.getvalue()).hexdigest(),
    }
    index = GENERATOR["cisco_index"](outer.getvalue(), pin)
    assert set(index) == {"SOC2-CC6.4", "SOC2-A1.1", "SOC2-P6.2", "SOC2-C1.1", "ISO27001-A.8.6"}
    assert len(index["SOC2-CC6.4"]) == 1
    assert index["ISO27001-A.8.6"][0]["cell"] == "BI2"


GOVERNANCE_TARGETS = (
    "SOC2-CC1.1",
    "SOC2-CC1.2",
    "SOC2-CC1.4",
    "SOC2-CC1.5",
    "SOC2-CC2.1",
    "SOC2-CC2.2",
    "SOC2-CC2.3",
    "SOC2-CC3.1",
    "SOC2-CC4.2",
    "SOC2-CC5.1",
    "SOC2-CC5.2",
    "SOC2-CC5.3",
)


@pytest.mark.parametrize("cid", GOVERNANCE_TARGETS)
def test_soc2_governance_requires_its_own_assessment_not_a_cmmc_plan(cid):
    payload = load_safeguards()
    owners = [e for e in payload["safeguards"] if any(m["control_id"] == cid for m in e["satisfies"])]
    assert "SG-GOVERNANCE-002" not in {e["safeguard_id"] for e in owners}
    entry = next(e for e in owners if e["safeguard_id"] == "SG-REVIEW-" + cid.replace(".", "-"))
    assert len(entry["satisfies"]) == 1
    assert entry["satisfies"][0]["review_status"] == "proposed"
    assert entry["required_evidence_types"] == ["review_" + cid.lower().replace("-", "_").replace(".", "_")]
    row = normalized(
        asset_type=entry["asset_types"][0],
        bindings=[entry["safeguard_id"]],
        status="pass",
        control_ids=[cid],
        evidence_types=["system_security_plan"],
    )
    result = evaluate_safeguards(
        [row], {"review_log_verified": True, "safeguards": [entry]}, {cid: load_control_catalog()[cid]}
    )
    assert result["safeguards"][0]["status"] != "pass"
    assert result["requirements"][0]["status"] != "pass"
