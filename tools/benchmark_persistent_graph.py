"""Bounded prepared-index HTTP measurements; not end-to-end ingestion or production capacity."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def records(count, *, assets, findings, tenant):
    if not 0 < assets <= count or not 0 <= findings <= count:
        raise ValueError("require 0 < assets <= records and 0 <= findings <= records")
    for index in range(count):
        asset = index % assets
        yield {
            "event_id": f"event-{index}",
            "tenant_id": "shared-account" if asset % 2 == 0 else "account-b",
            "asset_id": f"asset-{asset // 2}",
            "asset_type": "iam_role",
            "source": "synthetic",
            "event_type": "identity.access_review",
            "event_time": "2026-10-31T00:00:00Z",
            "control_ids": ["SOC2-CC6.1"],
            "status": "fail" if index < findings else "pass",
            "severity": "high" if index < findings else "info",
            "raw_sha256": hashlib.sha256(f"{tenant}:{index}".encode()).hexdigest(),
        }


def worker(args):
    import httpx
    from tools.benchmark_investigation_http import loopback_server

    from security_lakehouse.catalog import load_control_catalog
    from security_lakehouse.db.models import Tenant
    from security_lakehouse.db.repository import create_api_key, create_user
    from security_lakehouse.generations import new_generation, publish_generation, seal_generation
    from security_lakehouse.graph_index_cli import prepare_index
    from security_lakehouse.investigation_graph import _id
    from security_lakehouse.io import canonical_sha256, file_sha256, write_json, write_jsonl_from_iterable
    from security_lakehouse.mapping_review import effective_safeguards
    from security_lakehouse.server_app import create_app

    app = create_app(args.scratch, require_auth=True)
    app.state.job_worker_enabled = False
    receipts, credentials, reads = [], {}, []
    result = {"preparation": receipts, "reads": reads, "correctness_ok": False}

    def retain():
        write_json(args.scratch / "progress.json", result)

    try:
        for index in range(args.tenants):
            tenant = f"benchmark-{index}"
            lake = args.scratch / "tenants" / tenant
            generation = new_generation(lake)
            normalized = generation / "silver/normalized_events.jsonl"
            write_jsonl_from_iterable(
                normalized, records(args.records, assets=args.assets, findings=args.findings, tenant=tenant)
            )
            write_json(generation / "catalog/control_map.json", {"controls": list(load_control_catalog().values())})
            write_json(generation / "catalog/safeguards.json", effective_safeguards(lake))
            seal_generation(generation, legacy=True)
            publish_generation(lake, generation)
            with app.state.sessionmaker.begin() as session:
                session.add(Tenant(id=tenant, slug=tenant, name=tenant))
                session.flush()
                user = create_user(session, tenant_id=tenant, email=f"reader@{tenant}.test", role="security_admin")
                _, credentials[tenant] = create_api_key(session, tenant_id=tenant, user_id=user.id)
            prepared = prepare_index(lake, tenant=tenant, vendors=[], timeout=args.timeout)
            assert prepared["counts"]["asset"] == args.assets
            assert prepared["counts"]["evidence_type"] == args.records
            assert prepared["counts"].get("finding", 0) == args.findings
            receipts.append({"tenant": tenant, **prepared, "input_sha256": file_sha256(normalized)})
            retain()
        # Separate preparation/file timestamp validation from settled read measurements.
        time.sleep(2.1)
        with loopback_server(app) as url, httpx.Client(base_url=url, timeout=75, trust_env=False) as client:
            route = "/api/v1/graph/investigation"
            assert client.get(route).status_code == 401
            assert client.get(route, headers={"Authorization": "Bearer invalid-fixture-key"}).status_code == 401
            queries = [
                ("asset", {"view": "environment", "root": _id("asset", "shared-account", "asset-0"), "depth": 1}),
                ("account", {"view": "environment", "root": _id("account", "shared-account"), "depth": 1}),
                (
                    "root_page",
                    {
                        "view": "environment",
                        "root": _id("asset", "shared-account", "asset-0"),
                        "depth": 1,
                        "root_offset": max(0, args.assets // 2),
                    },
                ),
                ("control", {"root": "control:SOC2-CC6.1", "depth": 2}),
            ]
            for tenant, credential in credentials.items():
                for name, query in queries:
                    for repeat in range(args.repeats):
                        started = time.perf_counter()
                        response = client.get(
                            route, headers={"Authorization": "Bearer " + credential}, params={**query, "limit": 150}
                        )
                        read = {
                            "tenant": tenant,
                            "query": name,
                            "repeat": repeat + 1,
                            "seconds": time.perf_counter() - started,
                            "http_status": response.status_code,
                        }
                        reads.append(read)
                        retain()
                        if response.status_code != 200:
                            raise ValueError("prepared graph read failed")
                        data = response.json()["data"]
                        identities = {row["id"] for row in data["nodes"]}
                        assert len(identities) == len(data["nodes"]) <= 150
                        assert all(e["source"] in identities and e["target"] in identities for e in data["edges"])
                        for node in data["nodes"]:
                            if node["kind"] == "evidence_type":
                                index = int(node["evidence_id"].split("-")[1])
                                asset = index % args.assets
                                expected = {
                                    "event_id": f"event-{index}",
                                    "tenant_id": "shared-account" if asset % 2 == 0 else "account-b",
                                    "asset_id": f"asset-{asset // 2}",
                                    "asset_type": "iam_role",
                                    "source": "synthetic",
                                    "event_type": "identity.access_review",
                                    "event_time": "2026-10-31T00:00:00Z",
                                    "control_ids": ["SOC2-CC6.1"],
                                    "status": "fail" if index < args.findings else "pass",
                                    "severity": "high" if index < args.findings else "info",
                                    "raw_sha256": hashlib.sha256(f"{tenant}:{index}".encode()).hexdigest(),
                                }
                                assert node["id"] == "evidence:" + canonical_sha256(expected)
                        read.update(
                            nodes=len(data["nodes"]), edges=len(data["edges"]), matching_nodes=data["matching_nodes"]
                        )
                        retain()
        result["correctness_ok"] = True
    finally:
        app.state.sessionmaker.kw["bind"].dispose()
        result["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
            2**20 if sys.platform == "darwin" else 1024
        )
        retain()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100000)
    parser.add_argument("--assets", type=int, default=10000)
    parser.add_argument("--findings", type=int, default=100000)
    parser.add_argument("--tenants", type=int, choices=(1, 2), default=1)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-rss-mib", type=int, default=1536)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scratch", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not (0 < args.assets <= args.records <= 2000000 and 0 <= args.findings <= args.records):
        parser.error("require 0 < assets <= records <= 2000000 and 0 <= findings <= records")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.max_rss_mib <= 0:
        parser.error("resource bounds must be positive")
    if args.worker:
        sys.path.insert(0, str(ROOT))
        from tools.benchmark_investigation_http import local_configuration

        try:
            with local_configuration():
                print(json.dumps(worker(args)))
            return 0
        except Exception as exc:  # noqa: BLE001 — retain diagnostic failure, never count it as a passing sample.
            print(json.dumps({"failed": type(exc).__name__, "correctness_ok": False}))
            return 1
    if args.out is None or args.out.exists():
        parser.error("--out must be a new receipt path")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="grc-prepared-graph-") as scratch, tempfile.TemporaryFile(mode="w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--scratch",
                scratch,
                "--records",
                str(args.records),
                "--assets",
                str(args.assets),
                "--findings",
                str(args.findings),
                "--tenants",
                str(args.tenants),
                "--repeats",
                str(args.repeats),
                "--timeout",
                str(args.timeout),
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.DEVNULL,
        )
        peak, stopped = 0, None
        try:
            while process.poll() is None:
                sampled = subprocess.run(["ps", "-o", "rss=", "-p", str(process.pid)], capture_output=True, text=True)
                if sampled.stdout.strip():
                    peak = max(peak, int(sampled.stdout.strip()))
                if peak > args.max_rss_mib * 1024:
                    stopped = "rss_limit"
                elif time.monotonic() - started > args.timeout:
                    stopped = "timeout"
                elif shutil.disk_usage(scratch).free < 10 * 2**30:
                    stopped = "disk_floor"
                if stopped:
                    process.kill()
                    break
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
        progress = Path(scratch) / "progress.json"
        result = json.loads(progress.read_text()) if progress.exists() else {"correctness_ok": False}
        if stopped or process.returncode:
            result["correctness_ok"] = False
        receipt = {
            "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "tracked_diff_sha256": hashlib.sha256(
                subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=ROOT)
            ).hexdigest(),
            "untracked_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in subprocess.check_output(
                    ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
                ).splitlines()
            },
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "measured_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "load_average_after": os.getloadavg(),
            "configuration": {k: v for k, v in vars(args).items() if k not in {"out", "worker", "scratch"}},
            "scope": "Sequential prepared-index HTTP reads; synthetic normalized evidence, not ingestion, provider accuracy, saturation or HA.",
            "elapsed_seconds": time.monotonic() - started,
            "sampled_peak_rss_mib": peak / 1024,
            "stopped": stopped,
            "worker_exit_code": process.returncode,
            "result": result,
        }
        args.out.write_text(json.dumps(receipt, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "correctness_ok": result["correctness_ok"],
                    "stopped": stopped,
                    "elapsed_seconds": receipt["elapsed_seconds"],
                    "sampled_peak_rss_mib": peak / 1024,
                }
            )
        )
        return 0 if result["correctness_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
