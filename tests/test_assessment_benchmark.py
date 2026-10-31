"""Benchmark results must check labeled CCF outcomes, not only row counts."""

from datetime import UTC, datetime

from tools.benchmark_assessment_pipeline import worker

from security_lakehouse.io import read_jsonl


def test_ccf_workload_checks_outcomes_and_source_tenant_boundaries(tmp_path):
    result = worker(10, workload="ccf", root=tmp_path, base_time=datetime(2020, 1, 1, tzinfo=UTC))
    assert result["silver_count"] == 10
    assert result["integrity_ok"]
    assert result["ccf_labels_ok"]
    assert result["ccf_asset_count"] == 10
    assert result["ccf_asset_result_count"] == 8
    assert result["ccf_status_counts"] == {"pass": 2, "fail": 2, "not_evaluated": 2, "stale": 2}

    rows = read_jsonl(tmp_path / "raw.jsonl")
    assert all(row["event_type"] == "nist53_ac_10_assessment" for row in rows)
    assert all(row["controls"] == ["NIST-800-53-AC-10"] for row in rows)
