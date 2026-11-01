"""Benchmark results must check labeled CCF outcomes, not only row counts."""

import json
from datetime import UTC, datetime

import pytest
from tools.benchmark_assessment_pipeline import worker

from security_lakehouse.io import read_jsonl


def test_ccf_workload_checks_outcomes_and_source_tenant_boundaries(tmp_path):
    result = worker(10, workload="ccf", root=tmp_path, base_time=datetime(2020, 1, 1, tzinfo=UTC))
    assert result["silver_count"] == 10
    assert result["integrity_ok"]
    assert result["ccf_labels_ok"]
    assert result["normalized_records_ok"]
    assert result["ccf_asset_count"] == 10
    assert result["ccf_asset_result_count"] == 8
    assert result["ccf_status_counts"] == {"pass": 2, "fail": 2, "not_evaluated": 2, "stale": 2}

    rows = read_jsonl(tmp_path / "raw.jsonl")
    assert all(row["event_type"] == "nist53_ac_10_assessment" for row in rows)
    assert all(row["controls"] == ["NIST-800-53-AC-10"] for row in rows)


def test_framework_workload_checks_record_labels(tmp_path):
    result = worker(10, workload="framework", root=tmp_path, base_time=datetime(2020, 1, 1, tzinfo=UTC))
    assert result["integrity_ok"]
    assert result["normalized_records_ok"]


@pytest.mark.parametrize("mutation", ["status", "controls", "tenant_id"])
def test_framework_label_corruption_fails_even_with_valid_integrity(tmp_path, monkeypatch, mutation):
    from security_lakehouse import pipeline
    from security_lakehouse.io import write_jsonl

    original = pipeline.run_pipeline

    def altered_input(raw, lake, **kwargs):
        rows = read_jsonl(raw)
        rows[0][mutation] = {"status": "not_evaluated", "controls": [], "tenant_id": "different-source"}[mutation]
        write_jsonl(raw, rows)
        return original(raw, lake, **kwargs)

    monkeypatch.setattr(pipeline, "run_pipeline", altered_input)
    result = worker(10, workload="framework", root=tmp_path, base_time=datetime(2020, 1, 1, tzinfo=UTC))
    assert result["silver_count"] == 10
    assert result["integrity_ok"]
    assert result["normalized_records_ok"] is False


def test_record_parity_failure_stops_repeats_and_larger_sizes(monkeypatch, capsys):
    from tools import benchmark_assessment_pipeline as benchmark

    attempts = []

    def mismatched(count, workload, base_time):
        attempts.append(count)
        return {"silver_count": count, "integrity_ok": True, "ccf_labels_ok": True, "normalized_records_ok": False}

    monkeypatch.setattr(benchmark, "attempt", mismatched)
    monkeypatch.setattr("sys.argv", ["benchmark", "--sizes", "1000", "10000", "--repeats", "2"])
    assert benchmark.main() == 1
    assert attempts == [1000]
    assert json.loads(capsys.readouterr().out)["attempts"][0]["normalized_records_ok"] is False
