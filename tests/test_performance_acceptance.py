"""A bounded performance gate must reject incomplete or misleading receipts."""

from copy import deepcopy

import pytest
from tools.check_performance_acceptance import evaluate


def receipt():
    reads = []
    for tenant in ("tenant-0", "tenant-1"):
        for query in ("first", "after_idle", "balanced", "skewed", "sustained"):
            reads.append(
                {
                    "tenant": tenant,
                    "query": query,
                    "http_status": 200,
                    "error_code": None,
                    "seconds": 0.1,
                    "client_queue_seconds": 0.0,
                }
            )
    return {
        "schema_version": "grc.investigation_benchmark.v2",
        "revision": "a" * 40,
        "tracked_diff_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "untracked_source_sha256": {},
        "configuration": {
            "transport": "http",
            "tenants": 2,
            "sizes": [1000, 10000],
            "concurrency": [4],
            "frozen_catalogs": True,
            "model_cache": "shipped policy",
            "sustained_seconds": 30,
            "idle_seconds": 61,
            "seed": 910,
            "repeats": 3,
            "http": {
                "server_processes": 1,
                "graph_build_concurrency": "shipped default",
                "query": {"view": "environment", "root": "own account-a asset-0", "depth": 1, "limit": 150},
            },
        },
        "attempts": [
            {
                "rows": rows,
                "unique_records_per_tenant": rows,
                "concurrency": 4,
                "correctness_ok": True,
                "peak_rss_mib": 320,
                "checks": {
                    key: True
                    for key in (
                        "unauthenticated_rejected",
                        "invalid_credential_rejected",
                        "exact_bindings",
                        "duplicate_records",
                        "source_account_isolation",
                        "account_collision_isolation",
                        "foreign_root_rejected",
                        "stale_version_rejected",
                        "all_submitted_reads_answered",
                        "admission_slots_released",
                    )
                },
                "reads": deepcopy(reads),
                "scenarios": {
                    "sustained": {
                        "wall_seconds": 30,
                        "per_tenant": {tenant: {"max_success_gap_seconds": 1.0} for tenant in ("tenant-0", "tenant-1")},
                    }
                },
            }
            for rows in (1000, 10000)
        ],
    }


def test_complete_receipt_reports_successes_and_rejections_separately():
    data = receipt()
    data["attempts"][0]["reads"].append(
        {
            "tenant": "tenant-0",
            "query": "sustained",
            "http_status": 503,
            "error_code": "graph_tenant_capacity",
            "seconds": 0.02,
            "client_queue_seconds": 0,
        }
    )
    result = evaluate(data, revision="a" * 40)
    tenant = result[0]["tenants"]["tenant-0"]
    assert tenant["admitted"] == 1 and tenant["rejected"] == 1
    assert tenant["admission_fraction"] == 0.5
    assert tenant["warm_p95_seconds"] == 0.1


def test_a_transport_failure_without_http_status_is_not_an_admission_rejection():
    data = receipt()
    data["attempts"][0]["reads"].append(
        {
            "tenant": "tenant-0",
            "query": "sustained",
            "http_status": None,
            "error_code": None,
            "error_type": "ReadTimeout",
            "seconds": 0.1,
            "client_queue_seconds": 0,
        }
    )
    with pytest.raises(ValueError, match="transport"):
        evaluate(data, revision="a" * 40)


@pytest.mark.parametrize("change", ["workers", "admission", "depth", "actual_rows"])
def test_measured_server_and_dataset_must_match_the_declared_profile(change):
    data = receipt()
    if change == "workers":
        data["configuration"]["http"]["server_processes"] = 2
    elif change == "admission":
        data["configuration"]["http"]["graph_build_concurrency"] = 100
    elif change == "depth":
        data["configuration"]["http"]["query"]["depth"] = 0
    else:
        data["attempts"][0]["unique_records_per_tenant"] = 12
    with pytest.raises(ValueError):
        evaluate(data, revision="a" * 40)


@pytest.mark.parametrize(
    "field,value",
    [("peak_rss_mib", 1025), ("peak_rss_mib", float("nan")), ("correctness_ok", False), ("stopped", "timeout")],
)
def test_stops_failed_correctness_and_memory_limits_cannot_pass(field, value):
    data = receipt()
    data["attempts"][0][field] = value
    with pytest.raises(ValueError):
        evaluate(data, revision="a" * 40)


@pytest.mark.parametrize(
    "query,seconds",
    [("first", 5.1), ("after_idle", 5.1), ("sustained", 0.51), ("sustained", float("inf")), ("sustained", -1)],
)
def test_latency_gate_includes_cold_idle_and_warm_reads(query, seconds):
    data = receipt()
    next(r for r in data["attempts"][0]["reads"] if r["query"] == query)["seconds"] = seconds
    with pytest.raises(ValueError):
        evaluate(data, revision="a" * 40)


@pytest.mark.parametrize("missing", ["tenant", "attempt", "cold", "check", "sustained", "progress"])
def test_omitted_work_or_missing_progress_is_not_a_fast_success(missing):
    data = receipt()
    attempt = data["attempts"][0]
    if missing == "tenant":
        attempt["reads"] = [r for r in attempt["reads"] if r["tenant"] != "tenant-1"]
    elif missing == "attempt":
        data["attempts"].pop()
    elif missing == "cold":
        attempt["reads"] = [r for r in attempt["reads"] if r["query"] != "first"]
    elif missing == "check":
        del attempt["checks"]["exact_bindings"]
    elif missing == "progress":
        attempt["scenarios"]["sustained"]["per_tenant"]["tenant-1"]["max_success_gap_seconds"] = 4
    else:
        attempt["reads"] = [r for r in attempt["reads"] if r["query"] != "sustained"]
    with pytest.raises(ValueError):
        evaluate(data, revision="a" * 40)


@pytest.mark.parametrize("change", ["dirty", "revision", "cache", "duration", "unexpected_error"])
def test_changed_source_scope_or_unexpected_failures_cannot_pass(change):
    data = receipt()
    if change == "dirty":
        data["untracked_source_sha256"] = {"src/untracked.py": "abc"}
    elif change == "revision":
        data["revision"] = "b" * 40
    elif change == "cache":
        data["configuration"]["model_cache"] = "override"
    elif change == "duration":
        data["configuration"]["sustained_seconds"] = 1
    else:
        data["attempts"][0]["reads"][0]["http_status"] = 500
    with pytest.raises(ValueError):
        evaluate(data, revision="a" * 40)
