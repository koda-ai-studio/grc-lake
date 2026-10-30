"""A bounded lake sample cannot claim complete collection or advance its cursor."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_lakehouse.connector_runner import DEFAULT_TOKEN_ENV, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.ingestion.watermark import collection_scope, read_watermark, write_watermark
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.lake_mapping import capture_mapping_stats, collect_mapped_evidence, resolve_mapping_ref
from security_lakehouse.pipeline import run_pipeline

FIXTURE = Path(__file__).parent / "fixtures/ocsf/ocsf_identity_events.json"


def _rows(count: int) -> list[dict]:
    template = json.loads(FIXTURE.read_text())[0]
    rows = []
    for i in range(count):
        row = deepcopy(template)
        row["metadata"]["uid"] = f"event-{i}"
        row["user"]["uid"] = f"user-{i}"
        row["time_dt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        row["is_mfa"] = True
        rows.append(row)
    return rows


def _spec():
    return resolve_mapping_ref({"preset": "ocsf/authentication", "source": {"table": "events"}})


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_overflow_lookahead_distinguishes_exact_bound_from_incomplete_read(count):
    rows = _rows(count)
    limits = []

    def fetch(spec, since, limit):
        limits.append(limit)
        return rows[:limit]

    events = collect_mapped_evidence(fetch, [_spec()], max_rows=2)
    assert limits == [3]
    evidence = [row for row in events if not row["attributes"].get("collection_gap")]
    gaps = [row for row in events if row["attributes"].get("collection_gap")]
    assert len(evidence) == min(count, 2)
    assert bool(gaps) is (count > 2)
    assert all(row["status"] == ("not_evaluated" if gaps else "pass") for row in evidence)
    if gaps:
        assert gaps[0]["attributes"]["reason"] == "row_limit_exceeded"
        assert gaps[0]["attributes"]["row_limit"] == 2
        assert not gaps[0].get("safeguard_ids") and not gaps[0]["controls"]
        assert "event-2" not in json.dumps(events)


def test_overflow_preserves_failures_and_observations_without_promoting_verdicts():
    rows = _rows(4)
    rows[0]["is_mfa"] = False
    rows[1].pop("is_mfa")
    events = collect_mapped_evidence(lambda *args: rows, [_spec()], max_rows=3)
    evidence = [row for row in events if not row["attributes"].get("collection_gap")]
    assert [row["status"] for row in evidence] == ["open", "observed", "not_evaluated"]
    assert all(row["attributes"]["mapping_partial"] for row in evidence)


def test_preview_reports_overflow_even_when_every_sampled_row_maps():
    with capture_mapping_stats() as stats:
        events = collect_mapped_evidence(lambda *args: _rows(3), [_spec()], max_rows=2)
    assert len(events) == 2
    assert stats[0]["truncated"] is True
    assert stats[0]["row_limit"] == 2
    assert stats[0]["rows_read"] == 3
    assert stats[0]["mapped_count"] == 2
    assert stats[0]["errors"] == []


@pytest.mark.parametrize(
    "connector",
    [
        "databricks-evidence-lake",
        "snowflake-evidence-lake",
        "clickhouse-telemetry-lake",
        "bigquery-evidence-lake",
        "iceberg-parquet-lake",
    ],
)
@pytest.mark.parametrize("prior", [None, "2026-09-01T00:00:00Z"])
def test_truncated_ocsf_sync_holds_cursor_and_cannot_pass_ccf(tmp_path, prior, connector):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    rows = _rows(3)
    rows[-1]["is_mfa"] = False
    (fixtures / "events.json").write_text(json.dumps(rows))
    lake = tmp_path / "lake"
    config = append_config_event(
        lake,
        connector_id=connector,
        state="enabled",
        actor="test",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={"mapping": {"preset": "ocsf/authentication", "source": {"table": "events"}}, "max_rows_per_sync": 2},
    )
    scope = collection_scope(config, repo=None, fixture_dir=fixtures, token_env=DEFAULT_TOKEN_ENV)
    if prior:
        write_watermark(lake, connector, prior, scope_id=scope)
    for _ in range(2):
        result = run_connector_sync(lake, connector_id=connector, fixture_dir=fixtures, materialize=False)
        assert result.run["metadata"]["partial"] is True
        assert result.watermark_cursor == prior
        assert read_watermark(lake, connector, scope_id=scope) == prior
        raw = read_jsonl(lake / "raw/connector_events.jsonl")
        assert len(raw) == 3
        assert not any(row["status"] == "pass" for row in raw)
    out = tmp_path / "assessment"
    run_pipeline(lake / "raw/connector_events.jsonl", out, tenant_id="platform-test")
    ccf = read_json(out / "gold/ccf_assessment.json")
    identity = [row for row in ccf["asset_results"] if row["safeguard_id"] == "SG-IDENTITY-001"]
    assert len(identity) == 2
    assert all(row["status"] == "not_evaluated" for row in identity)
    assert not any(row["status"] == "pass" for row in ccf["requirements"])


@pytest.mark.parametrize("max_rows", [0, -1, True, 1.5])
def test_invalid_budget_fails_before_fetch(max_rows):
    def fetch(*args):
        pytest.fail("invalid budget reached the source")

    with pytest.raises(ValueError, match="positive integer"):
        collect_mapped_evidence(fetch, [_spec()], max_rows=max_rows)


def test_overflow_and_mapping_errors_keep_distinct_gap_receipts():
    rows = _rows(4)
    rows[1]["user"] = {}
    events = collect_mapped_evidence(lambda *args: rows, [_spec()], max_rows=3)
    gaps = [row for row in events if row["attributes"].get("collection_gap")]
    assert {row["attributes"]["reason"] for row in gaps} == {"row_limit_exceeded", "unmappable_rows"}
    assert len({row["event_id"] for row in gaps}) == 2
    assert not any(row["status"] == "pass" for row in events)


def test_overflow_without_matching_rows_is_still_a_gap():
    rows = [dict(row, class_uid=6003) for row in _rows(3)]
    [gap] = collect_mapped_evidence(lambda *args: rows, [_spec()], max_rows=2)
    assert gap["attributes"]["reason"] == "row_limit_exceeded"
    assert gap["status"] == "not_evaluated"


def test_truncation_does_not_change_a_separate_complete_mapping():
    incomplete = _spec()
    complete = resolve_mapping_ref(
        {"preset": "ocsf/authentication", "name": "complete", "source": {"table": "complete"}}
    )

    def fetch(spec, since, limit):
        return _rows(3 if spec.name == incomplete.name else 1)[:limit]

    events = collect_mapped_evidence(fetch, [incomplete, complete], max_rows=2)
    [complete_event] = [row for row in events if row["attributes"]["mapping"] == "complete"]
    assert complete_event["status"] == "pass"
    assert not complete_event["attributes"].get("mapping_partial")
