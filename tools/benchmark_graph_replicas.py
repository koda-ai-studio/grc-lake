"""Measure simultaneous synthetic HTTP workers; no shared-store or load-balancer qualification."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def measure_replicas(scratch, *, rows, replicas, clients, seconds, timeout=300, max_rss_mib=4096):
    processes, outputs = [], []
    peak, simultaneous = 0.0, 0
    stopped = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="grc-replicas-", dir=scratch) as temporary, ExitStack() as output_stack:
        root = Path(temporary)
        try:
            if shutil.disk_usage(root).free < 5 * 2**30:
                return {"correctness_ok": False, "stopped": "disk_floor"}
            for index in range(replicas):
                lake = root / str(index)
                lake.mkdir()
                output = output_stack.enter_context(tempfile.TemporaryFile(mode="w+"))
                outputs.append(output)
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            str(ROOT / "tools/benchmark_investigation.py"),
                            "--worker",
                            "--transport",
                            "http",
                            "--sizes",
                            str(rows),
                            "--tenants",
                            "2",
                            "--concurrency",
                            str(clients),
                            "--repeats",
                            "1",
                            "--frozen-catalogs",
                            "--seed",
                            "910",
                            "--sustained-seconds",
                            str(seconds),
                            "--scratch",
                            str(lake),
                        ],
                        cwd=ROOT,
                        stdout=output,
                        stderr=subprocess.DEVNULL,
                    )
                )
            while active := [p for p in processes if p.poll() is None]:
                if time.monotonic() - started > timeout:
                    stopped = "timeout"
                elif shutil.disk_usage(root).free < 5 * 2**30:
                    stopped = "disk_floor"
                sampled = subprocess.run(
                    ["ps", "-o", "rss=", "-p", ",".join(str(p.pid) for p in active)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                values = [int(value) for value in sampled.stdout.split()]
                simultaneous = max(simultaneous, len(values))
                peak = max(peak, sum(values) / 1024)
                if peak > max_rss_mib:
                    stopped = "rss_limit"
                if stopped:
                    break
                time.sleep(0.25)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait()
            reports = []
            for output in outputs:
                try:
                    output.seek(0)
                    reports.append(json.load(output))
                except (ValueError, OSError):
                    reports.append({"correctness_ok": False, "failed": "worker_incomplete"})
                finally:
                    output.close()
        return {
            "correctness_ok": stopped is None and all(r.get("correctness_ok") for r in reports),
            "stopped": stopped,
            "elapsed_seconds": time.monotonic() - started,
            "peak_aggregate_rss_mib": peak,
            "max_simultaneous_processes": simultaneous,
            "replicas": reports,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--replicas", type=int, default=2)
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--scratch", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (
        not (
            2 <= args.rows <= 100000
            and 1 <= args.replicas <= 4
            and 1 <= args.clients <= 8
            and 0 < args.seconds <= 300
            and 0 < args.timeout <= 1800
        )
        or args.out.exists()
    ):
        parser.error("require bounded workloads and a new output path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
        "configuration": {
            "rows_per_tenant": args.rows,
            "tenants": 2,
            "replicas": args.replicas,
            "clients_per_replica": args.clients,
            "sustained_seconds": args.seconds,
            "sample_seconds": 0.25,
            "aggregate_rss_limit_mib": 4096,
            "min_free_gib": 5,
        },
        "limitations": [
            "Independent scratch SQLite databases; no shared-store replica consistency proof",
            "One host; each sampled worker includes its HTTP clients and server",
            "Sampled simultaneous RSS, not the sum of separately observed peaks",
            "No production capacity, failover, latency SLO or approved memory budget",
        ],
        **measure_replicas(
            args.scratch,
            rows=args.rows,
            replicas=args.replicas,
            clients=args.clients,
            seconds=args.seconds,
            timeout=args.timeout,
        ),
    }
    with args.out.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({"correctness_ok": report["correctness_ok"], "report": str(args.out)}))
    return 0 if report["correctness_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
