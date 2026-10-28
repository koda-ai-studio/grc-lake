"""Regenerate the NIST SP 800-53 Rev 5 pack manifest from official OSCAL content.

Reads the catalog and the LOW/MODERATE/HIGH/PRIVACY baseline profiles from a
pinned commit of https://github.com/usnistgov/oscal-content and writes
``frameworks/packs/data/nist_800_53_rev5_catalog.json`` with every active
(non-withdrawn) control and enhancement, its official title, family, parent,
and baseline membership. The commit and the catalog's sha256 are recorded so
the manifest can be re-derived and checked.

Usage::

    uv run python tools/sync_nist_800_53.py --commit <oscal-content sha>
    uv run python tools/sync_nist_800_53.py --source-dir <dir with downloaded files> --commit <sha>
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from security_lakehouse import framework_enrich

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "frameworks" / "packs" / "data" / "nist_800_53_rev5_catalog.json"
RAW_BASE = "https://raw.githubusercontent.com/usnistgov/oscal-content/{commit}/nist.gov/SP800-53/rev5/json/"
FILES = {
    "catalog": "NIST_SP-800-53_rev5_catalog.json",
    "low": "NIST_SP-800-53_rev5_LOW-baseline_profile.json",
    "moderate": "NIST_SP-800-53_rev5_MODERATE-baseline_profile.json",
    "high": "NIST_SP-800-53_rev5_HIGH-baseline_profile.json",
    "privacy": "NIST_SP-800-53_rev5_PRIVACY-baseline_profile.json",
}
BASELINES = ("low", "moderate", "high", "privacy")


def _load(name: str, *, commit: str, source_dir: Path | None) -> bytes:
    if source_dir is not None:
        return (source_dir / FILES[name]).read_bytes()
    return framework_enrich.fetch(RAW_BASE.format(commit=commit) + FILES[name], timeout=60)[0]


def _profile_ids(payload: bytes) -> set[str]:
    profile = json.loads(payload)["profile"]
    return {
        control_id
        for imported in profile["imports"]
        for include in imported.get("include-controls", [])
        for control_id in include.get("with-ids", [])
    }


def _withdrawn(control: dict[str, Any]) -> bool:
    return any(p.get("name") == "status" and p.get("value") == "withdrawn" for p in control.get("props", []))


def build_manifest(files: dict[str, bytes], *, commit: str) -> dict[str, Any]:
    catalog = json.loads(files["catalog"])["catalog"]
    members = {baseline: _profile_ids(files[baseline]) for baseline in BASELINES}
    rows: list[dict[str, Any]] = []

    def walk(controls: list[dict[str, Any]], family: str, parent: str | None) -> None:
        for control in controls:
            oscal_id = str(control["id"])
            if not _withdrawn(control):
                rows.append(
                    {
                        "id": oscal_id.upper(),
                        "title": str(control["title"]),
                        "family": family.upper(),
                        "parent": parent.upper() if parent else None,
                        "baselines": [b for b in BASELINES if oscal_id in members[b]],
                    }
                )
            walk(control.get("controls", []), family, oscal_id)

    for group in catalog["groups"]:
        walk(group.get("controls", []), str(group["id"]), None)

    return {
        "schema": "trustops.framework_pack_manifest.v1",
        "source": {
            "name": catalog["metadata"]["title"],
            "version": catalog["metadata"]["version"],
            "url": "https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final",
            "oscal_repository": "https://github.com/usnistgov/oscal-content",
            "oscal_commit": commit,
            "catalog_file": FILES["catalog"],
            "catalog_sha256": hashlib.sha256(files["catalog"]).hexdigest(),
            "baseline_counts": {b: len(members[b]) for b in BASELINES},
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", required=True, help="usnistgov/oscal-content commit sha to pin")
    parser.add_argument("--source-dir", type=Path, help="read the OSCAL files from this directory instead")
    args = parser.parse_args()
    files = {name: _load(name, commit=args.commit, source_dir=args.source_dir) for name in FILES}
    manifest = build_manifest(files, commit=args.commit)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {len(manifest['rows'])} active controls")


if __name__ == "__main__":
    main()
