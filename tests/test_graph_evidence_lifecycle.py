"""Graph lifecycle timestamps retain their meaning and exact account/asset scope."""

from security_lakehouse.investigation_graph import investigation_graph
from test_api_v1 import _write_jsonl


def test_lifecycle_uses_exact_evidence_receipt_without_cross_account_fallback(tmp_path):
    events = []
    receipts = []
    for account, day in [("account-a", "01"), ("account-b", "02")]:
        events.append(
            {
                "tenant_id": account,
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
        )
        receipts.append(
            {
                "tenant_id": account,
                "event_id": "shared-id",
                "asset_id": "shared-user",
                "status": "fresh",
                "evaluated_at": f"2026-10-{day}T02:00:00Z",
                "expires_at": f"2026-10-{day}T03:00:00Z",
                "age_minutes": 60,
            }
        )
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", events)
    _write_jsonl(tmp_path / "gold/evidence_freshness.jsonl", receipts)
    result = investigation_graph(tmp_path, root="control:SOC2-CC6.1")
    evidence = {n["source_account_id"]: n for n in result["nodes"] if n["kind"] == "evidence_type"}
    for account, day in [("account-a", "01"), ("account-b", "02")]:
        node = evidence[account]
        assert node["observed_at"] == "2026-10-01T00:00:00Z"
        assert node["collected_at"] == f"2026-10-{day}T01:00:00Z"
        assert node["freshness_evaluated_at"] == f"2026-10-{day}T02:00:00Z"
        assert node["freshness_expires_at"] == f"2026-10-{day}T03:00:00Z"
        assert node["freshness_age_minutes"] == 60


def test_legacy_observation_does_not_invent_collection_or_evaluation_time(tmp_path):
    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "tenant_id": "account-a",
                "event_id": "legacy",
                "asset_id": "user",
                "asset_type": "identity_user",
                "source": "okta",
                "event_type": "identity.mfa",
                "control_ids": ["SOC2-CC6.1"],
                "status": "observed",
                "event_time": "2026-10-01T00:00:00Z",
            }
        ],
    )
    _write_jsonl(
        tmp_path / "gold/evidence_freshness.jsonl",
        [
            {
                "tenant_id": "account-b",
                "event_id": "legacy",
                "asset_id": "user",
                "status": "fresh",
                "evaluated_at": "2026-10-01T02:00:00Z",
            }
        ],
    )
    result = investigation_graph(tmp_path, root="control:SOC2-CC6.1")
    [node] = [n for n in result["nodes"] if n["kind"] == "evidence_type"]
    assert node["collected_at"] is None
    assert node["freshness_evaluated_at"] is None
    assert node["freshness_expires_at"] is None
    assert node["freshness_status"] == "missing"


def test_pipeline_projection_reaches_graph_without_changing_receipts(tmp_path):
    from pathlib import Path

    from security_lakehouse.io import read_jsonl
    from security_lakehouse.pipeline import run_pipeline

    raw = Path(__file__).resolve().parents[1] / "data/raw/security_events.jsonl"
    run_pipeline(raw, tmp_path / "lake", tenant_id="platform-test")
    lake = tmp_path / "lake"
    silver = {(row["tenant_id"], row["event_id"]): row for row in read_jsonl(lake / "silver/normalized_events.jsonl")}
    freshness = {(row["tenant_id"], row["event_id"]): row for row in read_jsonl(lake / "gold/evidence_freshness.jsonl")}
    before = (lake / "gold/evidence_freshness.jsonl").read_bytes()
    result = investigation_graph(lake, root="control:SOC2-CC6.1", depth=3)
    evidence = [node for node in result["nodes"] if node["kind"] == "evidence_type"]
    assert evidence
    for node in evidence:
        key = node["source_account_id"], node["evidence_id"]
        assert node["observed_at"] == silver[key]["event_time"]
        assert node["collected_at"] == silver[key]["evidence_collected_at"]
        assert node["freshness_evaluated_at"] == freshness[key]["evaluated_at"]
        assert node["freshness_status"] == freshness[key]["status"]
        assert node["freshness_expires_at"] == freshness[key].get("expires_at")
        assert node["raw_sha256"] == silver[key]["raw_sha256"]
    assert (lake / "gold/evidence_freshness.jsonl").read_bytes() == before
