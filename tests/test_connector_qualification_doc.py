"""Qualification claims must follow catalog changes and retain their evidence source."""

import copy
import json
import re
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
    live = {"aws-posture", "azure-posture", "gcp-posture", "github-security", "databricks-evidence-lake"}
    assert {row["connector_id"] for row in rows if row["live_record"]} == live
    assert {row["connector_id"]: row["owner"] for row in rows if row["owner"]} == dict.fromkeys(live, "maintainer")
    assert all(
        row["live_record"]["reference"].startswith("docs/qualification/live/") for row in rows if row["live_record"]
    )
    rendered = qualification.render()
    assert "not qualification of a published release artifact" in rendered
    assert "provider-wide" in rendered


PROVIDER_IDENTIFIERS = {
    "AWS account id": re.compile(r"(?<![\w.])\d{12}(?![\w.])"),
    "ARN": re.compile(r"arn:aws[\w-]*:"),
    "GUID": re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "GCP project path": re.compile(r"projects/[a-z][\w-]{4,}"),
    "token": re.compile(r"\b(?:gh[opsu]_|github_pat_|AKIA|ASIA)[A-Za-z0-9_]{8,}"),
}


def test_live_receipts_exist_and_carry_no_provider_identifiers():
    records = [row for row in inputs()[1] if row["live_record"]]
    for record in records:
        path, _, anchor = record["live_record"]["reference"].partition("#")
        text = (ROOT / path).read_text()
        assert anchor and f'<a id="{anchor}"></a>' in text, record["connector_id"]
        assert record["live_record"]["source_basis"] in text
    for receipt in sorted((ROOT / "docs/qualification/live").glob("*.md")):
        text = receipt.read_text()
        for label, pattern in PROVIDER_IDENTIFIERS.items():
            assert not pattern.search(text), f"{receipt.name} contains a {label}"


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


def test_matrix_counts_linked_receipts_by_stage_without_equating_unlinked_with_untested():
    rendered = qualification.render()
    assert "| Implemented | 18 | 4 | 14 |" in rendered
    assert "| Preview | 10 | 1 | 9 |" in rendered
    assert "does not mean never tested or no demo account exists" in rendered
    assert "RECONCILING_LIVE_RECEIPTS.md" in rendered


@pytest.mark.parametrize("change", ["anchor", "basis"])
def test_live_reference_must_resolve_to_its_recorded_anchor_and_revision(change):
    catalog, records = inputs()
    record = next(row for row in records if row["live_record"])["live_record"]
    if change == "anchor":
        record["reference"] = record["reference"].split("#")[0] + "#not-a-receipt"
    else:
        record["source_basis"] = "0" * 40
    with pytest.raises(ValueError, match="receipt"):
        qualification.build_rows(catalog, records)
