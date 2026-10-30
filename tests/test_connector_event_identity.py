"""Connector-local source IDs remain distinct throughout the evidence pipeline."""

import copy

import pytest

from security_lakehouse.connector_runner import _upsert_raw_events
from security_lakehouse.io import read_jsonl, write_jsonl
from security_lakehouse.pipeline import normalize_raw_events, run_pipeline
from security_lakehouse.verification import verify_event


def event(*, at="2026-01-01T01:00:00Z", status="passed"):
    return {
        "event_id": "provider-42",
        "tenant_id": "t",
        "event_time": at,
        "source": "provider",
        "event_type": "configuration.status",
        "entity": {"id": "asset-1", "type": "service"},
        "status": status,
        "controls": [],
        "evidence": {"ref": "provider://record/42", "collected_at": at},
    }


@pytest.mark.parametrize("mode", ["append", "snapshot"])
def test_connector_collision_preserves_other_connector(tmp_path, mode):
    path = tmp_path / "raw.jsonl"
    _upsert_raw_events(path, [event()], connector_id="one", write_mode="append")
    _upsert_raw_events(path, [event()], connector_id="two", write_mode=mode)
    stored = read_jsonl(path)
    assert {row["connector_id"] for row in stored} == {"one", "two"}
    assert {row["event_id"] for row in stored} == {"provider-42"}


def test_stale_redelivery_cannot_replace_newer_observation(tmp_path):
    path = tmp_path / "raw.jsonl"
    _upsert_raw_events(path, [event()], connector_id="one", write_mode="append")
    older = event(at="2026-01-01T01:30:00+01:00", status="failed")
    _upsert_raw_events(path, [older], connector_id="one", write_mode="append")
    assert read_jsonl(path)[0]["status"] == "passed"


def test_conflicting_equal_time_observation_preserves_store(tmp_path):
    path = tmp_path / "raw.jsonl"
    _upsert_raw_events(path, [event()], connector_id="one", write_mode="append")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="conflict"):
        _upsert_raw_events(path, [event(status="failed")], connector_id="one", write_mode="append")
    assert path.read_bytes() == before


def test_scoped_identity_survives_normalization_incremental_and_lineage(tmp_path):
    path = tmp_path / "raw.jsonl"
    rows = [{**event(), "connector_id": "one"}, {**event(), "connector_id": "two"}]
    write_jsonl(path, rows)
    lake = tmp_path / "lake"
    run_pipeline(path, lake)
    silver = read_jsonl(lake / "silver/normalized_events.jsonl")
    assert len({row["event_id"] for row in silver}) == 2
    assert {row["source_event_id"] for row in silver} == {"provider-42"}
    assert {row["connector_id"] for row in silver} == {"one", "two"}
    assert all(verify_event(lake, row["event_id"])["verified"] for row in silver)
    previous = (lake / ".active-generation").resolve()
    previous_silver = (previous / "silver/normalized_events.jsonl").read_bytes()
    updated = copy.deepcopy(rows)
    updated[0]["event_time"] = "2026-01-02T00:00:00Z"
    updated[0]["status"] = "failed"
    write_jsonl(path, updated)
    normalize_raw_events(path, lake, incremental=True)
    current = read_jsonl(lake / "silver/normalized_events.jsonl")
    assert len(current) == 2
    assert {row["connector_id"]: row["status"] for row in current} == {"one": "failed", "two": "passed"}
    assert all(verify_event(lake, row["event_id"])["verified"] for row in current)
    assert (previous / "silver/normalized_events.jsonl").read_bytes() == previous_silver


def test_watermark_uses_instant_order_across_offsets(tmp_path):
    from security_lakehouse.connector_runner import _advance_watermark

    current = "2026-01-01T01:00:00Z"
    assert _advance_watermark(tmp_path, "one", [event(at=current)], write_mode="append") == current
    assert _advance_watermark(tmp_path, "one", [event(at="2026-01-01T01:30:00+01:00")], write_mode="append") == current


def test_incremental_rejects_unchanged_duplicate_input_before_publication(tmp_path):
    path = tmp_path / "raw.jsonl"
    row = {**event(), "connector_id": "one"}
    write_jsonl(path, [row])
    lake = tmp_path / "lake"
    run_pipeline(path, lake)
    before = (lake / ".active-generation").readlink()
    write_jsonl(path, [row, row])
    with pytest.raises(ValueError, match="duplicate"):
        normalize_raw_events(path, lake, incremental=True)
    assert (lake / ".active-generation").readlink() == before


