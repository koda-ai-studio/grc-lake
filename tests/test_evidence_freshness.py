from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from security_lakehouse.evidence_freshness import (
    build_evidence_freshness,
    summarize_control_freshness,
    summarize_source_freshness,
)
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.programs import build_control_tests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "security_events.jsonl"


def _event(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "event_id": "evt-runtime",
        "tenant_id": "tenant",
        "event_time": "2026-05-24T00:00:00Z",
        "source": "runtime-gateway",
        "event_type": "runtime.tool_call",
        "asset_id": "agent:demo",
        "asset_type": "ai_agent",
        "asset_owner": "ai-security",
        "environment": "prod",
        "severity": "low",
        "severity_score": 20,
        "status": "observed",
        "control_ids": ["NIST-AI-RMF-MEASURE-2.7"],
        "evidence_id": "evt-runtime",
        "evidence_ref": "s3://evidence/runtime.json",
        "evidence_collected_at": "2026-05-24T00:00:00Z",
        "raw_sha256": "a" * 64,
    }
    row.update(overrides)
    return row


def test_evidence_freshness_uses_connector_slo() -> None:
    rows = [_event()]

    records = build_evidence_freshness(rows, now=datetime(2026, 5, 24, 0, 6, tzinfo=UTC))

    assert records[0]["connector_id"] == "runtime-gateway"
    assert records[0]["freshness_slo_minutes"] == 5
    assert records[0]["status"] == "stale"
    assert records[0]["score"] == 30
    assert records[0]["next_action"] == "refresh stale runtime-gateway evidence and rerun affected control tests"


def test_source_freshness_surfaces_workflow_action() -> None:
    rows = [
        _event(
            source="runtime-gateway",
            event_type="runtime.tool_call",
            evidence_collected_at="2026-05-24T00:00:00Z",
        ),
        _event(
            event_id="evt-runtime-missing",
            source="runtime-gateway",
            event_type="runtime.policy_decision",
            evidence_ref="",
        ),
    ]

    records = build_evidence_freshness(rows, now=datetime(2026, 5, 24, 0, 6, tzinfo=UTC))
    sources = summarize_source_freshness(records)

    assert sources == [
        {
            "source": "runtime-gateway",
            "connector_id": "runtime-gateway",
            "fresh_count": 0,
            "stale_count": 1,
            "expired_count": 0,
            "missing_count": 1,
            "evidence_count": 2,
            "latest_evidence_at": "2026-05-24T00:00:00Z",
            "freshness_slo_minutes": 5,
            "state": "action_required",
            "status": "missing",
            "next_action": "request missing runtime-gateway evidence and confirm collection metadata",
        }
    ]


def test_control_test_moves_to_needs_evidence_when_required_evidence_is_stale() -> None:
    silver_rows = [
        _event(status="passed", event_id="evt-runtime", event_type="runtime.tool_call"),
        _event(status="passed", event_id="evt-detection", event_type="detection.alert"),
        _event(status="passed", event_id="evt-vuln", event_type="vulnerability.finding"),
        _event(status="passed", event_id="evt-ticket", event_type="remediation.ticket"),
    ]
    control_rows = [
        {
            "control_id": "NIST-AI-RMF-MEASURE-2.7",
            "framework": "NIST AI RMF",
            "title": "AI runtime risk indicators are measured and acted on",
            "risk_domain": "ai-security",
            "owner": "ai-security",
            "status": "pass",
            "risk_score": 20,
            "event_count": 1,
            "open_event_count": 0,
            "evidence_count": 1,
            "evidence_coverage": 1.0,
            "latest_event_time": "2026-05-24T00:00:00Z",
        }
    ]

    tests = build_control_tests(silver_rows, control_rows, now=datetime(2026, 5, 24, 0, 6, tzinfo=UTC))

    assert tests[0]["result"] == "needs_evidence"
    assert tests[0]["status"] == "collecting"
    assert tests[0]["freshness_status"] == "stale"
    assert tests[0]["stale_evidence_types"] == [
        "detection.alert",
        "remediation.ticket",
        "runtime.tool_call",
        "vulnerability.finding",
    ]
    assert tests[0]["next_action"].startswith("refresh stale detection.alert")


