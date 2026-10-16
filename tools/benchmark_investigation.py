"""Bounded synthetic direct or loopback HTTP graph reads; not production capacity."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from security_lakehouse.generations import new_generation, pin_generation, publish_generation, seal_generation
from security_lakehouse.investigation_graph import _id, investigation_graph
from security_lakehouse.io import canonical_sha256, file_sha256, write_jsonl_from_iterable

ROOT = Path(__file__).resolve().parents[1]
# Every platform tenant reuses this source account ID (for example two
# customers connecting the same cloud account), so isolation cannot rely on it.
COLLIDING_ACCOUNT = "shared-account-a"
SEEDED_CONTROLS = ("SOC2-CC6.1", "SOC2-CC6.2", "SOC2-CC6.3", "SOC2-CC6.6", "SOC2-CC7.1", "SOC2-CC7.2", "SOC2-CC8.1")
SEEDED_ASSET_TYPES = ("iam_role", "iam_user", "s3_bucket", "ec2_instance")


def validate_response(result, tenant, limit, *, evidence_ids=None):
    nodes = result["nodes"]
    identities = {n["id"] for n in nodes}
    if len(nodes) > limit or len(identities) != len(nodes):
        raise ValueError("node bound or uniqueness failed")
    if any(e["source"] not in identities or e["target"] not in identities for e in result["edges"]):
        raise ValueError("dangling edge")
    accounts = {COLLIDING_ACCOUNT, tenant + "-account-b"}
    if any(n.get("source_account_id") and n["source_account_id"] not in accounts for n in nodes):
        raise ValueError("tenant isolation failed")
    if evidence_ids is not None and any(
        n.get("kind") == "evidence_type" and n["id"] not in evidence_ids for n in nodes
    ):
        raise ValueError("tenant isolation failed: foreign evidence record")


def fixture_rows(rows, tenant, *, changed=False, seed=None):
    # No seed keeps the uniform shape of earlier receipts. A seed varies controls,
    # outcomes and asset types identically for every tenant.
    rng = random.Random(seed) if seed is not None else None
    for index in range(rows):
        if rng is None:
            controls = ["SOC2-CC6.1" if index % 2 == 0 else "SOC2-CC7.2"]
            failed = index % 5 == 0
            asset_type = "iam_role"
        else:
            controls = sorted(rng.sample(SEEDED_CONTROLS, rng.randint(1, 3)))
            failed = rng.random() < 0.2
            asset_type = rng.choice(SEEDED_ASSET_TYPES)
        yield {
            "event_id": f"event-{index // 2}",
            "tenant_id": COLLIDING_ACCOUNT if index % 2 == 0 else f"{tenant}-account-b",
            "asset_id": f"asset-{index // 2}",
            "asset_type": asset_type,
            "source": "synthetic",
            "event_type": "identity.access_review",
            "event_time": "2026-10-12T00:00:00Z",
            "control_ids": controls,
            "status": "failed" if failed else "pass",
            "severity": "high" if failed else "info",
            "environment": "changed" if changed and index == 0 else "benchmark",
            "raw_sha256": hashlib.sha256(f"{tenant}:{index}".encode()).hexdigest(),
        }


def expected_evidence_ids(rows, tenant, *, seed=None):
    return {"evidence:" + canonical_sha256(record) for record in fixture_rows(rows, tenant, seed=seed)}


def make_generation(lake, rows, tenant, *, changed=False, seed=None):
    generation = new_generation(lake)
    path = generation / "silver/normalized_events.jsonl"
    records = list(fixture_rows(rows, tenant, changed=changed, seed=seed))
    # Exact duplicate must not create an extra graph node or edge.
    write_jsonl_from_iterable(path, [*records, records[0]])
    seal_generation(generation, legacy=True)
    return generation


def timed_read(lake, tenant, query, kwargs, submitted=None, evidence_ids=None):
    start = time.perf_counter()
    cpu = time.thread_time()
    result = investigation_graph(lake, **kwargs)
    elapsed = time.perf_counter() - start
    cpu_elapsed = time.thread_time() - cpu
    validate_response(result, tenant, kwargs.get("limit", 150), evidence_ids=evidence_ids)
    receipt = {
        "tenant": tenant,
        "query": query,
        "seconds": elapsed,
        "cpu_seconds": cpu_elapsed,
        "queue_seconds": max(0, start - submitted) if submitted is not None else 0,
        "response_nodes": len(result["nodes"]),
        "response_edges": len(result["edges"]),
        "matching_nodes": result["matching_nodes"],
        "truncated": result["truncated"],
        "serialized_bytes": len(json.dumps(result, separators=(",", ":")).encode()),
    }
    return receipt, result


def require_rejection(fn):
    try:
        fn()
    except ValueError as exc:
        if "version changed" in str(exc):
            return
        raise
    raise ValueError("stale version was accepted")


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return {}
    return {f"p{p}": ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)] for p in (50, 95, 99)}


def control_page_query(lake):
    """Find a safeguard root whose mapped controls span more than one page."""
    # Restrict layers so evidence records cannot crowd safeguards out of the cap.
    anchor = investigation_graph(lake, root="control:SOC2-CC6.1", depth=1, layers={"control", "safeguard"})
    for safeguard in sorted(n["id"] for n in anchor["nodes"] if n["kind"] == "safeguard"):
        groups = investigation_graph(lake, root=safeguard)["framework_groups"]
        paged = [g["framework_id"] for g in groups if g["control_count"] > 5]
        if paged:
            return {"root": safeguard, "framework": paged[0]}
    raise ValueError("control pagination unavailable")


def run_workload(root, *, rows, tenants, concurrency, repeats, progress_path=None, seed=None):
    started = time.perf_counter()
    cpu = time.process_time()
    lakes = [root / f"tenant-{i}" for i in range(tenants)]
    evidence = {lake.name: expected_evidence_ids(rows, lake.name, seed=seed) for lake in lakes}
    hashes = []
    input_bytes = []
    for lake in lakes:
        generation = make_generation(lake, rows, lake.name, seed=seed)
        hashes.append(file_sha256(generation / "silver/normalized_events.jsonl"))
        input_bytes.append((generation / "silver/normalized_events.jsonl").stat().st_size)
        publish_generation(lake, generation)
    reads = []

    def retain_progress():
        if progress_path is not None:
            temporary = progress_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "completed_reads": reads,
                        "unique_records_per_tenant": rows,
                        "input_sha256": hashes,
                        "input_bytes_per_tenant": input_bytes,
                    }
                )
            )
            temporary.replace(progress_path)

    first = None
    colliding_root = _id("asset", COLLIDING_ACCOUNT, "asset-0")
    bound = {}
    for lake in lakes:
        receipt, result = timed_read(lake, lake.name, "first", {}, evidence_ids=evidence[lake.name])
        reads.append(receipt)
        retain_progress()
        if first is None:
            first = result
        paging = control_page_query(lake)
        pages = {}
        for query, kwargs in (
            ("repeat", {}),
            ("depth1", {"depth": 1}),
            ("depth3", {"depth": 3}),
            ("layers", {"layers": {"control", "evidence_type", "asset"}}),
            ("search", {"view": "environment", "search": "asset-0"}),
            ("search_miss", {"view": "environment", "search": "no-such-synthetic-asset"}),
            ("roots_page2", {"root_offset": 50}),
            ("controls_page1", paging),
            ("controls_page2", {**paging, "control_offset": 5}),
        ):
            for _ in range(repeats):
                receipt, result = timed_read(lake, lake.name, query, kwargs, evidence_ids=evidence[lake.name])
                reads.append(receipt)
                retain_progress()
                pages[query] = result
        if pages["search_miss"]["matching_nodes"]:
            raise ValueError("search matched a nonexistent asset")
        page_controls = [
            {n["id"] for n in pages[q]["nodes"] if n["kind"] == "control"} for q in pages if "controls" in q
        ]
        if (
            pages["controls_page1"]["next_control_offset"] != 5
            or not all(page_controls)
            or set.intersection(*page_controls)
        ):
            raise ValueError("control pagination failed")
        # A one-hop asset neighborhood must bind exactly the record from its
        # tenant and account. Every tenant requests the identical root ID.
        scoped = investigation_graph(lake, view="environment", root=colliding_root, depth=1)
        validate_response(scoped, lake.name, 150, evidence_ids=evidence[lake.name])
        expected_record = next(fixture_rows(rows, lake.name, seed=seed))
        bound[lake.name] = [n["id"] for n in scoped["nodes"] if n["kind"] == "evidence_type"]
        if bound[lake.name] != ["evidence:" + canonical_sha256(expected_record)]:
            raise ValueError("exact record binding failed")
        if any(n.get("source_account_id") not in (None, COLLIDING_ACCOUNT) for n in scoped["nodes"]):
            raise ValueError("source account isolation failed")
        if scoped["counts"]["evidence_type"] != rows:
            raise ValueError("duplicate record produced another node")
    if len({ids[0] for ids in bound.values()}) != len(lakes):
        raise ValueError("colliding source account shared an evidence record across tenants")
    page2 = investigation_graph(lakes[0], root_offset=50, expected_version=first["version"])
    if not page2["roots"] or {n["id"] for n in first["roots"]} & {n["id"] for n in page2["roots"]}:
        raise ValueError("root pagination failed")
    # Round-robin submitted local reads; queue measurements describe this
    # harness executor, not the server scheduler or HTTP request admission.
    burst_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        for _ in range(repeats * 2):
            for lake in lakes:
                futures.append(
                    pool.submit(timed_read, lake, lake.name, "concurrent", {}, time.perf_counter(), evidence[lake.name])
                )
        for future in futures:
            receipt, _ = future.result()
            reads.append(receipt)
            retain_progress()
    burst_seconds = time.perf_counter() - burst_started
    lake = lakes[0]
    replacement = make_generation(lake, rows, lake.name, changed=True, seed=seed)
    with pin_generation(lake):
        with ThreadPoolExecutor(max_workers=1) as writer:
            writer.submit(publish_generation, lake, replacement).result()
        pinned = investigation_graph(lake, expected_version=first["version"])
        if pinned["version"] != first["version"]:
            raise ValueError("concurrent publication changed a pinned read")
    require_rejection(lambda: investigation_graph(lake, expected_version=first["version"]))
    current = investigation_graph(lake)
    require_rejection(
        lambda: investigation_graph(
            lake,
            expected_version=current["version"],
            vendors=[{"id": "synthetic", "vendor_name": "Synthetic", "asset_refs": []}],
        )
    )
    concurrent = [r for r in reads if r["query"] == "concurrent"]
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2**20 if sys.platform == "darwin" else 1024)
    return {
        "correctness_ok": True,
        "checks": dict.fromkeys(
            (
                "source_account_isolation",
                "exact_bindings",
                "duplicate_records",
                "pinned_concurrent_publication",
                "stale_version_rejected",
                "overlay_version_rejected",
                "root_pagination",
                # A single tenant cannot exercise a cross-tenant collision.
                *(("account_collision_isolation",) if len(lakes) > 1 else ()),
                "control_pagination",
            ),
            True,
        ),
        "seed": seed,
        "unique_records_per_tenant": rows,
        "input_rows_including_duplicates": rows + 1,
        "input_sha256": hashes,
        "input_bytes_per_tenant": input_bytes,
        "model_counts": first["counts"],
        "retained_bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "peak_rss_mib": rss,
        "concurrent_burst": {
            "reads": len(concurrent),
            "workers": concurrency,
            "wall_seconds": burst_seconds,
            "reads_per_second": len(concurrent) / burst_seconds,
        },
        "concurrent_latency_seconds": distribution([r["seconds"] for r in concurrent]),
        "concurrent_queue_seconds": distribution([r["queue_seconds"] for r in concurrent]),
        "per_tenant": {
            lake.name: {
                "completed": sum(r["tenant"] == lake.name for r in concurrent),
                "latency_seconds": distribution([r["seconds"] for r in concurrent if r["tenant"] == lake.name]),
            }
            for lake in lakes
        },
        "reads": reads,
    }


def attempt(args, rows, concurrency):
    # Shared hosts are noisy; retain contention alongside every attempt.
    before = list(os.getloadavg())
    result = _attempt(args, rows, concurrency)
    return {**result, "load_average_before": before, "load_average_after": list(os.getloadavg())}


def _attempt(args, rows, concurrency):
    seed = getattr(args, "seed", None)
    slots = getattr(args, "graph_build_concurrency", None)
    with tempfile.TemporaryDirectory(prefix="grc-graph-benchmark-", dir=args.scratch) as folder:
        if shutil.disk_usage(folder).free < args.min_free_gib * 2**30:
            return {"stopped": "disk_floor_before_start"}
        with tempfile.TemporaryFile(mode="w+") as output:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--worker",
                    "--transport",
                    getattr(args, "transport", "direct"),
                    "--sizes",
                    str(rows),
                    "--tenants",
                    str(args.tenants),
                    "--concurrency",
                    str(concurrency),
                    "--repeats",
                    str(args.repeats),
                    "--scratch",
                    folder,
                    *(("--seed", str(seed)) if seed is not None else ()),
                    *(("--graph-build-concurrency", str(slots)) if slots is not None else ()),
                ],
                stdout=output,
                stderr=subprocess.DEVNULL,
                cwd=ROOT,
            )
            started = time.monotonic()
            stopped = None
            sampled_peak_rss_kib = 0
            try:
                while process.poll() is None:
                    if time.monotonic() - started > args.timeout:
                        stopped = "timeout"
                    elif shutil.disk_usage(folder).free < args.min_free_gib * 2**30:
                        stopped = "disk_floor"
                    else:
                        sampled = subprocess.run(
                            ["ps", "-o", "rss=", "-p", str(process.pid)], capture_output=True, text=True
                        )
                        if sampled.returncode == 0 and sampled.stdout.strip():
                            sampled_peak_rss_kib = max(sampled_peak_rss_kib, int(sampled.stdout.strip()))
                            if sampled_peak_rss_kib > args.max_rss_mib * 1024:
                                stopped = "rss_limit"
                    if stopped:
                        process.kill()
                        break
                    time.sleep(0.25)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
            output.seek(0)
            if stopped:
                progress = Path(folder) / "progress.json"
                partial = json.loads(progress.read_text()) if progress.is_file() else {}
                return {
                    "stopped": stopped,
                    "elapsed_seconds": time.monotonic() - started,
                    "sampled_peak_rss_mib": sampled_peak_rss_kib / 1024,
                    **partial,
                }
            try:
                report = json.load(output)
            except (ValueError, OSError):
                report = {"failed": "worker_failed", "returncode": process.returncode}
            if process.returncode:
                report["correctness_ok"] = False
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--tenants", type=int, default=2)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--max-rss-mib", type=int, default=2048)
    parser.add_argument("--min-free-gib", type=float, default=5)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--transport", choices=("direct", "http"), default="direct")
    parser.add_argument("--seed", type=int, help="vary controls, outcomes and asset types deterministically")
    parser.add_argument(
        "--graph-build-concurrency", type=int, help="HTTP only: server graph build slots (default: shipped value)"
    )
    args = parser.parse_args()
    if (
        not all(2 <= n <= 100000 for n in args.sizes)
        or not 1 <= args.tenants <= 4
        or not all(1 <= n <= 8 for n in args.concurrency)
        or not 1 <= args.repeats <= 10
        or args.timeout <= 0
        or args.max_rss_mib <= 0
        or args.min_free_gib < 1
        or (args.graph_build_concurrency is not None and not 1 <= args.graph_build_concurrency <= 64)
        or (args.graph_build_concurrency is not None and args.transport != "http")
    ):
        parser.error(
            "require 2-100000 rows, 1-4 tenants, 1-8 workers, 1-10 repeats, positive watchdogs, >=1 GiB free"
            " and HTTP-only 1-64 graph build slots"
        )
    if args.worker:
        try:
            workload = run_workload
            if args.transport == "http":
                # Direct script execution puts tools/, not the repo root, on sys.path.
                sys.path.insert(0, str(ROOT))
                from tools.benchmark_investigation_http import run_http_workload

                workload = run_http_workload
            options = {"graph_build_concurrency": args.graph_build_concurrency} if args.transport == "http" else {}
            result = workload(
                args.scratch,
                rows=args.sizes[0],
                tenants=args.tenants,
                concurrency=args.concurrency[0],
                repeats=args.repeats,
                progress_path=args.scratch / "progress.json",
                seed=args.seed,
                **options,
            )
        except Exception as exc:  # noqa: BLE001 — worker boundary retains a failed attempt, never success
            progress = args.scratch / "progress.json"
            partial = json.loads(progress.read_text()) if progress.is_file() else {}
            print(
                json.dumps({"correctness_ok": False, "error_type": type(exc).__name__, "failed": str(exc), **partial})
            )
            return 1
        print(json.dumps(result))
        return 0
    if args.out is None or args.out.exists():
        parser.error("--out must name a new receipt; preserve all attempts")
    untracked = (
        subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
    )
    report = {
        "untracked_source_sha256": {
            name: file_sha256(ROOT / name) for name in untracked if name and (ROOT / name).is_file()
        },
        "schema_version": "grc.investigation_benchmark.v2",
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tracked_diff_sha256": hashlib.sha256(
            subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=ROOT)
        ).hexdigest(),
        "harness_sha256": file_sha256(Path(__file__)),
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "machine": platform.machine(),
            "physical_memory_bytes": (
                int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
                if sys.platform == "darwin"
                else os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            ),
            "storage": "local filesystem, synthetic legacy-compatible generations",
            "cache": "OS and shared catalog caches uncontrolled; first means first graph call per tenant",
        },
        "configuration": {
            "transport": args.transport,
            "tenants": args.tenants,
            "repeats": args.repeats,
            "sizes": args.sizes,
            "concurrency": args.concurrency,
            "timeout_seconds": args.timeout,
            "sampled_rss_limit_mib": args.max_rss_mib,
            "min_free_gib": args.min_free_gib,
            "sample_seconds": 0.25,
            "seed": args.seed,
            "fixture": (
                "uniform two-control fixture" if args.seed is None else "seeded mixed controls/outcomes/asset types"
            )
            + "; every tenant shares source account "
            + COLLIDING_ACCOUNT,
        },
        "limitations": [
            "Direct graph-function reads, no HTTP authentication or scheduler fairness proof",
            "Synthetic normalized records, not full pipeline or provider evidence",
            "Thread concurrency on one host",
            "No object-store failover, crash recovery or production SLO",
            "Watchdogs are sampled safety stops, not reviewer-approved capacity budgets",
        ],
        "attempts": [],
    }
    if args.transport == "http":
        from importlib.metadata import version

        report["http_harness_sha256"] = file_sha256(ROOT / "tools/benchmark_investigation_http.py")
        report["configuration"]["http"] = {
            "server_processes": 1,
            "client_timeout_seconds": 30,
            "auth_role": "security_admin",
            "database": "scratch SQLite",
            "query": {"view": "environment", "root": "own account-a asset-0", "depth": 1, "limit": 150},
            "graph_build_concurrency": args.graph_build_concurrency or "shipped default",
            "dependencies": {name: version(name) for name in ("fastapi", "starlette", "anyio", "uvicorn", "httpx")},
        }
        report["limitations"] = [
            "Authenticated loopback HTTP, one Uvicorn process with default thread-pool and rate limits",
            "Balanced and 4:1 skewed client submissions; client queue delay is not server scheduler delay",
            "Explicit 503 admission rejections are retained per tenant; they are not retried",
            "Client and server share one process and host; RSS and CPU include both",
            "Synthetic normalized records, SQLite state, no evaluation jobs or provider evidence",
            "Response body bytes exclude HTTP headers; no production fairness, SLO or capacity budget",
            "No object-store failover, crash recovery or distributed admission qualification",
        ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the path before starting; retain intermediate completed attempts.
    args.out.touch(exist_ok=False)
    for rows in sorted(set(args.sizes)):
        for concurrency in sorted(set(args.concurrency)):
            result = {"rows": rows, "concurrency": concurrency, **attempt(args, rows, concurrency)}
            report["attempts"].append(result)
            args.out.write_text(json.dumps(report, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in result.items()
                        if k
                        in (
                            "rows",
                            "concurrency",
                            "correctness_ok",
                            "stopped",
                            "failed",
                            "peak_rss_mib",
                            "wall_seconds",
                        )
                    }
                ),
                flush=True,
            )
            if not result.get("correctness_ok"):
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
