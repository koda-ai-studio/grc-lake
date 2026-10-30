"""Connector health / silent-failure detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from security_lakehouse.connector_health import build_connector_health, evaluate_connector_health
from security_lakehouse.connector_state import append_config_event, append_run_event
from security_lakehouse.ingestion_status import build_ingestion_status

NOW = datetime(2026, 6, 27, 12, 0, tzinfo=UTC)


def _health(last_success_at: datetime | None, *, enabled: bool = True, slo: int = 60) -> str:
    return evaluate_connector_health(
        connector_id="x",
        enabled=enabled,
        freshness_slo_minutes=slo,
        last_success_at=last_success_at,
        now=NOW,
    )["health"]


def test_health_classifications_by_age_vs_slo() -> None:
    assert _health(NOW - timedelta(minutes=30)) == "healthy"  # within one SLO
    assert _health(NOW - timedelta(minutes=90)) == "degraded"  # > 1 SLO
    assert _health(NOW - timedelta(hours=5)) == "silent"  # > 3 SLO (180m)
    assert _health(None) == "never_succeeded"  # enabled, never an ok sync
    assert _health(None, enabled=False) == "disabled"


def test_failed_sync_does_not_count_as_success(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="aws-posture", state="enabled", actor="a")
    # Only a failed sync on record -> still never_succeeded (the clock is keyed on ok).
    append_run_event(tmp_path, connector_id="aws-posture", kind="sync", result="error", actor="a", error="boom")
    health = build_connector_health(tmp_path)
    aws = next(c for c in health["connectors"] if c["connector_id"] == "aws-posture")
    assert aws["health"] == "never_succeeded"


def test_stale_success_is_flagged_silent(tmp_path: Path) -> None:
    config = append_config_event(tmp_path, connector_id="aws-posture", state="enabled", actor="a")
    append_run_event(
        tmp_path,
        connector_id="aws-posture",
        kind="sync",
        result="ok",
        actor="a",
        evidence_count=5,
        access_fingerprint=config["credential_fingerprint"],
    )

    # Evaluated now: the success is fresh.
    fresh = build_connector_health(tmp_path)
    assert next(c for c in fresh["connectors"] if c["connector_id"] == "aws-posture")["health"] == "healthy"

    # Evaluated far in the future: the same success is now well past the SLO.
    future = build_connector_health(tmp_path, now=datetime.now(UTC) + timedelta(days=30))
    aws = next(c for c in future["connectors"] if c["connector_id"] == "aws-posture")
    assert aws["health"] == "silent"
    assert future["summary"]["silent"] >= 1
    assert future["summary"]["unhealthy"] >= 1


def test_ingestion_status_surfaces_silent_connectors(tmp_path: Path) -> None:
    # Enabled but never successfully synced -> silent-failure signal.
    append_config_event(tmp_path, connector_id="okta-identity", state="enabled", actor="a")
    status = build_ingestion_status(tmp_path)

    assert "health" in status
    assert status["summary"]["silent_connectors"] >= 1
    actions = [a["action"] for a in status["recommended_actions"]]
    assert "investigate_silent_connectors" in actions
    # It is a p0 (silent failure rots the pipeline quietly).
    silent_action = next(a for a in status["recommended_actions"] if a["action"] == "investigate_silent_connectors")
    assert silent_action["priority"] == "p0"
