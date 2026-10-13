"""Qualification claims must follow catalog changes and retain their evidence source."""

import copy
import json
from pathlib import Path

import pytest
from tools import connector_qualification_doc as qualification

ROOT = Path(__file__).resolve().parents[1]


def inputs():
    catalog = json.loads((ROOT / "connectors/catalog.json").read_text())["connectors"]
    records = json.loads((ROOT / "docs/qualification/connector-evidence.json").read_text())["connectors"]
    return catalog, records


def test_generated_matrix_is_current_and_does_not_promote_historical_checks():
    assert (ROOT / "docs/CONNECTOR_QUALIFICATION.md").read_text() == qualification.render()
    catalog, records = inputs()
    rows = qualification.build_rows(catalog, records)
    assert len(rows) == len(catalog)
    assert {row["connector_id"] for row in rows if row["live_record"]} == {
        "aws-posture",
        "azure-posture",
        "gcp-posture",
    }
    assert all(row["owner"] is None for row in rows)
    assert "not qualification of the current release" in qualification.render()


@pytest.mark.parametrize("mutation", ["new", "stale", "duplicate"])
def test_catalog_drift_requires_an_explicit_qualification_record(mutation):
    catalog, records = inputs()
    if mutation == "new":
        catalog.append({**catalog[0], "connector_id": "new-connector"})
    elif mutation == "stale":
        catalog.pop()
    else:
        records.append(copy.deepcopy(records[0]))
    with pytest.raises(ValueError):
        qualification.build_rows(catalog, records)


def test_permissions_and_release_stage_come_from_the_catalog():
    catalog, records = inputs()
    catalog[0].update(minimum_permissions=["SELECT on a narrower view"], release_stage="preview")
    row = next(
        row for row in qualification.build_rows(catalog, records) if row["connector_id"] == catalog[0]["connector_id"]
    )
    assert row["minimum_permissions"] == ["SELECT on a narrower view"]
    assert row["release_stage"] == "preview"


@pytest.mark.parametrize("fixture_tests", [[], ["tests/missing_contract.py"], ["../outside.py"]])
def test_executable_adapter_cannot_claim_missing_fixture_references(fixture_tests):
    catalog, records = inputs()
    records[0]["fixture_tests"] = fixture_tests
    with pytest.raises(ValueError, match="fixture"):
        qualification.build_rows(catalog, records)


@pytest.mark.parametrize("missing", ["date", "source_basis", "scope", "reference"])
def test_historical_live_claim_requires_a_bounded_source_record(missing):
    catalog, records = inputs()
    record = next(row for row in records if row["live_record"])
    del record["live_record"][missing]
    with pytest.raises(ValueError, match="live record"):
        qualification.build_rows(catalog, records)
