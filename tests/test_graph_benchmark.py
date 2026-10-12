"""The measurement harness must enforce correctness rather than just time reads."""

import pytest
from tools.benchmark_investigation import run_workload, validate_response


def test_dangling_edges_and_foreign_tenant_data_fail_measurement():
    with pytest.raises(ValueError, match="dangling"):
        validate_response({"nodes": [], "edges": [{"source": "x", "target": "y"}]}, "tenant-0", 150)
    with pytest.raises(ValueError, match="tenant"):
        validate_response(
            {"nodes": [{"id": "x", "source_account_id": "tenant-1-account-a"}], "edges": []}, "tenant-0", 150
        )


def test_small_workload_checks_generation_isolation_and_records_all_queries(tmp_path):
    report = run_workload(tmp_path, rows=12, tenants=2, concurrency=2, repeats=1)
    assert report["correctness_ok"]
    assert report["checks"] == {
        "source_account_isolation": True,
        "exact_bindings": True,
        "duplicate_records": True,
        "pinned_concurrent_publication": True,
        "stale_version_rejected": True,
        "overlay_version_rejected": True,
        "root_pagination": True,
    }
    assert {r["query"] for r in report["reads"]} >= {
        "first",
        "repeat",
        "depth1",
        "depth3",
        "layers",
        "search",
        "roots_page2",
        "concurrent",
    }
    assert len([r for r in report["reads"] if r["query"] == "concurrent"]) == 4
    assert report["model_counts"]["evidence_type"] == 12
    assert report["input_rows_including_duplicates"] == 13
    assert report["retained_bytes"] > 0


def test_watchdog_retains_stop_and_removes_worker_scratch(tmp_path):
    from types import SimpleNamespace

    from tools.benchmark_investigation import attempt

    args = SimpleNamespace(scratch=tmp_path, min_free_gib=1, tenants=1, repeats=1, timeout=0.001, max_rss_mib=1024)
    result = attempt(args, 1000, 1)
    assert result["stopped"] == "timeout"
    assert not list(tmp_path.iterdir())


def test_disk_floor_refuses_start(tmp_path):
    from types import SimpleNamespace

    from tools.benchmark_investigation import attempt

    args = SimpleNamespace(scratch=tmp_path, min_free_gib=10**9)
    assert attempt(args, 1000, 1)["stopped"] == "disk_floor_before_start"
    assert not list(tmp_path.iterdir())
