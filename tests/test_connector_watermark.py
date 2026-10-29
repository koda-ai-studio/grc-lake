"""Incremental watermark wiring: append connectors persist + advance a cursor.

The ``ingestion.watermark`` module was previously unwired — connectors
full-refreshed every sync. ``run_connector_sync`` now reads an append/event-log
connector's high-water cursor before collecting (exposed as ``SyncInputs.since``
for incremental pulls) and advances it after a successful sync. Snapshot
connectors replace state and carry no watermark.
"""

from __future__ import annotations

from pathlib import Path

from security_lakehouse import connector_runner as cr
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.ingestion.watermark import collection_scope, read_watermark, write_watermark

GITHUB_FIXTURE = Path(__file__).parent / "fixtures" / "github-governance"
AWS_FIXTURE = Path(__file__).parent / "fixtures" / "aws"


# --- unit: _advance_watermark ------------------------------------------------


def _rows(*times: str) -> list[dict]:
    return [{"event_id": f"e{i}", "event_time": t} for i, t in enumerate(times)]


def test_advance_writes_max_event_time_for_append(tmp_path: Path) -> None:
    cursor = cr._advance_watermark(
        tmp_path, "okta-system-log", _rows("2026-06-01T00:00:00Z", "2026-06-03T00:00:00Z"), write_mode="append"
    )
    assert cursor == "2026-06-03T00:00:00Z"
    assert read_watermark(tmp_path, "okta-system-log") == "2026-06-03T00:00:00Z"


def test_snapshot_connector_carries_no_watermark(tmp_path: Path) -> None:
    cursor = cr._advance_watermark(tmp_path, "aws-posture", _rows("2026-06-03T00:00:00Z"), write_mode="snapshot")
    assert cursor is None
    assert read_watermark(tmp_path, "aws-posture") is None


def test_cursor_is_monotonic(tmp_path: Path) -> None:
    write_watermark(tmp_path, "siem-alerts", "2026-06-10T00:00:00Z")
    # An older pull must not move the high-water mark backwards.
    cursor = cr._advance_watermark(tmp_path, "siem-alerts", _rows("2026-06-05T00:00:00Z"), write_mode="append")
    assert cursor == "2026-06-10T00:00:00Z"
    assert read_watermark(tmp_path, "siem-alerts") == "2026-06-10T00:00:00Z"


def test_empty_pull_keeps_prior_cursor(tmp_path: Path) -> None:
    write_watermark(tmp_path, "siem-alerts", "2026-06-10T00:00:00Z")
    assert cr._advance_watermark(tmp_path, "siem-alerts", [], write_mode="append") == "2026-06-10T00:00:00Z"


def test_partial_pull_keeps_prior_cursor(tmp_path: Path) -> None:
    # A gap means some events before the newest one may be missing; advancing
    # past them would skip them on every later incremental sync.
    write_watermark(tmp_path, "siem-alerts", "2026-06-10T00:00:00Z")
    rows = _rows("2026-06-12T00:00:00Z") + [
        {"event_id": "gap", "event_time": "2026-06-12T00:00:00Z", "attributes": {"collection_gap": True}}
    ]
    assert cr._advance_watermark(tmp_path, "siem-alerts", rows, write_mode="append") == "2026-06-10T00:00:00Z"
    assert read_watermark(tmp_path, "siem-alerts") == "2026-06-10T00:00:00Z"


# --- integration: through run_connector_sync ---------------------------------


def test_append_connector_sync_advances_watermark(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="alice")
    assert read_watermark(tmp_path, "github-security") is None  # nothing synced yet

    result = cr.run_connector_sync(
        tmp_path, connector_id="github-security", repo="acme/model-service", fixture_dir=GITHUB_FIXTURE
    )
    assert result.result == "ok"
    # github-security is an event_log (append) connector, so the sync records how
    # far it has synced through.
    assert result.watermark_cursor is not None
    assert (
        read_watermark(tmp_path, "github-security", scope_id=result.run["metadata"]["watermark_scope_id"])
        == result.watermark_cursor
    )

    # A second sync never regresses the cursor.
    again = cr.run_connector_sync(
        tmp_path, connector_id="github-security", repo="acme/model-service", fixture_dir=GITHUB_FIXTURE
    )
    assert again.watermark_cursor >= result.watermark_cursor


def test_since_is_read_and_threaded_for_append(tmp_path: Path, monkeypatch) -> None:
    config = append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="alice")
    scope_id = collection_scope(
        config, repo="acme/model-service", fixture_dir=GITHUB_FIXTURE, token_env=cr.DEFAULT_TOKEN_ENV
    )
    write_watermark(tmp_path, "github-security", "2020-01-01T00:00:00Z", scope_id=scope_id)

    seen: dict[str, object] = {}
    real_build = cr.REGISTRY["github-security"]

    def _spy(inputs):
        seen["since"] = inputs.since
        return real_build(inputs)

    monkeypatch.setitem(cr.REGISTRY, "github-security", _spy)
    cr.run_connector_sync(
        tmp_path, connector_id="github-security", repo="acme/model-service", fixture_dir=GITHUB_FIXTURE
    )
    # The prior cursor is read and handed to the builder as ``since``.
    assert seen["since"] == "2020-01-01T00:00:00Z"


def test_snapshot_connector_sync_records_no_cursor(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="aws-posture", state="enabled", actor="alice")
    result = cr.run_connector_sync(tmp_path, connector_id="aws-posture", fixture_dir=AWS_FIXTURE)
    assert result.result == "ok"
    assert result.watermark_cursor is None
    assert read_watermark(tmp_path, "aws-posture") is None
