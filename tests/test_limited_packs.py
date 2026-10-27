"""Tests for limited-mapping framework packs (GDPR, HIPAA, PCI, EU AI Act)."""

from __future__ import annotations

from security_lakehouse.catalog import load_control_catalog, validate_catalog
from security_lakehouse.limited_packs import LIMITED_PACK_BUILDERS, LIMITED_PACK_MINIMUMS
from security_lakehouse.mappings import load_control_article_mappings


def test_limited_pack_builders_emit_expected_counts() -> None:
    for pack_id, builder in LIMITED_PACK_BUILDERS.items():
        specs = list(builder())
        if pack_id == "fedramp-ksi":
            assert {spec.control_id for spec in specs} == {"KSI-IAM-AAM", "KSI-IAM-APM"}
        else:
            assert len(specs) >= 9, f"{pack_id} should emit a meaningful subset"


def test_limited_frameworks_meet_minimum_seeded_counts() -> None:
    catalog = load_control_catalog()
    mappings = load_control_article_mappings()
    for framework_id, minimum in LIMITED_PACK_MINIMUMS.items():
        controls = [c for c in catalog.values() if c["framework_id"] == framework_id]
        assert len(controls) >= minimum, f"{framework_id} expected >={minimum}, got {len(controls)}"
        mapped = [c for c in controls if c["control_id"] in mappings]
        assert len(mapped) == len(controls), f"{framework_id} controls must all have mappings"


def test_catalog_validates_after_limited_pack_sync() -> None:
    errors = validate_catalog()
    assert errors == [], errors


PCI_PRINCIPAL_REQUIREMENTS = {str(n) for n in range(1, 13)}


def test_pci_manifest_lists_every_principal_requirement() -> None:
    from security_lakehouse.limited_packs import pci_dss_limited_pack_specs

    refs = {spec.article_id.removeprefix("Req-") for spec in pci_dss_limited_pack_specs()}
    assert refs == PCI_PRINCIPAL_REQUIREMENTS


def test_pci_cites_v4_0_1_and_keeps_v4_0_versions_in_history() -> None:
    from security_lakehouse.catalog import load_framework_registry
    from security_lakehouse.catalog_versions import controls_as_of

    registry = load_framework_registry()["pci-dss-v4"]
    assert registry["version"] == "v4.0.1"
    assert "v4.0.1" in registry["official_source_name"]

    active = {cid: c for cid, c in load_control_catalog().items() if c["framework_id"] == "pci-dss-v4"}
    assert {c["framework_ref"] for c in active.values()} == {
        f"PCI DSS v4.0.1 Req {n}" for n in PCI_PRINCIPAL_REQUIREMENTS
    }
    assert {c["framework"] for c in active.values()} == {"PCI DSS"}
    assert all(c["supersedes"] == f"{cid}@1.0.0" for cid, c in active.items())

    before = {cid: c for cid, c in controls_as_of("2026-09-01").items() if c["framework_id"] == "pci-dss-v4"}
    assert set(before) == set(active)
    assert all(c["version"] == "1.0.0" for c in before.values())
