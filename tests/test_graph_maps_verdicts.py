"""The framework map and the investigation view must give one verdict per record."""

from __future__ import annotations

from pathlib import Path

from security_lakehouse.graph import build_compliance_graph, compliance_graph_view
from security_lakehouse.investigation_graph import investigation_graph
from test_api_v1 import _write_jsonl


def _event(tenant: str, day: str) -> dict[str, object]:
    return {
        "tenant_id": tenant,
        "event_id": "shared-id",
        "asset_id": "shared-user",
        "asset_type": "identity_user",
        "source": "okta",
        "event_type": "identity.mfa",
        "control_ids": ["SOC2-CC6.1"],
        "status": "pass",
        "event_time": "2026-10-01T00:00:00Z",
        "evidence_collected_at": f"2026-10-{day}T01:00:00Z",
    }


def _lake(tmp_path: Path) -> Path:
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", [_event("account-a", "01"), _event("account-b", "02")])
    _write_jsonl(
        tmp_path / "gold/evidence_freshness.jsonl",
        [
            {
                "tenant_id": "account-a",
                "event_id": "shared-id",
                "asset_id": "shared-user",
                "status": "fresh",
                "age_minutes": 60,
            },
            {
                "tenant_id": "account-b",
                "event_id": "shared-id",
                "asset_id": "shared-user",
                "status": "expired",
                "age_minutes": 9000,
            },
        ],
    )
    _write_jsonl(
        tmp_path / "gold/control_posture.jsonl", [{"control_id": "SOC2-CC6.1", "status": "stale", "risk_score": 40}]
    )
    _write_jsonl(
        tmp_path / "gold/control_tests.jsonl",
        [
            {
                "control_id": "SOC2-CC6.1",
                "result": "needs_evidence",
                "missing_evidence_types": ["identity.access_review"],
            }
        ],
    )
    return tmp_path


def test_map_control_verdict_matches_the_investigation_view(tmp_path: Path) -> None:
    lake = _lake(tmp_path)
    mapped = {n["id"]: n for n in build_compliance_graph(lake)["nodes"]}
    investigated = {n["id"]: n for n in investigation_graph(lake, root="control:SOC2-CC6.1")["nodes"]}
    control = mapped["control:SOC2-CC6.1"]
    assert control["status"] == investigated["control:SOC2-CC6.1"]["status"] == "needs_evidence"
    assert control["posture_status"] == "stale"
    assert control["missing_evidence_types"] == ["identity.access_review"]


def test_map_evidence_carries_exact_freshness_without_cross_account_fallback(tmp_path: Path) -> None:
    lake = _lake(tmp_path)
    evidence = [n for n in build_compliance_graph(lake)["nodes"] if n["kind"] == "evidence_type"]
    assert {n["freshness_status"] for n in evidence} == {"fresh", "expired"}
    by_collected = {n["collected_at"]: n for n in evidence}
    assert by_collected["2026-10-01T01:00:00Z"]["freshness_status"] == "fresh"
    assert by_collected["2026-10-02T01:00:00Z"]["freshness_status"] == "expired"
    assert by_collected["2026-10-02T01:00:00Z"]["freshness_age_minutes"] == 9000


def test_map_evidence_without_a_receipt_reads_missing(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", [_event("account-a", "01")])
    (evidence,) = [n for n in build_compliance_graph(tmp_path)["nodes"] if n["kind"] == "evidence_type"]
    assert evidence["freshness_status"] == "missing"


def test_map_cache_follows_control_tests_and_freshness(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", [_event("account-a", "01")])
    _write_jsonl(tmp_path / "gold/control_posture.jsonl", [{"control_id": "SOC2-CC6.1", "status": "stale"}])
    first = {n["id"]: n for n in compliance_graph_view(tmp_path)["nodes"]}
    assert first["control:SOC2-CC6.1"]["status"] == "stale"
    _write_jsonl(tmp_path / "gold/control_tests.jsonl", [{"control_id": "SOC2-CC6.1", "result": "pass"}])
    _write_jsonl(
        tmp_path / "gold/evidence_freshness.jsonl",
        [{"tenant_id": "account-a", "event_id": "shared-id", "asset_id": "shared-user", "status": "fresh"}],
    )
    second = {n["id"]: n for n in compliance_graph_view(tmp_path)["nodes"]}
    assert second["control:SOC2-CC6.1"]["status"] == "pass"
    assert [n for n in second.values() if n["kind"] == "evidence_type"][0]["freshness_status"] == "fresh"
