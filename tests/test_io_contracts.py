"""Contracts shared by canonical evidence and generation SQL projections."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from security_lakehouse.io import read_jsonl
from security_lakehouse.pipeline import _silver_row, run_pipeline

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    root = tmp_path_factory.mktemp("io-contract")
    rows = read_jsonl(ROOT / "data/raw/security_events.jsonl")[:3]
    for index, row in enumerate(rows):
        row["tenant_id"] = "source-account"
        row["event_id"] = f"event-{index}"
        if index != 2:
            row["connector_id"] = "fixture-source"
        row["status"] = "observed" if index == 0 else "passed"
        if index == 1:
            row.pop("evidence", None)
    raw = root / "input.jsonl"
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = run_pipeline(raw, root / "lake", tenant_id="platform-owner")
    return root / "lake", result


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_generation_sql_retains_provenance_and_eligibility(lake, backend):
    root, result = lake
    if backend == "duckdb":
        duckdb = pytest.importorskip("duckdb")
        connection = duckdb.connect(result.duckdb_mart_path, read_only=True)
    else:
        connection = sqlite3.connect(result.mart_path)
    try:
        actual = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT event_id, source_account_id, connector_id, source_event_id, "
                "evidence_available, evidence_types_json, safeguard_ids_json FROM normalized_events"
            ).fetchall()
        }
        expected = read_jsonl(root / "silver/normalized_events.jsonl")
        for row in expected:
            values = actual[row["event_id"]]
            assert values[:3] == (row["source_account_id"], row.get("connector_id"), row.get("source_event_id"))
            assert values[3] is not None
            assert bool(values[3]) is row["evidence_available"]
            assert json.loads(values[4]) == row["evidence_types"]
            assert json.loads(values[5]) == row["safeguard_ids"]
        eligibility = dict(connection.execute("SELECT event_id, verdict_eligible FROM evidence_freshness").fetchall())
        for row in read_jsonl(root / "gold/evidence_freshness.jsonl"):
            assert eligibility[row["event_id"]] is not None
            assert bool(eligibility[row["event_id"]]) is row["verdict_eligible"]
        assert set(map(bool, eligibility.values())) == {True, False}
    finally:
        connection.close()


@pytest.mark.parametrize(
    "patch",
    [
        {"evidence_available": "false"},
        {"evidence_types": [5]},
        {"raw_sha256": "z" * 64},
        {"connector_id": "source"},
        {"source_event_id": "event"},
    ],
)
def test_normalized_schema_rejects_invalid_provenance_fields(patch):
    raw = read_jsonl(ROOT / "data/raw/security_events.jsonl")[0]
    row = _silver_row(raw, "a" * 64)
    schema = json.loads((ROOT / "data/schemas/normalized-event.schema.json").read_text())
    validator = Draft202012Validator(schema)
    assert validator.is_valid(row)
    invalid = {**copy.deepcopy(row), **patch}
    assert not validator.is_valid(invalid)


def test_normalized_schema_keeps_legacy_optional_fields_compatible():
    raw = read_jsonl(ROOT / "data/raw/security_events.jsonl")[0]
    row = _silver_row(raw, "a" * 64)
    for key in ("source_account_id", "evidence_available", "evidence_types", "safeguard_ids"):
        row.pop(key, None)
    schema = json.loads((ROOT / "data/schemas/normalized-event.schema.json").read_text())
    assert Draft202012Validator(schema).is_valid(row)


def test_incremental_rebuilds_when_mart_contract_changes(tmp_path, monkeypatch):
    from security_lakehouse import pipeline
    from security_lakehouse.io import read_json

    raw = ROOT / "data/raw/security_events.jsonl"
    lake = tmp_path / "lake"
    with monkeypatch.context() as context:
        context.setattr(pipeline, "MART_SCHEMA_VERSION", "trustops.mart.v0", raising=False)
        pipeline.run_pipeline(raw, lake)
    prior = read_json(lake / "manifest.json")
    previous_mart = lake / "generations" / prior["generation_id"] / "mart/security_lakehouse.sqlite"
    previous_bytes = previous_mart.read_bytes()
    pipeline.run_pipeline_incremental(raw, lake)
    current = read_json(lake / "manifest.json")
    assert prior["generation_id"] != current["generation_id"]
    assert current["mart_schema_version"] == pipeline.MART_SCHEMA_VERSION
    assert previous_mart.read_bytes() == previous_bytes
