"""HTTP measurements fail closed and retain authenticated tenant evidence."""

import json
from types import SimpleNamespace

import httpx
import pytest
from tools.benchmark_investigation import attempt


def test_http_workload_uses_auth_and_preserves_tenant_bindings(tmp_path, monkeypatch):
    from tools.benchmark_investigation_http import run_http_workload

    # A benchmark must never migrate an operator's configured database.
    monkeypatch.setenv("TRUSTOPS_DATABASE_URL", "postgresql://must-not-connect.invalid/private")
    monkeypatch.setenv("GRC_LAKE_ALLOW_INSECURE", "1")
    report = run_http_workload(tmp_path, rows=12, tenants=2, concurrency=2, repeats=1)
    assert report["correctness_ok"]
    assert all(report["checks"].values())
    assert report["checks"]["unauthenticated_rejected"]
    assert report["checks"]["foreign_root_rejected"]
    assert report["checks"]["exact_bindings"]
    assert report["checks"]["stale_version_rejected"]
    for scenario in ("balanced", "skewed"):
        assert report["scenarios"][scenario]["per_tenant"]["tenant-1"]["completed"] == 2
    assert report["scenarios"]["skewed"]["per_tenant"]["tenant-0"]["completed"] == 8
    assert all(r["http_status"] == 200 and r["response_body_bytes"] > 0 for r in report["reads"])
    assert "must-not-connect" not in json.dumps(report)
    assert not list(tmp_path.rglob("credentials*"))


def test_http_validation_rejects_an_empty_or_wrong_binding():
    from tools.benchmark_investigation_http import validate_http_graph

    with pytest.raises(ValueError, match="exact record binding"):
        validate_http_graph({"nodes": [], "edges": []}, "tenant-0", 12)


def test_http_watchdog_reaps_server_and_retains_stop(tmp_path):
    args = SimpleNamespace(
        scratch=tmp_path,
        min_free_gib=1,
        tenants=2,
        repeats=1,
        timeout=0.001,
        max_rss_mib=1024,
        transport="http",
    )
    result = attempt(args, 1000, 2)
    assert result["stopped"] == "timeout"
    assert not list(tmp_path.iterdir())


def test_http_parent_dispatches_worker_and_preserves_receipt(tmp_path):
    args = SimpleNamespace(
        scratch=tmp_path,
        min_free_gib=1,
        tenants=2,
        repeats=1,
        timeout=60,
        max_rss_mib=1024,
        transport="http",
    )
    report = attempt(args, 12, 2)
    assert report["correctness_ok"]
    assert report["transport"] == "http"
    assert report["checks"]["foreign_root_rejected"]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("failure", ["status", "timeout"])
def test_failed_http_requests_retain_prior_reads_and_failure_without_secrets(tmp_path, monkeypatch, failure):
    from tools.benchmark_investigation_http import run_http_workload

    original = httpx.Client.get

    def fail_after_first_reads(client, url, **kwargs):
        if kwargs.get("params", {}).get("depth") == 1:
            fail_after_first_reads.count += 1
            if fail_after_first_reads.count > 2:
                if failure == "timeout":
                    raise httpx.ReadTimeout("secret-must-not-be-retained")
                return httpx.Response(503, content=b"unavailable")
        return original(client, url, **kwargs)

    fail_after_first_reads.count = 0
    monkeypatch.setattr(httpx.Client, "get", fail_after_first_reads)
    progress = tmp_path / "progress.json"
    with pytest.raises(ValueError, match="HTTP concurrent read failed"):
        run_http_workload(tmp_path, rows=12, tenants=2, concurrency=1, repeats=1, progress_path=progress)
    report = json.loads(progress.read_text())
    reads = report["completed_reads"]
    assert len([r for r in reads if r["http_status"] == 200]) == 2
    assert any(r["http_status"] != 200 for r in reads)
    assert "secret-must-not-be-retained" not in progress.read_text()
