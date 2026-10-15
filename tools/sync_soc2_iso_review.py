"""Reproduce proposed repairs and review packets from pinned vendor guidance.

The input files remain local. Published artifacts contain source locators and
original GRC Lake assessment designs, not vendor control narratives.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy
from pathlib import Path

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.catalog_versions import write_bundle_lock
from security_lakehouse.io import canonical_sha256
from security_lakehouse.mapping_review_packet import build_review_packet
from security_lakehouse.safeguards import load_safeguards, validate_safeguards

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "controls/soc2_iso_review_plan.json"
PREFIX = "SG-REVIEW-"
FRAMEWORKS = ("soc2", "iso-27001-2022", "iso-42001-2023")
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def verify_source(raw: bytes, pin: dict) -> None:
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError(f"source hash differs: {pin['name']}")


def cisco_index(raw: bytes, pin: dict) -> dict:
    """Read explicit target IDs only, never infer equivalence from an X marker."""
    verify_source(raw, pin)
    with zipfile.ZipFile(io.BytesIO(raw)) as outer:
        book = outer.read("cisco-ccf-v4.xlsx")
    if hashlib.sha256(book).hexdigest() != pin["workbook_sha256"]:
        raise ValueError("Cisco workbook hash differs")
    with zipfile.ZipFile(io.BytesIO(book)) as archive:
        strings = [
            "".join(t.text or "" for t in s.findall(".//s:t", NS))
            for s in ET.fromstring(archive.read("xl/sharedStrings.xml"))
        ]
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        sheets = ET.fromstring(archive.read("xl/workbook.xml")).find("s:sheets", NS)
        sheet = next(s for s in sheets if s.attrib["name"] == "CCF V4")
        target = rels[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        rows = ET.fromstring(archive.read(target)).findall(".//s:sheetData/s:row", NS)
        index: dict[str, list] = {}
        for row in rows:
            cells = {}
            for cell in row.findall("s:c", NS):
                value = cell.find("s:v", NS)
                if value is not None:
                    cells[re.sub(r"\d", "", cell.attrib["r"])] = (
                        strings[int(value.text)] if cell.attrib.get("t") == "s" else value.text
                    )
            if not re.fullmatch(r"CCF \d+", str(cells.get("C", ""))):
                continue
            for column in ("BC", "BD", "BE", "BF", "BI"):
                text = str(cells.get(column) or "")
                pattern = (
                    r"(?<![\w.])(?:A\.)?([5-8]\.\d+)(?![\w.])"
                    if column == "BI"
                    else r"(?<![\w.])((?:CC|A|C|P)[ \t]*\d+\.\d+)(?![\w.])"
                )
                # Cisco uses both CC1.3 and CC 1.3. Normalize only horizontal
                # spacing within an explicit identifier, before deduplication.
                refs = {re.sub(r"[ \t]+", "", ref) for ref in re.findall(pattern, text)}
                for ref in sorted(refs):
                    cid = "ISO27001-A." + ref if column == "BI" else "SOC2-" + ref
                    index.setdefault(cid, []).append(
                        {
                            "control": cells["C"],
                            "cell": column + row.attrib["r"],
                            "narrative_lookup": "Control Narrative RFI, column B=" + cells["C"],
                        }
                    )
    return index


def repaired_payload(payload: dict, plan: dict, index: dict, catalog: dict) -> dict:
    targets = [r["control_id"] for r in plan["repairs"]]
    if len(targets) != len(set(targets)):
        raise ValueError("duplicate repair target")
    expected_ids = {PREFIX + cid.replace(".", "-") for cid in targets}
    existing_ids = [e["safeguard_id"] for e in payload["safeguards"] if e["safeguard_id"].startswith(PREFIX)]
    if len(existing_ids) != len(set(existing_ids)) or set(existing_ids) - expected_ids:
        raise ValueError("unexpected or duplicate generated safeguard")
    result = deepcopy(payload)
    generated = []
    for repair in plan["repairs"]:
        cid = repair["control_id"]
        control = catalog[cid]
        source = plan["sources"][repair["source"]]
        if repair["source"] == "cisco":
            available = {r["control"] for r in index.get(cid, [])}
            if not {f"CCF {n}" for n in repair["cisco_controls"]} <= available:
                raise ValueError(f"Cisco source does not cite target {cid}")
        evidence_type = "review_" + cid.lower().replace("-", "_").replace(".", "_")
        entry = {
            "safeguard_id": PREFIX + cid.replace(".", "-"),
            "title": control["title"],
            "risk_domain": repair["risk_domain"],
            "objective": repair["objective"],
            "evidence_requirement": (
                "A scoped assessor record, explicitly bound to this safeguard and asset, must identify the assessor, "
                "assessment period, population, applicability, evidence references, tests and exceptions. "
                "Examine and test " + repair["evidence_checks"] + ". "
                "Record unmet checks and remaining uncertainty. A sampled pass does not establish population completeness. "
                "An imported pass flag does not verify these checks or approve the mapping."
            ),
            "evaluation_rule": "fail_when_open_violation_or_stale_evidence",
            "frequency": "documented assessment schedule and after material change",
            "owner": "security-assurance",
            "reviewed_by": None,
            "reviewed_at": None,
            "asset_types": sorted(set(control["asset_types"])),
            "required_evidence_types": [evidence_type],
            "satisfies": [
                {
                    "control_id": cid,
                    "framework_id": control["framework_id"],
                    "role": "primary",
                    "control_version": control["version"],
                    "review_status": "proposed",
                    "mapping_basis": "vendor_guided_proposal",
                    "mapping_source": {k: source[k] for k in ("name", "url", "sha256")}
                    | {"locator": repair["source_locator"] + "; " + repair["source_limit"]},
                }
            ],
        }
        existing = next((e for e in result["safeguards"] if e["safeguard_id"] == entry["safeguard_id"]), None)
        if existing is not None and existing != entry:
            raise ValueError(f"refusing to overwrite changed or reviewed contract: {cid}")
        for old in repair["replaces"]:
            owner = next(e for e in result["safeguards"] if e["safeguard_id"] == old["safeguard_id"])
            matches = [m for m in owner["satisfies"] if m["control_id"] == cid]
            if not matches and existing is not None:
                continue
            if (
                matches != [old["member"]]
                or matches[0]["review_status"] != "proposed"
                or matches[0]["role"] == "primary"
            ):
                raise ValueError(f"refusing to replace unexpected or reviewed mapping: {cid}")
            owner["satisfies"].remove(matches[0])
            # Removing a proposed relationship must not change the operated
            # scope or invalidate reviews of other mappings on this safeguard.
        generated.append(entry)
    result["safeguards"] = [e for e in result["safeguards"] if not e["safeguard_id"].startswith(PREFIX)] + generated
    problems = validate_safeguards(result)
    if problems:
        raise ValueError("; ".join(problems))
    return result


def review_artifacts(payload: dict, plan: dict, index: dict) -> tuple[dict, str]:
    # Apply the same version and inheritance annotations as the runtime loader.
    # Hashing raw JSON would produce fingerprints that the review API rejects.
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory) / "safeguards.json"
        staged.write_text(json.dumps(payload))
        runtime_payload = load_safeguards(staged)
    questions = json.loads((ROOT / "controls/soc2_iso_review_questions.json").read_text())
    repairs = {r["control_id"]: r for r in plan["repairs"]}
    packets = []
    lines = [
        "# SOC 2 and ISO mapping review batches",
        "",
        "Generated by `tools/sync_soc2_iso_review.py`. These are new review proposals; no decision is preselected. Prior approval of the NIST/source batches does not approve these mappings.",
        "",
        "Cisco CCF 4.0 supplies candidate control references and implementation/audit guidance. Oracle supplies implementation context for AI governance, not an ISO Annex A crosswalk. Neither publisher has approved GRC Lake mappings. References must be checked against each proposed operating contract and the applicable requirement before approval.",
        "",
        "The three JSON companions contain exact candidate fingerprints, operating contracts, source pins, questions, and empty decision fields. Record decisions against those fingerprints. Regenerate after any semantic change.",
        "",
        "- [SOC 2 candidates](soc2-batches.json)",
        "- [ISO 27001 candidates](iso-27001-2022-batches.json)",
        "- [ISO 42001 candidates](iso-42001-2023-batches.json)",
        "",
        "## Review scope and reproduction",
        "",
        f"This queue contains 150 requirements and 185 candidate relationships in 17 batches: SOC 2 (51 requirements), ISO 27001 (71), and ISO 42001 (28). {len(plan['repairs'])} requirement-specific assessment contracts replace {sum(len(r['replaces']) for r in plan['repairs'])} weak proposed relationships. Mapped and reviewed requirement counts are unchanged; every new contract remains proposed.",
        "",
        "Cisco references use explicit SOC 2 IDs and the ISO/IEC 27002:2022 column corresponding to ISO 27001:2022 Annex A. Older ISO columns and broad X markers are excluded. Processing Integrity requirements without a Cisco reference stay explicitly unsourced. Oracle articles provide AI governance examples; they do not supply the complete ISO 42001 requirement text. Fifteen unmapped ISO requirements remain outside this pending-mapping queue.",
        "",
        "Download the pinned source URLs below into a local directory as `cisco-ccf-v4.zip`, `oracle-practice.html`, and `oracle-risk.html`. The generator checks both the ZIP and workbook hashes and both HTML hashes; a changed source requires inspection and a deliberate pin update. Vendor source files are not committed.",
        "",
        "```sh",
        "PYTHONPATH=src uv run python tools/sync_soc2_iso_review.py --source-dir /path/to/sources --check",
        "```",
        "",
        "Omit `--check` to regenerate. JSON verification compares parsed content, so repository formatting does not change the review basis. The generator refuses to overwrite changed or reviewed contracts. Record actual reviewer decisions through the [mapping review workflow](../MAPPING_REVIEW.md), with requirement references, rationale, limits and evidence; empty fields here are not approvals.",
        "",
        "## Sources",
        "",
    ]
    for key, source in plan["sources"].items():
        lines.append(f"- [{source['name']}]({source['url']}), SHA-256 `{source['sha256']}`. Key: `{key}`.")
    lines += ["", "## Repaired proposals", ""]
    for repair in plan["repairs"]:
        old_ids = ", ".join(f"`{old['safeguard_id']}`" for old in repair["replaces"])
        lines.append(
            f"- **{repair['control_id']}**: replace the proposed links from {old_ids} with `{PREFIX + repair['control_id'].replace('.', '-')}`."
        )
    lines += [
        "",
        "All other mappings and existing operating contracts are preserved, including the semantics bound to earlier human review receipts. These replacements do not supply evidence or approve an equivalence.",
    ]
    for framework in FRAMEWORKS:
        packet = build_review_packet(payload=runtime_payload, framework_id=framework, batch_size=10)
        batches = []
        lines += ["", f"## {framework}", ""]
        for batch in packet["batches"]:
            bid = framework + "-" + batch["batch_id"]
            rows = []
            lines += [f"### {bid}", ""]
            for requirement in batch["requirements"]:
                cid = requirement["control_id"]
                repair = repairs.get(cid)
                question = (
                    ("Repaired proposal: verify " + repair["evidence_checks"] + ". " + repair["source_limit"])
                    if repair
                    else questions[cid]
                )
                references = index.get(cid, [])
                candidates = [
                    {
                        k: c[k]
                        for k in (
                            "safeguard_id",
                            "role",
                            "review_state",
                            "review_basis_sha256",
                            "operating_contract",
                            "mapping_source",
                        )
                    }
                    | {"decision": None, "reviewer": None, "rationale": None}
                    for c in requirement["candidates"]
                ]
                row = {
                    "control_id": cid,
                    "framework_ref": requirement["requirement"]["framework_ref"],
                    "question": question,
                    "cisco_candidates": references,
                    "source_scope": "vendor implementation context, not verified normative equivalence"
                    if references or framework == "iso-42001-2023"
                    else "no target-specific vendor reference found",
                    "oracle_context": ["oracle-practice", "oracle-risk"] if framework == "iso-42001-2023" else [],
                    "candidates": candidates,
                }
                rows.append(row)
                refs = ", ".join(f"{r['control']} ({r['cell']})" for r in references) or (
                    "Oracle implementation context; no published clause crosswalk"
                    if framework == "iso-42001-2023"
                    else "No target-specific vendor reference found"
                )
                lines += [
                    f"**{cid}** — {requirement['control_title']}",
                    "",
                    "Candidates: " + ", ".join(f"`{c['safeguard_id']}`" for c in candidates) + ".",
                    "",
                    question,
                    "",
                    "Source locators: " + refs + ".",
                    "",
                ]
            batches.append({"batch_id": bid, "basis_sha256": canonical_sha256(rows), "requirements": rows})
        packets.append({"framework_id": framework, "batches": batches})
    body = {"schema": "grc_lake.vendor_review_batches.v1", "sources": plan["sources"], "frameworks": packets}
    return body | {"sha256": canonical_sha256(body)}, re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    plan = json.loads(PLAN.read_text())
    index = cisco_index((args.source_dir / "cisco-ccf-v4.zip").read_bytes(), plan["sources"]["cisco"])
    for source in ("oracle-practice", "oracle-risk"):
        verify_source((args.source_dir / (source + ".html")).read_bytes(), plan["sources"][source])
    path = ROOT / "controls/safeguards.json"
    original = json.loads(path.read_text())
    payload = repaired_payload(original, plan, index, load_control_catalog())
    packet, markdown = review_artifacts(payload, plan, index)
    outputs = {
        path: json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        ROOT / "docs/reviews/SOC2_ISO_REVIEW.md": markdown,
    }
    for framework in packet["frameworks"]:
        body = {"schema": packet["schema"], "sources": packet["sources"], "frameworks": [framework]}
        artifact = body | {"sha256": canonical_sha256(body)}
        outputs[ROOT / "docs/reviews" / (framework["framework_id"] + "-batches.json")] = (
            json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
        )
    for target, content in outputs.items():
        if args.check:
            matches = (
                json.loads(target.read_text()) == json.loads(content)
                if target.suffix == ".json"
                else target.read_text() == content
            )
            if not matches:
                raise ValueError(f"generated artifact drift: {target.name}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    if not args.check:
        write_bundle_lock()
    print(
        f"Verified {len(plan['repairs'])} proposed repairs and {sum(len(f['batches']) for f in packet['frameworks'])} review batches"
    )


if __name__ == "__main__":
    main()
