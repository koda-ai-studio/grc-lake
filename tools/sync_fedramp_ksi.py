"""Replay the bounded KSI proposal from retained, digest-pinned official sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.catalog_versions import write_bundle_lock

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "controls/fedramp_ksi_assessment_plan.json"
SOURCE = ROOT / "frameworks/packs/sources/fedramp-2026/rules.json"
SOURCE_SCHEMA = SOURCE.with_name("schema.json")
MANIFEST = ROOT / "frameworks/packs/data/fedramp_ksi_2026.json"


def build_manifest(raw: bytes, schema_raw: bytes, plan: dict[str, Any]) -> dict[str, Any]:
    pin = plan["source"]
    if (
        hashlib.sha256(raw).hexdigest() != pin["sha256"]
        or hashlib.sha256(schema_raw).hexdigest() != pin["schema_sha256"]
    ):
        raise ValueError("FedRAMP source or schema digest mismatch")
    source, schema = json.loads(raw), json.loads(schema_raw)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(source)
    if source["info"]["version"] != pin["version"]:
        raise ValueError("FedRAMP source version mismatch")
    indicators = {cid: value for theme in source["KSI"].values() for cid, value in theme["indicators"].items()}
    ids = [r["id"] for r in plan["rows"]]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("KSI scope requires distinct identifiers")
    rows = []
    for proposal in plan["rows"]:
        cid = proposal["id"]
        if cid not in indicators:
            raise ValueError(f"unknown KSI source identifier: {cid}")
        theme = source["KSI"][cid.split("-")[1]]
        if theme["status"] != "stable":
            raise ValueError("KSI source status requires explicit reconciliation")
        indicator = indicators[cid]
        requirement = (
            "An explicitly bound, scoped assessor record must identify the assessor, tenant and service boundary, "
            "source revision, assessment period, population reconciliation, applicability decision, evidence references, "
            "methods, outcomes and exceptions. " + proposal["evidence_checks"] + " "
            "Record measure objectives, the documented cycle and interruptions for persistent measures, verification "
            "of automation accuracy and sufficiency (or why automation is unnecessary), and validation that measures "
            "are operating as intended. Missing evidence or unknown applicability blocks a conclusion. "
            "This is an assessor assertion, not an automated demonstration of the indicator or independent approval. "
            "A snapshot cannot establish persistent performance."
        )
        rows.append(
            {
                **proposal,
                "title": indicator["name"],
                "statement": indicator["statement"],
                "source_status": theme["status"],
                "source_updated": indicator["updated"],
                "related_nist_controls": indicator.get("controls", []),
                "evidence_requirement": requirement,
                "required_evidence_types": [cid.lower().replace("-", "_") + "_assessment"],
            }
        )
    return {
        "schema": "trustops.framework_pack_manifest.v1",
        "source": deepcopy(pin),
        "scope": plan["scope"],
        "source_indicator_count": len(indicators),
        "selected_indicator_ids": ids,
        "not_seeded": sorted(set(indicators) - set(ids)),
        "default_artifacts": source["info"]["default_artifacts"]["KSI"],
        "applicability": {
            "decision": "not_automatically_determined",
            "boundary": "Review source rules, certification type/path, service class, effective dates and Minimum Assessment Scope before selecting these indicators. Process rules below are context, not implemented controls.",
            "class_a_context": source["FRR"]["FRC"]["data"]["all"]["CLA"]["FRC-CLA-MFR"],
            "scope_context": source["FRR"]["FRC"]["data"]["20x"]["CSX"]["FRC-CSX-MAS"],
            "automation_context": source["FRR"]["FRC"]["data"]["20x"]["CSX"]["FRC-CSX-VVK"],
            "document_context": source["FRR"]["FRC"]["info"],
        },
        "rows": rows,
    }


def build_entries(manifest: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for row in manifest["rows"]:
        cid, source = row["id"], manifest["source"]
        if catalog[cid]["framework_id"] != "fedramp-ksi-2026" or catalog[cid]["version"] != source["version"]:
            raise ValueError("KSI catalog identity/version requires explicit reconciliation")
        entries.append(
            {
                "safeguard_id": "SG-" + cid,
                "title": row["title"],
                "risk_domain": row["risk_domain"],
                "objective": row["statement"],
                "evidence_requirement": row["evidence_requirement"]
                + " Expected failure modes: "
                + row["failure_modes"],
                "evaluation_rule": "fail_when_open_violation_or_stale_evidence",
                "frequency": "documented assessment cycle and after material change",
                "owner": "security-assurance",
                "reviewed_by": None,
                "reviewed_at": None,
                "asset_types": ["service"],
                "required_evidence_types": row["required_evidence_types"],
                "satisfies": [
                    {
                        "control_id": cid,
                        "framework_id": "fedramp-ksi-2026",
                        "role": "primary",
                        "review_status": "proposed",
                        "control_version": source["version"],
                        "mapping_basis": "internal_assessment_proposal",
                        "mapping_source": {
                            "name": source["name"],
                            "url": source["url"],
                            "sha256": source["sha256"],
                            "locator": f"KSI.IAM.indicators.{cid}; info.default_artifacts.KSI. "
                            + row["mapping_rationale"],
                        },
                    }
                ],
            }
        )
    return entries


def updated_payload(payload: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    existing = {row["safeguard_id"]: row for row in payload["safeguards"]}
    for entry in entries:
        sid = entry["safeguard_id"]
        if sid in existing and existing[sid] != entry:
            raise ValueError(f"existing KSI contract changed; explicit reconciliation required: {sid}")
        existing[sid] = entry
    return {**payload, "safeguards": list(existing.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest(SOURCE.read_bytes(), SOURCE_SCHEMA.read_bytes(), json.loads(PLAN.read_text()))
    if MANIFEST.exists() and json.loads(MANIFEST.read_text()) != manifest:
        raise ValueError("KSI manifest changed; explicit source/version reconciliation required")
    if args.check:
        assert json.loads(MANIFEST.read_text()) == manifest
    else:
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        from security_lakehouse.framework_packs import sync_framework_packs

        sync_framework_packs(packs=["fedramp-ksi"])
    path = ROOT / "controls/safeguards.json"
    before = json.loads(path.read_text())
    after = updated_payload(before, build_entries(manifest, load_control_catalog()))
    if args.check and before != after:
        raise ValueError("KSI safeguards are not synchronized")
    if not args.check and before != after:
        path.write_text(json.dumps(after, indent=2, ensure_ascii=False) + "\n")
        write_bundle_lock()
    print(
        f"Verified {len(manifest['rows'])} of {manifest['source_indicator_count']} KSI source indicators; mappings remain proposed"
    )


if __name__ == "__main__":
    main()
