"""Retiring an adapter stops collection, never erases retained observations."""

from pathlib import Path

import pytest

from security_lakehouse import assessment, connector_runner, connector_state, oscal, scheduler
from security_lakehouse.connectors import load_connector_catalog
from security_lakehouse.ingestion.watermark import read_watermark, write_watermark
from security_lakehouse.io import read_jsonl, write_jsonl
from security_lakehouse.pipeline import run_pipeline

RETIRED = "knowbe4-training"
FIXTURE = Path(__file__).parent / "fixtures/retired_knowbe4_evidence.jsonl"


def seed_legacy_config(lake):
    # Existing append-only configuration from an older installation.
    write_jsonl(
        lake / "gold/connector_config.jsonl",
        [
            {
                "connector_id": RETIRED,
                "state": "enabled",
                "actor": "operator",
                "occurred_at": "2026-10-18T00:00:00Z",
                "credentials": {"region": "us", "credential_ref": "RETIRED_PROVIDER_TOKEN"},
                "options": {"sync_schedule": "1h"},
            }
        ],
    )


def test_retired_connector_cannot_be_configured_or_discovered(tmp_path):
    assert RETIRED not in load_connector_catalog()
    assert RETIRED not in connector_runner.registered_connector_ids()
    assert not connector_state.has_adapter(RETIRED)
    assert "unknown connector_id" in connector_state.configure_payload_error(
        connector_id=RETIRED,
        state="enabled",
        credentials={"region": "us", "credential_ref": "RETIRED_PROVIDER_TOKEN"},
        options={},
    )
    with pytest.raises(ValueError, match="unknown connector_id"):
        connector_state.append_config_event(tmp_path, connector_id=RETIRED, state="enabled", actor="operator")
    for action in (connector_state.run_probe, connector_state.run_discovery):
        result = action(tmp_path, connector_id=RETIRED, actor="operator")
        assert result["result"] == "error"
        assert "unknown connector_id" in result["error"]


def test_legacy_enabled_configuration_is_not_scheduled(tmp_path):
    seed_legacy_config(tmp_path)
    original = (tmp_path / "gold/connector_config.jsonl").read_bytes()
    assert RETIRED not in {row["connector_id"] for row in connector_state.build_catalog_view(tmp_path)}
    assert RETIRED not in {row.connector_id for row in scheduler._scheduled_from_connectors(tmp_path)}
    assert (tmp_path / "gold/connector_config.jsonl").read_bytes() == original
    assert connector_state.latest_config(tmp_path, RETIRED)["state"] == "enabled"


def test_retirement_preserves_evidence_snapshots_and_exports(tmp_path, monkeypatch):
    lake = tmp_path / "lake"
    raw = lake / connector_runner.CONNECTOR_RAW_FILE
    write_jsonl(raw, read_jsonl(FIXTURE))
    run_pipeline(raw, lake)
    seed_legacy_config(lake)
    write_watermark(lake, RETIRED, "retained-cursor")
    snapshot = assessment.write_assessment_snapshot(lake)
    before = {
        p: p.read_bytes()
        for p in (raw, snapshot, lake / "gold/current_posture.json", lake / "gold/connector_config.jsonl")
    }
    exported = oscal.build_assessment_results(lake, snapshot_id=snapshot.stem)
    assert exported["assessment-results"]["results"][0]["observations"]
    monkeypatch.setattr(connector_runner, "_collect", lambda *a, **k: pytest.fail("retired provider was called"))
    with pytest.raises(connector_runner.ConnectorSyncError, match="unknown connector_id"):
        connector_runner.run_connector_sync(lake, connector_id=RETIRED)
    assert all(p.read_bytes() == data for p, data in before.items())
    assert read_watermark(lake, RETIRED) == "retained-cursor"
    assert connector_state.latest_run(lake, RETIRED, kind="sync")["result"] == "error"
    assert assessment.verify_snapshot_chain(lake)["ok"]
    after = oscal.build_assessment_results(lake, snapshot_id=snapshot.stem)
    assert after["assessment-results"]["results"] == exported["assessment-results"]["results"]
    assert all(row["source"] == "knowbe4" for row in read_jsonl(raw))
