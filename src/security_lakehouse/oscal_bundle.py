"""Offline OSCAL component and catalog handoff using GRC Lake's authored model.

Catalog presence is not reviewed mapping coverage, assessment, or certification.
The archive contains no credentials or lake evidence; optional lake access reads
only mapping review decisions through the existing component exporter.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.catalog import load_control_catalog, load_framework_registry
from security_lakehouse.jsontypes import JsonObject
from security_lakehouse.models import utc_iso
from security_lakehouse.oscal import (
    OSCAL_VERSION,
    _native_control_id,
    _oscal_token,
    _prop,
    _uuid5,
    build_component_definition,
)

_SCOPE = (
    "GRC Lake-authored catalog projection, not an official standards publication. "
    "Catalogued requirements and reviewed mappings do not establish organizational "
    "implementation, assessed compliance, certification, or complete normative coverage."
)


def build_component_bundle(
    safeguards_payload: JsonObject | None = None,
    catalog: dict[str, JsonObject] | None = None,
    *,
    now: datetime | None = None,
    lake_dir: str | Path | None = None,
) -> dict[str, JsonObject]:
    """Project all local requirements and only reviewed, unambiguous CCF mappings.

    Every control-implementation source resolves to a catalog inside the bundle.
    Native NIST IDs and original GRC IDs survive the projection. Ambiguous token
    conversions fail closed instead of associating a mapping with the wrong row.
    """
    controls = catalog if catalog is not None else load_control_catalog()
    registry = load_framework_registry()
    moment = now or datetime.now(UTC)
    component = build_component_definition(safeguards_payload, controls, now=moment, lake_dir=lake_dir)
    files: dict[str, JsonObject] = {"component-definition.json": component}
    grouped: dict[str, list[JsonObject]] = {}
    paths: dict[str, str] = {}
    control_framework: dict[str, str] = {}
    for control_id, control in sorted(controls.items()):
        framework_id = str(control.get("framework_id") or "")
        if not framework_id or control.get("control_id", control_id) != control_id:
            raise ValueError(f"invalid catalog identity: {control_id}")
        framework = registry.get(framework_id, {})
        token = _oscal_token(
            _native_control_id(control_id, framework) if framework.get("oscal_source_url") else control_id
        )
        rows = grouped.setdefault(framework_id, [])
        if any(row["id"] == token for row in rows):
            raise ValueError(f"OSCAL control ID collision in {framework_id}: {token}")
        row: JsonObject = {
            "id": token,
            "title": str(control.get("title") or control_id),
            "props": [_prop("trustops-control-id", control_id), _prop("trustops-framework-id", framework_id)],
        }
        if control.get("evidence_requirement"):
            row["parts"] = [{"name": "statement", "prose": str(control["evidence_requirement"])}]
        rows.append(row)
        control_framework[control_id] = framework_id
    for framework_id, rows in sorted(grouped.items()):
        framework = registry.get(framework_id, {})
        suffix = hashlib.sha256(framework_id.encode()).hexdigest()[:12]
        path = f"catalogs/{_oscal_token(framework_id)}-{suffix}.json"
        paths[framework_id] = path
        metadata: JsonObject = {
            "title": f"GRC Lake catalog projection — {framework.get('name', framework_id)}",
            "last-modified": utc_iso(moment),
            "version": hashlib.sha256(_json_bytes(rows)).hexdigest(),
            "oscal-version": OSCAL_VERSION,
            "remarks": _SCOPE,
            "props": [_prop("trustops-framework-id", framework_id)],
        }
        if framework.get("official_source_url"):
            metadata["links"] = [{"href": str(framework["official_source_url"]), "rel": "reference"}]
        files[path] = {
            "catalog": {
                "uuid": _uuid5("catalog-projection", framework_id, str(metadata["version"])),
                "metadata": metadata,
                "controls": rows,
            }
        }
    counts = dict.fromkeys(grouped, 0)
    reviewed: dict[str, set[str]] = {key: set() for key in grouped}
    for entry in component["component-definition"]["components"]:
        for implementation in entry.get("control-implementations", []):
            requirements = implementation["implemented-requirements"]
            targets = []
            for requirement in requirements:
                original = next(prop["value"] for prop in requirement["props"] if prop["name"] == "trustops-control-id")
                framework_id = control_framework[original]
                targets.append(framework_id)
                counts[framework_id] += 1
                reviewed[framework_id].add(original)
            if len(set(targets)) != 1:
                raise ValueError("component implementation has ambiguous framework references")
            implementation["source"] = paths[targets[0]]
    component["component-definition"]["metadata"]["remarks"] = _SCOPE
    files["manifest.json"] = {
        "schema": "grc-lake.oscal-component-bundle.v1",
        "oscal_version": OSCAL_VERSION,
        "generated_at": utc_iso(moment),
        "scope": _SCOPE,
        "entrypoint": "component-definition.json",
        "frameworks": [
            {
                "framework_id": key,
                "catalog_path": paths[key],
                "catalogued_controls": len(grouped[key]),
                "reviewed_requirement_count": len(reviewed[key]),
                "reviewed_mapping_count": counts[key],
            }
            for key in sorted(grouped)
        ],
        "sha256": {name: hashlib.sha256(_json_bytes(value)).hexdigest() for name, value in sorted(files.items())},
    }
    return files


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_component_bundle(path: str | Path, files: dict[str, JsonObject]) -> None:
    """Write a deterministic ZIP, refusing to replace an existing handoff."""
    # Serialize first so a failure cannot leave a half-built archive on disk.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, document in sorted(files.items()):
            if name.startswith("/") or "\\" in name or any(part in {"", ".", ".."} for part in name.split("/")):
                raise ValueError("unsafe bundle member path")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, _json_bytes(document))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(buffer.getvalue())
