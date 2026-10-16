"""Synthetic authenticated loopback reads; no deployment or fairness guarantee."""

from __future__ import annotations

import json
import os
import resource
import secrets
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

import httpx
import uvicorn
from tools.benchmark_investigation import (
    COLLIDING_ACCOUNT,
    distribution,
    expected_evidence_ids,
    fixture_rows,
    make_generation,
    validate_response,
)

from security_lakehouse.generations import publish_generation
from security_lakehouse.graph_admission import graph_build_settings
from security_lakehouse.investigation_graph import _id
from security_lakehouse.io import canonical_sha256, file_sha256

ROUTE = "/api/v1/graph/investigation"
# Explicit fail-fast server responses: saturation evidence, not correctness failures.
ADMISSION_CODES = ("graph_build_capacity", "graph_build_timeout")


@contextmanager
def local_configuration():
    """Only used in a dedicated benchmark worker (or an isolated test)."""
    saved = {k: v for k, v in os.environ.items() if k.startswith(("GRC_LAKE_", "TRUSTOPS_"))}
    for key in saved:
        del os.environ[key]
    os.environ["GRC_LAKE_COOKIE_SIGNING_KEY"] = secrets.token_hex(32)
    try:
        yield
    finally:
        for key in list(os.environ):
            if key.startswith(("GRC_LAKE_", "TRUSTOPS_")):
                del os.environ[key]
        os.environ.update(saved)


@contextmanager
def loopback_server(app, shutdown_timeout=10):
    # Server and clients live in the watchdog's worker process. Killing it also
    # closes the listening socket; no detached server process can survive it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        failed = False
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("loopback server startup failed")
                time.sleep(0.01)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        except BaseException:
            failed = True
            raise
        finally:
            server.should_exit = True
            thread.join(timeout=shutdown_timeout)
            # A server still computing an abandoned request must not replace
            # the request failure that caused it; the worker exit reaps it.
            if thread.is_alive() and not failed:
                raise RuntimeError("loopback server shutdown failed")


def admission_rejected(receipt):
    return receipt["http_status"] == 503 and receipt["error_code"] in ADMISSION_CODES


def validate_http_graph(result, tenant, rows, *, seed=None, evidence_ids=None):
    validate_response(result, tenant, 150, evidence_ids=evidence_ids)
    expected = "evidence:" + canonical_sha256(next(fixture_rows(rows, tenant, seed=seed)))
    evidence = [n["id"] for n in result["nodes"] if n["kind"] == "evidence_type"]
    if evidence != [expected]:
        raise ValueError("exact record binding failed")
    if result["counts"]["evidence_type"] != rows:
        raise ValueError("duplicate record produced another node")
    if any(n.get("source_account_id") not in (None, COLLIDING_ACCOUNT) for n in result["nodes"]):
        raise ValueError("source account isolation failed")


def run_http_workload(
    root, *, rows, tenants, concurrency, repeats, progress_path=None, seed=None, graph_build_concurrency=None
):
    with local_configuration():
        if graph_build_concurrency is not None:
            os.environ["GRC_LAKE_GRAPH_BUILD_CONCURRENCY"] = str(graph_build_concurrency)
        return _run_http_workload(
            root,
            rows=rows,
            tenants=tenants,
            concurrency=concurrency,
            repeats=repeats,
            progress_path=progress_path,
            seed=seed,
        )


