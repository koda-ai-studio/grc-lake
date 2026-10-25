"""Check the bounded local graph release profile, not a production capacity claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

__all__ = ["evaluate"]

CHECKS = (
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
REJECTIONS = {"graph_build_capacity": 503, "graph_tenant_capacity": 503, "rate_limited": 429}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "invalid measurement")
    return value


def percentile95(values):
    require(bool(values), "missing latency samples")
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def evaluate(report, *, revision):
    """Validate every required attempt and retain admission separately from latency."""
    require(report.get("schema_version") == "grc.investigation_benchmark.v2", "unexpected receipt schema")
    require(report.get("revision") == revision and len(revision) == 40, "unexpected source revision")
    require(report.get("tracked_diff_sha256") == hashlib.sha256(b"").hexdigest(), "dirty measured source")
    require(report.get("untracked_source_sha256") == {}, "untracked measured source")
    configuration = report["configuration"]
    expected = {
        "transport": "http",
        "tenants": 2,
        "sizes": [1000, 10000],
        "concurrency": [4],
        "frozen_catalogs": True,
        "model_cache": "shipped policy",
        "seed": 910,
    }
    require(all(configuration.get(k) == v for k, v in expected.items()), "workload differs from release profile")
    http = configuration["http"]
    require(
        http.get("server_processes") == 1 and http.get("graph_build_concurrency") == "shipped default",
        "server admission differs from release profile",
    )
    require(
        http.get("query") == {"view": "environment", "root": "own account-a asset-0", "depth": 1, "limit": 150},
        "graph query differs from release profile",
    )
    require(number(configuration["sustained_seconds"]) >= 30, "sustained interval too short")
    require(number(configuration["idle_seconds"]) >= 61, "cache expiry not exercised")
    require(number(configuration["repeats"]) >= 3, "insufficient query repetitions")
    attempts = report["attempts"]
    require(len(attempts) == 2 and sorted(a["rows"] for a in attempts) == [1000, 10000], "missing workload attempt")
    results = []
    for attempt in attempts:
        require(attempt.get("correctness_ok") is True, "correctness failed")
        require(not attempt.get("stopped") and not attempt.get("failed"), "incomplete workload")
        require(attempt.get("concurrency") == 4, "unexpected client concurrency")
        require(attempt.get("unique_records_per_tenant") == attempt["rows"], "measured record count differs")
        require(all(attempt.get("checks", {}).get(key) is True for key in CHECKS), "missing correctness check")
        rss = number(attempt["peak_rss_mib"])
        require(rss <= 1024, "process RSS exceeds 1 GiB")
        reads = attempt["reads"]
        tenants = {"tenant-0", "tenant-1"}
        require({r["tenant"] for r in reads} == tenants, "missing or unexpected tenant")
        for row in reads:
            number(row["seconds"])
            number(row["client_queue_seconds"])
            require(
                row["http_status"] == 200
                or (row.get("error_code") in REJECTIONS and REJECTIONS[row["error_code"]] == row["http_status"]),
                "unexpected HTTP or transport failure",
            )
        sustained = attempt["scenarios"]["sustained"]
        require(number(sustained["wall_seconds"]) >= 30, "incomplete sustained workload")
        result = {"rows_per_tenant": attempt["rows"], "peak_rss_mib": rss, "tenants": {}}
        for tenant in sorted(tenants):
            own = [r for r in reads if r["tenant"] == tenant]
            for query in ("first", "after_idle"):
                samples = [r for r in own if r["query"] == query]
                require(len(samples) == 1 and samples[0]["http_status"] == 200, "missing cold or post-idle read")
                require(samples[0]["seconds"] <= 5, "cold or post-idle read exceeds 5 seconds")
            require(
                all(any(r["query"] == query for r in own) for query in ("balanced", "skewed")), "missing burst scenario"
            )
            samples = [r for r in own if r["query"] == "sustained"]
            successful = [r for r in samples if r["http_status"] == 200]
            p95 = percentile95([r["seconds"] + r["client_queue_seconds"] for r in successful])
            require(p95 <= 0.5, "warm p95 exceeds 500 milliseconds")
            gap = number(sustained["per_tenant"][tenant]["max_success_gap_seconds"])
            require(gap <= 2, "tenant progress gap exceeds 2 seconds")
            rejected = [r for r in samples if r["http_status"] != 200]
            result["tenants"][tenant] = {
                "admitted": len(successful),
                "rejected": len(rejected),
                "admission_fraction": len(successful) / len(samples),
                "rejection_codes": {code: sum(r["error_code"] == code for r in rejected) for code in REJECTIONS},
                "warm_p95_seconds": p95,
                "max_success_gap_seconds": gap,
                "cold_seconds": next(r["seconds"] for r in own if r["query"] == "first"),
                "post_idle_seconds": next(r["seconds"] for r in own if r["query"] == "after_idle"),
            }
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipts", nargs="+", type=Path)
    parser.add_argument("--revision", required=True, help="expected measured source commit")
    args = parser.parse_args()
    try:
        results = [evaluate(json.loads(path.read_text()), revision=args.revision) for path in args.receipts]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"performance acceptance failed: {exc}\n")
    print(
        json.dumps(
            {
                "profile": "local-graph-10k-v1",
                "source_commit": args.revision,
                "passed": True,
                "production_capacity_qualified": False,
                "results": results,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
