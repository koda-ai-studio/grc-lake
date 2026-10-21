"""Portable CCF references resolve offline without inflating reviewed coverage."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from security_lakehouse.cli import main
from security_lakehouse.oscal_bundle import build_component_bundle, write_component_bundle

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def validate_schema(document, name):
    raw = (Path(__file__).resolve().parents[1] / "controls" / "oscal" / name).read_text()
    raw = raw.replace(r"\\p{L}", "[A-Za-z]").replace(r"\\p{N}", "[0-9]")
    Draft7Validator(json.loads(raw)).validate(document)


def test_full_bundle_is_schema_valid_and_every_mapping_resolves_offline():
    files = build_component_bundle(now=NOW)
    assert files == build_component_bundle(now=NOW)
    manifest = files["manifest.json"]
    component = files["component-definition.json"]
    validate_schema(component, "oscal_component_schema.json")
    frameworks = {row["framework_id"]: row for row in manifest["frameworks"]}
    assert {"soc2", "iso-27001-2022", "nist-csf-2.0", "nist-800-53-rev5"} <= set(frameworks)
    mapping_count = 0
    for item in component["component-definition"]["components"]:
        for impl in item.get("control-implementations", []):
            assert impl["source"].startswith("catalogs/")
            controls = {row["id"]: row for row in files[impl["source"]]["catalog"]["controls"]}
            for requirement in impl["implemented-requirements"]:
                target = controls[requirement["control-id"]]
                props = {p["name"]: p["value"] for p in requirement["props"]}
                assert props["trustops-review-state"] in {"maintainer-reviewed", "org-reviewed"}
                assert props["trustops-control-id"] == target["props"][0]["value"]
                mapping_count += 1
    assert mapping_count == sum(row["reviewed_mapping_count"] for row in frameworks.values())
    for row in frameworks.values():
        catalog = files[row["catalog_path"]]
        validate_schema(catalog, "oscal_catalog_schema.json")
        assert row["catalogued_controls"] == len(catalog["catalog"]["controls"])
        assert row["reviewed_requirement_count"] <= row["catalogued_controls"]
    assert frameworks["soc2"]["reviewed_requirement_count"] < frameworks["soc2"]["catalogued_controls"]


def test_proposed_and_rejected_mappings_remain_catalogued_but_not_asserted():
    catalog = {
        f"CONTROL-{i}": {"control_id": f"CONTROL-{i}", "framework_id": "custom", "title": f"Original requirement {i}"}
        for i in range(3)
    }
    payload = {
        "safeguards": [
            {
                "safeguard_id": "SG-ONE",
                "title": "Example",
                "satisfies": [
                    {"control_id": "CONTROL-0", "role": "primary", "review_status": "reviewed"},
                    {"control_id": "CONTROL-1", "role": "primary", "review_status": "proposed"},
                    {"control_id": "CONTROL-2", "role": "primary", "review_status": "rejected"},
                ],
            }
        ]
    }
    files = build_component_bundle(payload, catalog, now=NOW)
    summary = files["manifest.json"]["frameworks"][0]
    assert summary["catalogued_controls"] == 3
    assert summary["reviewed_requirement_count"] == 1
    assert summary["reviewed_mapping_count"] == 1


def test_ambiguous_sanitized_ids_fail_instead_of_linking_wrong_requirement():
    catalog = {key: {"control_id": key, "framework_id": "custom"} for key in ["ABC(1)", "ABC-1"]}
    with pytest.raises(ValueError, match="collision"):
        build_component_bundle({"safeguards": []}, catalog, now=NOW)


def test_archive_is_reproducible_has_checksums_and_does_not_overwrite(tmp_path):
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    files = build_component_bundle(now=NOW)
    write_component_bundle(first, files)
    write_component_bundle(second, files)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest["sha256"]) == set(archive.namelist()) - {"manifest.json"}
        for name, digest in manifest["sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    with pytest.raises(FileExistsError):
        write_component_bundle(first, files)
    assert first.read_bytes() == second.read_bytes()


def test_cli_bundle_and_incompatible_flags(tmp_path):
    out = tmp_path / "ccf.zip"
    assert main(["oscal", "export", "--component-bundle", "--out", str(out)]) == 0
    assert zipfile.is_zipfile(out)
    for flags in [[], ["--snapshot", "x"], ["--component-definition"], ["--assessment-results", str(tmp_path)]]:
        with pytest.raises(SystemExit):
            main(["oscal", "export", "--component-bundle", *flags])


def test_org_review_overlay_is_scoped_and_preserves_receipts(tmp_path, monkeypatch):
    from security_lakehouse.mapping_review import effective_safeguards, record_decisions

    catalog = {"SOC2-CC6.1": {"control_id": "SOC2-CC6.1", "framework_id": "soc2"}}
    payload = {
        "safeguards": [
            {
                "safeguard_id": "SG-ONE",
                "title": "Access",
                "satisfies": [
                    {
                        "control_id": "SOC2-CC6.1",
                        "framework_id": "soc2",
                        "role": "primary",
                        "review_status": "proposed",
                    },
                ],
            }
        ]
    }
    # The real append-only review service is exercised; only the small base catalog is substituted.
    monkeypatch.setattr("security_lakehouse.mapping_review.load_safeguards", lambda: payload)
    monkeypatch.setattr("security_lakehouse.mapping_review.load_control_catalog", lambda: catalog)
    record_decisions(
        tmp_path / "tenant-a",
        decision="approve",
        reviewer="reviewer@example.test",
        rationale="Reviewed scoped evidence",
        items=[{"safeguard_id": "SG-ONE", "control_id": "SOC2-CC6.1", "framework_id": "soc2"}],
    )
    approved = build_component_bundle(catalog=catalog, lake_dir=tmp_path / "tenant-a", now=NOW)
    untouched = build_component_bundle(catalog=catalog, lake_dir=tmp_path / "tenant-b", now=NOW)
    assert approved["manifest.json"]["frameworks"][0]["reviewed_requirement_count"] == 1
    assert untouched["manifest.json"]["frameworks"][0]["reviewed_requirement_count"] == 0
    component = approved["component-definition.json"]["component-definition"]["components"][0]
    requirement = component["control-implementations"][0]["implemented-requirements"][0]
    props = {p["name"]: p["value"] for p in requirement["props"]}
    assert props["trustops-review-state"] == "org-reviewed"
    assert props["trustops-reviewed-by"] == "reviewer@example.test"
    assert props["trustops-review-decision-id"]
    assert effective_safeguards(tmp_path / "tenant-b")["safeguards"][0]["satisfies"][0]["review_status"] == "proposed"


@pytest.mark.parametrize("name", ["../outside.json", "/absolute.json", "catalogs/../bad.json", "catalogs\\bad.json"])
def test_writer_rejects_unsafe_member_paths_before_creating_archive(tmp_path, name):
    out = tmp_path / "bad.zip"
    with pytest.raises(ValueError, match="unsafe"):
        write_component_bundle(out, {name: {}})
    assert not out.exists()
