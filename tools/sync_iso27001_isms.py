"""Generate proposed ISMS safeguards after verifying the retained public preview.

Run the iso-27001-isms framework pack sync first. Source bytes remain outside
the repository; no licensed requirement text is copied into the contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.catalog_versions import write_bundle_lock

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "frameworks/packs/data/iso_27001_isms_2022.json"


def verify_source(data: bytes, manifest: dict[str, Any], clause_data: bytes) -> None:
    if hashlib.sha256(data).hexdigest() != manifest["source"]["preview_sha256"]:
        raise ValueError("ISMS public preview does not match the pinned source")
    if hashlib.sha256(clause_data).hexdigest() != manifest["references"][0]["sha256"]:
        raise ValueError("ISMS clause 6.3 reference does not match the pinned source")


def build_entries(manifest: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows = manifest["rows"]
    ids = [row["id"] for row in rows]
    if len(ids) != 30 or len(set(ids)) != len(ids):
        raise ValueError("ISMS manifest requires 30 distinct leaf clause identifiers")
    if any(a != b and b.startswith(a + ".") for a in ids for b in ids):
        raise ValueError("ISMS manifest must not count parent headings with their children")
    entries = []
    for row in rows:
        cid = "ISO27001-" + row["id"]
        control = catalog[cid]
        if control["framework_id"] != "iso-27001-isms-2022":
            raise ValueError("ISMS clause belongs to an unexpected framework")
        if not row["evidence_checks"] or len(row["required_evidence_types"]) != 1:
            raise ValueError("ISMS clause requires its own assessment contract")
        source = manifest["source"]
        # 6.3 is confirmed by NEN, not present in the retained contents preview.
        citation = (
            {key: manifest["references"][0][key] for key in ("name", "url", "sha256")}
            if row["id"] == "6.3"
            else {"name": source["name"], "url": source["preview_url"], "sha256": source["preview_sha256"]}
        )
        entries.append(
            {
                "safeguard_id": "SG-ISMS-" + row["id"].replace(".", "-"),
                "title": row["title"],
                "risk_domain": row["risk_domain"],
                "objective": f"Maintain reviewable evidence for the scoped ISMS activity: {row['title']}.",
                "evidence_requirement": (
                    "A scoped assessor record explicitly bound to this safeguard and asset must identify the assessor, "
                    "assessment period, population, applicability, evidence references, tests, and exceptions. "
                    f"GRC Lake proposes inspection of: {row['evidence_checks']}. "
                    "Validate the procedure against the applicable standard and amendment before approval. "
                    "An imported pass does not establish semantic completeness, approve the mapping, or certify conformity."
                ),
                "evaluation_rule": "fail_when_open_violation_or_stale_evidence",
                "frequency": "documented assessment schedule and after material change",
                "owner": row["owner"],
                "reviewed_by": None,
                "reviewed_at": None,
                "asset_types": row["asset_types"],
                "required_evidence_types": row["required_evidence_types"],
                "satisfies": [
                    {
                        "control_id": cid,
                        "framework_id": control["framework_id"],
                        "role": "primary",
                        "review_status": "proposed",
                        "control_version": control["version"],
                        "mapping_basis": "internal_assessment_proposal",
                        "mapping_source": {
                            **citation,
                            "locator": f"Clause {row['id']}; identifier reference only. Original GRC Lake evidence prompt; no normative text or equivalence approval.",
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
            raise ValueError(f"existing ISMS contract changed; explicit reconciliation required: {sid}")
        existing[sid] = entry
    return {**payload, "safeguards": list(existing.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="retained public contents preview HTML")
    parser.add_argument("--clause-source", type=Path, required=True, help="retained NEN clause 6.3 reference HTML")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    verify_source(args.source.read_bytes(), manifest, args.clause_source.read_bytes())
    path = ROOT / "controls/safeguards.json"
    before = json.loads(path.read_text())
    after = updated_payload(before, build_entries(manifest, load_control_catalog()))
    if args.check:
        if after != before:
            raise SystemExit("ISMS safeguards are not synchronized")
    elif after != before:
        path.write_text(json.dumps(after, indent=2, ensure_ascii=False) + "\n")
        write_bundle_lock()


if __name__ == "__main__":
    main()
