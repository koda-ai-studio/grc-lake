"""Build proposed, obligation-specific NIST safeguards from a pinned OSCAL catalog.

No title matching or cross-framework equivalence inference is performed. Each
selected obligation receives its own assessment evidence type. Run with the
official catalog bytes named in controls/nist53_assessment_expansion.json:

    PYTHONPATH=src python tools/sync_nist53_assessment_safeguards.py --source catalog.json
    PYTHONPATH=src python tools/sync_nist53_assessment_safeguards.py --source catalog.json --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.safeguards import load_ccf_families

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "controls/nist53_assessment_expansion.json"
SAFEGUARDS_PATH = ROOT / "controls/safeguards.json"
PREFIX = "SG-NIST53-"
PARAM = re.compile(r"\{\{\s*insert:\s*param,\s*([^}]+?)\s*\}\}")


def flatten(parts: list[dict[str, Any]]) -> list[str]:
    lines = []
    for part in parts:
        if part.get("prose"):
            lines.append(str(part["prose"]))
        lines.extend(flatten(part.get("parts", [])))
    return lines


def source_controls(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    controls: dict[str, Any] = {}
    params: dict[str, Any] = {}

    def walk(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            key = row["id"].upper()
            if key in controls:
                raise ValueError(f"duplicate source control {key}")
            controls[key] = row
            for param in row.get("params", []):
                if param["id"] in params and params[param["id"]] != param:
                    raise ValueError(f"conflicting source parameter {param['id']}")
                params[param["id"]] = param
            walk(row.get("controls", []))

    for group in source["catalog"]["groups"]:
        walk(group.get("controls", []))
    return controls, params


def resolve(text: str, params: dict[str, Any]) -> str:
    def replacement(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in params:
            raise ValueError(f"unresolved source parameter {key}")
        param = params[key]
        choices = param.get("select", {}).get("choice", [])
        selection = param.get("select", {})
        label = param.get("label") or (
            f"select {selection.get('how-many', 'one')} from: " + "; ".join(map(str, choices)) if choices else ""
        )
        if not label:
            raise ValueError(f"source parameter has no definition: {key}")
        return f"[organization-defined {key}: {label}]"

    for _ in range(8):
        if not PARAM.search(text):
            break
        text = PARAM.sub(replacement, text)
    if "{{" in text:
        raise ValueError("unresolved or cyclic source insertion")
    return text


def build_entries(raw: bytes, plan: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    pin = plan["source"]
    if hashlib.sha256(raw).hexdigest() != pin["catalog_sha256"]:
        raise ValueError("source catalog SHA-256 does not match the pinned manifest")
    source = json.loads(raw)
    if source["catalog"]["metadata"]["version"] != pin["version"]:
        raise ValueError("source catalog version does not match the pinned manifest")
    controls, params = source_controls(source)
    selected = plan["control_ids"]
    if len(set(selected)) != len(selected):
        raise ValueError("duplicate expansion target")
    overrides = plan.get("control_families", {})
    if set(overrides) - set(selected):
        raise ValueError("family override names an unknown expansion target")
    if plan.get("coverage_scope") == "all_active_controls":
        active = {
            cid
            for cid, control in controls.items()
            if not any(p.get("name") == "status" and p.get("value") == "withdrawn" for p in control.get("props", []))
        }
        if set(selected) != active:
            raise ValueError("complete expansion must contain exactly the active source controls")
        catalog_ids = {cid for cid, control in catalog.items() if control["framework_id"] == "nist-800-53-rev5"}
        if catalog_ids != {"NIST-800-53-" + cid for cid in active}:
            raise ValueError("catalog does not match the active source controls")
    url = (
        f"https://raw.githubusercontent.com/usnistgov/oscal-content/{pin['oscal_commit']}"
        f"/nist.gov/SP800-53/rev5/json/{pin['catalog_file']}"
    )
    entries = []
    taxonomy = load_ccf_families()
    for control_id in selected:
        family = control_id.split("-")[0]
        risk_domain = overrides.get(control_id, plan["families"][family])
        if family not in taxonomy.get(risk_domain, {}).get("nist_800_53_families", []):
            raise ValueError(f"source family {family} is not governed by CCF family {risk_domain}")
        source_control = controls[control_id]
        if any(p.get("name") == "status" and p.get("value") == "withdrawn" for p in source_control.get("props", [])):
            raise ValueError(f"withdrawn expansion target: {control_id}")
        cid = "NIST-800-53-" + control_id
        control = catalog[cid]
        if control["framework_id"] != "nist-800-53-rev5":
            raise ValueError(f"catalog framework mismatch: {cid}")
        parts = source_control["parts"]
        statements = flatten([p for p in parts if p["name"] == "statement"])
        objectives = flatten([p for p in parts if p["name"] == "assessment-objective"])
        methods = [
            ", ".join(str(prop["value"]) for prop in part.get("props", []) if prop.get("name") == "method")
            + ":\n"
            + "\n".join(flatten(part.get("parts", [])))
            for part in parts
            if part["name"] == "assessment-method"
        ]
        if not statements or not objectives or not methods:
            raise ValueError(f"incomplete source assessment contract: {cid}")
        required = [link["href"] for link in source_control.get("links", []) if link.get("rel") == "required"]
        evidence_type = "nist53_" + control_id.lower().replace("-", "_").replace(".", "_") + "_assessment"
        definition = resolve("\n".join(statements), params)
        assessment = resolve("\n".join(objectives), params)
        objects = resolve("\n".join(methods), params)
        dependencies = ", ".join(required) or "none listed by the source"
        entries.append(
            {
                "safeguard_id": PREFIX + control_id,
                "title": f"{control_id}: {source_control['title']}",
                "risk_domain": risk_domain,
                "objective": f"Operate {control_id} within its defined system and population scope. Source statement:\n{definition}",
                "evidence_requirement": (
                    f"A scoped assessor record of type {evidence_type}, explicitly bound to this safeguard and asset, "
                    "must identify the assessor, assessment period, evidence references, applicability and all organization-defined "
                    "parameter values. The assessor must establish each objective and prerequisite; an imported pass flag alone "
                    "does not establish semantic completeness.\n"
                    f"Required source dependencies: {dependencies}.\nAssessment objectives:\n{assessment}\n"
                    f"Source assessment objects (examine, interview or test as applicable):\n{objects}"
                ),
                "evaluation_rule": "fail_when_open_violation_or_stale_evidence",
                "frequency": "organization-defined assessment schedule and after material change",
                "owner": "security-assurance",
                "reviewed_by": None,
                "reviewed_at": None,
                "asset_types": sorted(set(control["asset_types"])),
                "required_evidence_types": [evidence_type],
                "satisfies": [
                    {
                        "control_id": cid,
                        "framework_id": "nist-800-53-rev5",
                        "role": "primary",
                        "review_status": "proposed",
                        "control_version": control["version"],
                        "mapping_source": {
                            "name": pin["name"],
                            "url": url,
                            "sha256": pin["catalog_sha256"],
                            "locator": f"control {source_control['id']}; statement, parameters, assessment-objective and assessment-method parts",
                        },
                    }
                ],
            }
        )
    return entries


def source_contract(entry: dict) -> dict:
    """Compare source semantics while preserving separately recorded human decisions."""
    contract = deepcopy(entry)
    for member in contract["satisfies"]:
        member["review_status"] = "proposed"
        for field in ("maintainer_review_ref", "reviewed_by", "reviewed_at"):
            member.pop(field, None)
    return contract


def reconcile_entries(existing: list[dict], generated: list[dict]) -> list[dict]:
    """Extend source contracts without changing the basis of a human decision.

    Exact existing contracts retain their review metadata. A reviewed contract
    may neither disappear nor change through source regeneration; that requires
    explicit reconciliation of its review basis outside this generator.
    """
    old = {entry["safeguard_id"]: entry for entry in existing}
    new = {entry["safeguard_id"]: entry for entry in generated}
    if len(old) != len(existing) or len(new) != len(generated):
        raise ValueError("duplicate NIST assessment safeguard")

    def same_contract(before: dict, after: dict) -> bool:
        contract = source_contract(before)
        # Display grouping is outside the semantic definition/review digest.
        if "risk_domain" in contract and "risk_domain" in after:
            contract["risk_domain"] = after["risk_domain"]
        return contract == after

    for sid, entry in old.items():
        reviewed = bool(entry.get("reviewed_by") or entry.get("reviewed_at")) or any(
            member.get("review_status") != "proposed"
            or any(member.get(field) for field in ("reviewed_by", "reviewed_at", "maintainer_review_ref"))
            for member in entry["satisfies"]
        )
        if reviewed and (sid not in new or not same_contract(entry, new[sid])):
            raise ValueError(f"refusing to change or remove reviewed contract: {sid}")
    reconciled = []
    for entry in generated:
        previous = old.get(entry["safeguard_id"])
        if previous is not None and same_contract(previous, entry):
            retained = deepcopy(previous)
            if "risk_domain" in entry:
                retained["risk_domain"] = entry["risk_domain"]
            reconciled.append(retained)
        else:
            reconciled.append(deepcopy(entry))
    return reconciled


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    plan = json.loads(PLAN_PATH.read_text())
    entries = build_entries(args.source.read_bytes(), plan, load_control_catalog())
    payload = json.loads(SAFEGUARDS_PATH.read_text())
    existing = [e for e in payload["safeguards"] if e["safeguard_id"].startswith(PREFIX)]
    if args.check:
        if [source_contract(entry) for entry in existing] != entries:
            raise SystemExit("NIST assessment safeguards differ from their pinned source")
    else:
        merged = reconcile_entries(existing, entries)
        # Keep this generated group at its existing position so regenerating
        # other contract groups does not continually reorder the catalog.
        position = next(
            (i for i, entry in enumerate(payload["safeguards"]) if entry["safeguard_id"].startswith(PREFIX)),
            len(payload["safeguards"]),
        )
        others = [entry for entry in payload["safeguards"] if not entry["safeguard_id"].startswith(PREFIX)]
        payload["safeguards"] = others[:position] + merged + others[position:]
        SAFEGUARDS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"Verified {len(entries)} obligation-specific source contracts against the pinned NIST source")


if __name__ == "__main__":
    main()