def _run_http_workload(root, *, rows, tenants, concurrency, repeats, progress_path, seed):
    from security_lakehouse.db.models import Tenant
    from security_lakehouse.db.repository import create_api_key, create_user
    from security_lakehouse.server_app import create_app

    started = time.perf_counter()
    cpu = time.process_time()
    app = create_app(root, require_auth=True)
    _, graph_timeout = graph_build_settings(os.environ)
    # No evaluation jobs are submitted by this read-only workload.
    app.state.job_worker_enabled = False
    credentials = {}
    evidence = {}
    hashes, input_bytes = [], []
    for index in range(tenants):
        tenant = f"tenant-{index}"
        lake = root / "tenants" / tenant
        evidence[tenant] = expected_evidence_ids(rows, tenant, seed=seed)
        generation = make_generation(lake, rows, tenant, seed=seed)
        hashes.append(file_sha256(generation / "silver/normalized_events.jsonl"))
        input_bytes.append((generation / "silver/normalized_events.jsonl").stat().st_size)
        publish_generation(lake, generation)
        with app.state.sessionmaker.begin() as session:
            session.add(Tenant(id=tenant, slug=tenant, name=tenant))
            session.flush()
            user = create_user(session, tenant_id=tenant, email=f"reader@{tenant}.test", role="security_admin")
            _, credentials[tenant] = create_api_key(session, tenant_id=tenant, user_id=user.id)
    reads = []
    checks = {}

    def retain():
        if progress_path is not None:
            temporary = progress_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "completed_reads": reads,
                        "checks": checks,
                        "unique_records_per_tenant": rows,
                        "input_sha256": hashes,
                        "input_bytes_per_tenant": input_bytes,
                    }
                )
            )
            temporary.replace(progress_path)

    try:
        with loopback_server(app) as url, httpx.Client(base_url=url, trust_env=False, timeout=30) as client:
            if client.get(ROUTE).status_code != 401:
                raise ValueError("unauthenticated graph request was accepted")
            if client.get(ROUTE, headers={"Authorization": "Bearer invalid-benchmark-token"}).status_code != 401:
                raise ValueError("invalid credential was accepted")
            checks["unauthenticated_rejected"] = True
            checks["invalid_credential_rejected"] = True

            def request(tenant, scenario, submitted, ordinal):
                request_started = time.perf_counter()
                response = None
                error_type = None
                try:
                    response = client.get(
                        ROUTE,
                        headers={"Authorization": "Bearer " + credentials[tenant]},
                        params={
                            "view": "environment",
                            # Identical for every tenant: the source account collides.
                            "root": _id("asset", COLLIDING_ACCOUNT, "asset-0"),
                            "depth": 1,
                            "limit": 150,
                        },
                    )
                except httpx.HTTPError as exc:
                    error_type = type(exc).__name__
                finished = time.perf_counter()
                error_code = None
                if response is not None and response.status_code == 503:
                    try:
                        error_code = response.json()["errors"][0]["code"]
                    except (ValueError, KeyError, IndexError, TypeError):
                        error_code = None
                receipt = {
                    "tenant": tenant,
                    "query": scenario,
                    "submission_ordinal": ordinal,
                    "http_status": response.status_code if response is not None else None,
                    "error_type": error_type,
                    "error_code": error_code,
                    "retry_after": response.headers.get("retry-after") if response is not None else None,
                    "seconds": finished - request_started,
                    "client_queue_seconds": request_started - submitted,
                    "completion_seconds": finished - started,
                    "response_body_bytes": len(response.content) if response is not None else 0,
                }
                if response is None or response.status_code != 200:
                    return receipt, None
                result = response.json()["data"]
                validate_http_graph(result, tenant, rows, seed=seed, evidence_ids=evidence[tenant])
                receipt.update(response_nodes=len(result["nodes"]), response_edges=len(result["edges"]))
                return receipt, result

            first = {}
            for tenant in credentials:
                receipt, result = request(tenant, "first", time.perf_counter(), len(reads))
                reads.append(receipt)
                retain()
                if result is None:
                    raise ValueError("HTTP first read failed")
                first[tenant] = result
            checks.update(exact_bindings=True, duplicate_records=True, source_account_isolation=True)
            if len(first) > 1:
                # Same root ID string, yet each tenant received only its own record.
                if len({r["root"] for r in first.values()}) != 1:
                    raise ValueError("colliding root was not shared")
                bound = [n["id"] for r in first.values() for n in r["nodes"] if n["kind"] == "evidence_type"]
                if len(set(bound)) != len(first):
                    raise ValueError("colliding source account shared an evidence record across tenants")
                checks["account_collision_isolation"] = True
            for tenant in credentials:
                foreign = next((other for other in credentials if other != tenant), "tenant-missing")
                response = client.get(
                    ROUTE,
                    headers={"Authorization": "Bearer " + credentials[tenant]},
                    # The non-colliding account exists only in the other tenant.
                    params={"view": "environment", "root": _id("asset", foreign + "-account-b", "asset-0")},
                )
                if response.status_code != 200:
                    raise ValueError("foreign-root probe failed")
                result = response.json()["data"]
                if result["nodes"] or not result["root_missing"]:
                    raise ValueError("foreign tenant root was accessible")
            checks["foreign_root_rejected"] = True

            scenarios = {}
            for scenario in ("balanced", "skewed"):
                batch = []
                for _ in range(repeats * 2):
                    for tenant in credentials:
                        batch.extend([tenant] * (4 if scenario == "skewed" and tenant == "tenant-0" else 1))
                burst_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = [
                        pool.submit(request, tenant, scenario, time.perf_counter(), i) for i, tenant in enumerate(batch)
                    ]
                    for future in as_completed(futures):
                        receipt, _ = future.result()
                        reads.append(receipt)
                        retain()
                burst_seconds = time.perf_counter() - burst_started
                samples = [r for r in reads if r["query"] == scenario]
                if any(r["http_status"] != 200 and not admission_rejected(r) for r in samples):
                    raise ValueError("HTTP concurrent read failed")
                admitted = [r for r in samples if r["http_status"] == 200]
                scenarios[scenario] = {
                    "reads": len(samples),
                    "admitted": len(admitted),
                    "rejected": len(samples) - len(admitted),
                    "clients": concurrency,
                    "wall_seconds": burst_seconds,
                    "reads_per_second": len(samples) / burst_seconds,
                    "per_tenant": {
                        tenant: {
                            "submitted": batch.count(tenant),
                            "completed": sum(r["tenant"] == tenant for r in samples),
                            "admitted": sum(r["tenant"] == tenant for r in admitted),
                            "rejected": {
                                code: sum(r["tenant"] == tenant and r["error_code"] == code for r in samples)
                                for code in ADMISSION_CODES
                            },
                            "latency_seconds": distribution([r["seconds"] for r in admitted if r["tenant"] == tenant]),
                            "rejection_latency_seconds": distribution(
                                [r["seconds"] for r in samples if r["tenant"] == tenant and admission_rejected(r)]
                            ),
                            "client_queue_seconds": distribution(
                                [r["client_queue_seconds"] for r in samples if r["tenant"] == tenant]
                            ),
                        }
                        for tenant in credentials
                    },
                }
            checks["all_submitted_reads_answered"] = True
            if app.state.graph_build_slots.active:
                raise ValueError("graph build slot leaked after the bursts")
            checks["admission_slots_released"] = True
            tenant = "tenant-0"
            lake = root / "tenants" / tenant
            publish_generation(lake, make_generation(lake, rows, tenant, changed=True, seed=seed))
            response = client.get(
                ROUTE,
                headers={"Authorization": "Bearer " + credentials[tenant]},
                params={"version": first[tenant]["version"]},
            )
            if response.status_code != 400 or "version changed" not in response.text:
                raise ValueError("stale graph version was accepted")
            checks["stale_version_rejected"] = True
            retain()
    finally:
        app.state.sessionmaker.kw["bind"].dispose()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2**20 if sys.platform == "darwin" else 1024)
    return {
        "correctness_ok": True,
        "checks": checks,
        "scenarios": scenarios,
        "admission": {
            "graph_build_concurrency": app.state.graph_build_slots.capacity,
            "graph_build_timeout_seconds": graph_timeout,
        },
        "transport": "http",
        "seed": seed,
        "retained_bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()),
        "unique_records_per_tenant": rows,
        "input_rows_including_duplicates": rows + 1,
        "input_sha256": hashes,
        "input_bytes_per_tenant": input_bytes,
        "model_counts": first["tenant-0"]["counts"],
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "peak_rss_mib": rss,
        "reads": reads,
    }