def test_control_freshness_marks_missing_required_types() -> None:
    summary = summarize_control_freshness(
        [_event(event_type="runtime.tool_call")],
        required_evidence_types=["runtime.tool_call", "detection.alert"],
        now=datetime(2026, 5, 24, 0, 1, tzinfo=UTC),
    )

    assert summary["status"] == "stale"
    assert summary["missing_evidence_types"] == ["detection.alert"]
    assert summary["stale_evidence_types"] == []


def test_pipeline_writes_evidence_freshness_gold_and_mart(tmp_path: Path) -> None:
    result = run_pipeline(RAW, tmp_path / "lake")

    evidence_freshness = read_jsonl(tmp_path / "lake" / "gold" / "evidence_freshness.jsonl")
    metrics = read_json(result.metrics_path)
    posture = read_json(tmp_path / "lake" / "gold" / "current_posture.json")
    manifest = read_json(tmp_path / "lake" / "manifest.json")

    assert len(evidence_freshness) == result.silver_count
    assert {row["status"] for row in evidence_freshness} <= {"fresh", "stale", "expired", "missing"}
    assert metrics["evidence_freshness_count"] == result.silver_count
    assert "stale_evidence_count" in metrics
    assert posture["evidence_freshness"]["count"] == result.silver_count
    assert all("next_action" in row for row in posture["evidence_freshness"]["stale_evidence"])
    assert all("next_action" in row for row in posture["evidence_freshness"]["sources"])
    assert manifest["zones"]["gold_evidence_freshness"].endswith("evidence_freshness.jsonl")

    with sqlite3.connect(result.mart_path) as conn:
        count = conn.execute("select count(*) from evidence_freshness").fetchone()[0]

    assert count == result.silver_count


def test_control_freshness_without_required_types_uses_latest_evidence_age() -> None:
    old = _event(evidence_collected_at="2026-02-26T00:00:00Z", event_time="2026-02-26T00:00:00Z")

    summary = summarize_control_freshness(
        [old],
        required_evidence_types=[],
        now=datetime(2026, 5, 24, 0, 0, tzinfo=UTC),
    )

    assert summary["status"] == "expired"
    assert summary["score"] == 0
    assert summary["expired_evidence_types"] == ["runtime.tool_call"]
    assert summary["latest_evidence_at"] == "2026-02-26T00:00:00Z"


def test_control_freshness_without_required_types_stale_when_between_one_and_two_slos() -> None:
    summary = summarize_control_freshness(
        [_event(source="manual-upload", evidence_collected_at="2026-05-22T12:00:00Z")],
        required_evidence_types=[],
        now=datetime(2026, 5, 24, 0, 0, tzinfo=UTC),
    )

    assert summary["status"] == "stale"
    assert summary["score"] == 30


def test_control_freshness_without_required_types_fresh_when_latest_row_is_current() -> None:
    summary = summarize_control_freshness(
        [
            _event(event_id="old", source="manual-upload", evidence_collected_at="2026-02-26T00:00:00Z"),
            _event(event_id="new", source="manual-upload", evidence_collected_at="2026-05-23T23:00:00Z"),
        ],
        required_evidence_types=[],
        now=datetime(2026, 5, 24, 0, 0, tzinfo=UTC),
    )

    assert summary["status"] == "fresh"
    assert summary["score"] == 100


def test_control_freshness_without_required_types_or_evidence_is_missing() -> None:
    summary = summarize_control_freshness(
        [],
        required_evidence_types=[],
        now=datetime(2026, 5, 24, 0, 0, tzinfo=UTC),
    )

    assert summary["status"] == "missing"
    assert summary["score"] == 0