def test_redelivery_updates_collection_time_without_changing_source_content(tmp_path):
    path = tmp_path / "raw.jsonl"
    original = event()
    _upsert_raw_events(path, [original], connector_id="one", write_mode="append")
    recollected = copy.deepcopy(original)
    recollected["evidence"]["collected_at"] = "2026-01-02T01:00:00Z"
    _upsert_raw_events(path, [recollected], connector_id="one", write_mode="append")
    assert read_jsonl(path)[0]["evidence"]["collected_at"] == recollected["evidence"]["collected_at"]
    conflicting = copy.deepcopy(recollected)
    conflicting["status"] = "failed"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="conflict"):
        _upsert_raw_events(path, [conflicting], connector_id="one", write_mode="append")
    assert path.read_bytes() == before


def test_same_provider_id_in_two_accounts_survives_sync_and_replay(tmp_path, monkeypatch):
    from security_lakehouse import connector_runner as runner
    from security_lakehouse.connector_state import append_config_event

    rows = [{**event(), "tenant_id": account} for account in ["example-a", "example-b"]]
    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="test")
    monkeypatch.setattr(runner, "_collect", lambda *args, **kwargs: copy.deepcopy(rows))
    first = runner.run_connector_sync(tmp_path, connector_id="github-security")
    assert first.evidence_count == 2
    before = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assert len({row["event_id"] for row in before}) == 2
    assert {row["source_account_id"] for row in before} == {"example-a", "example-b"}
    assert {row["source_event_id"] for row in before} == {"provider-42"}
    assert all(verify_event(tmp_path, row["event_id"])["verified"] for row in before)
    assert (tmp_path / "gold/ccf_assessment.json").is_file()
    again = runner.run_connector_sync(tmp_path, connector_id="github-security")
    assert again.evidence_count == 2
    assert read_jsonl(tmp_path / "silver/normalized_events.jsonl") == before


@pytest.mark.parametrize("mode", ["append", "snapshot"])
def test_account_local_update_cannot_overwrite_another_accounts_event(tmp_path, mode):
    path = tmp_path / "raw.jsonl"
    a = {**event(), "tenant_id": "example-a"}
    b = {**event(), "tenant_id": "example-b"}
    _upsert_raw_events(path, [a, b], connector_id="one", write_mode=mode)
    newer = {**a, "event_time": "2026-01-02T01:00:00Z", "status": "failed"}
    _upsert_raw_events(path, [newer, b], connector_id="one", write_mode=mode)
    assert {row["tenant_id"]: row["status"] for row in read_jsonl(path)} == {
        "example-a": "failed",
        "example-b": "passed",
    }


def test_account_identity_upgrade_rebuilds_and_keeps_old_generation_verifiable(tmp_path, monkeypatch):
    import hashlib
    import json

    from security_lakehouse import pipeline
    from security_lakehouse.io import read_json

    path = tmp_path / "raw.jsonl"
    rows = [{**event(), "connector_id": "one", "tenant_id": "example-a"}]
    write_jsonl(path, rows)
    old_id = "trustops:connector-event:v1:" + hashlib.sha256(b'["one","provider-42"]').hexdigest()
    lake = tmp_path / "lake"
    with monkeypatch.context() as legacy:
        legacy.setattr(pipeline, "NORMALIZATION_TRANSFORM_VERSION", "trustops.normalization.v6")
        legacy.setattr(pipeline, "event_identity", lambda row: old_id)
        run_pipeline(path, lake)
    previous = (lake / ".active-generation").resolve()
    previous_bytes = (previous / "silver/normalized_events.jsonl").read_bytes()
    assert json.loads(previous_bytes)["event_id"] == old_id
    rows.append({**rows[0], "tenant_id": "example-b"})
    write_jsonl(path, rows)
    normalize_raw_events(path, lake, incremental=True)
    current = read_jsonl(lake / "silver/normalized_events.jsonl")
    assert len(current) == 2
    assert all(row["event_id"].startswith("trustops:connector-event:v2:") for row in current)
    assert read_json(lake / "manifest.json")["normalization"]["transform_version"] == "trustops.normalization.v7"
    assert (previous / "silver/normalized_events.jsonl").read_bytes() == previous_bytes
    assert verify_event(previous, old_id)["verified"]
    assert all(verify_event(lake, row["event_id"])["verified"] for row in current)
