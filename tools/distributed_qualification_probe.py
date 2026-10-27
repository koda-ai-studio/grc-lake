"""Container-side assertions for the disposable distributed qualification stack."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import httpx
from sqlalchemy import select

from security_lakehouse.db.base import create_engine_for, session_factory
from security_lakehouse.db.models import Tenant
from security_lakehouse.distributed import workspace
from security_lakehouse.distributed.catalog import Catalog, Conflict
from security_lakehouse.distributed.config import ClusterConfig
from security_lakehouse.distributed.objects import ObjectStore
from security_lakehouse.distributed.workspace import Runtime

WORK = Path("/work")
ROOT = Path("/tmp/probe-lake")


def save(name, data):
    temporary = WORK / (name + ".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n")
    temporary.replace(WORK / (name + ".json"))


def load(name):
    return json.loads((WORK / (name + ".json")).read_text())


def runtime():
    config = ClusterConfig.from_env()
    engine = create_engine_for(ROOT)
    catalog = Catalog(engine, config)
    catalog.initialize()
    return Runtime(catalog, ObjectStore(config), ROOT / "scratch"), session_factory(engine)


def request(service, method, path, credential=None, *, timeout=90, **kwargs):
    headers = kwargs.pop("headers", {})
    if credential:
        headers["Authorization"] = "Bearer " + credential["token"]
    return httpx.request(method, f"http://{service}:8787{path}", headers=headers, timeout=timeout, **kwargs)


def ready(services=("api-a", "api-b", "reader")):
    deadline = time.monotonic() + 90
    for service in services:
        while True:
            try:
                response = request(service, "GET", "/api/readyz")
                if response.status_code == 200 and response.json().get("ok"):
                    break
            except httpx.HTTPError:
                # Startup and deliberate service restarts can refuse/reset a
                # connection. Retry only until the bounded readiness deadline.
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{service} readiness deadline exceeded")
            time.sleep(0.5)


def prepare():
    from botocore.exceptions import ClientError

    from security_lakehouse.db.migrate import upgrade
    from security_lakehouse.db.repository import create_api_key, create_user
    from security_lakehouse.pipeline import run_pipeline

    ROOT.mkdir(parents=True, exist_ok=True)
    store = ObjectStore(ClusterConfig.from_env())
    deadline = time.monotonic() + 60
    while True:
        try:
            upgrade(ROOT)
            store.client.list_buckets()
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    store.client.create_bucket(Bucket=store.config.bucket)
    store.verify_conditional_writes()
    key = "clusters/qualification/preflight/race-" + uuid.uuid4().hex

    def contender(index):
        try:
            store.client.put_object(Bucket=store.config.bucket, Key=key, Body=str(index).encode(), IfNoneMatch="*")
            return 1
        except ClientError as exc:
            assert exc.response["ResponseMetadata"]["HTTPStatusCode"] == 412
            return 0

    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(contender, range(8))) == 1
    store.client.delete_object(Bucket=store.config.bucket, Key=key)
    multipart = ROOT / "multipart"
    with multipart.open("wb") as stream:
        for _ in range(33):
            stream.write(b"q" * 1024**2)
    reference = store.put("protocol", multipart)
    assert store.put("protocol", multipart) == reference
    store.get("protocol", reference, ROOT / "restored")
    assert hashlib.sha256((ROOT / "restored").read_bytes()).hexdigest() == reference["sha256"]
    rt, factory = runtime()
    credentials = []
    with factory.begin() as session:
        for index in range(4):
            tenant = Tenant(
                id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"grc-qualification-{index}")),
                slug=f"qualification-{index}",
                name=f"Qualification {index}",
            )
            session.add(tenant)
            session.flush()
            user = create_user(session, tenant_id=tenant.id, email=f"user-{index}@example.test", role="security_admin")
            _, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
            credentials.append(
                {
                    "tenant": tenant.id,
                    "token": token,
                    "name": tenant.name,
                    "shard": rt.catalog.config.shard_for(tenant.id),
                }
            )
    save("credentials", credentials)
    (WORK / "credentials.json").chmod(0o600)
    shards = sorted({c["shard"] for c in credentials})
    assert len(shards) >= 2, "need tenants in at least two shards"
    assignments = [",".join(map(str, shards[::2])), ",".join(map(str, shards[1::2]))]

    def seed(credential):
        writer = Runtime(rt.catalog, ObjectStore(rt.catalog.config), ROOT / credential["tenant"])
        # Distinct evidence makes accidental cross-tenant reads observable.
        raw = ROOT / (credential["tenant"] + ".jsonl")
        rows = [json.loads(line) for line in Path("/fixtures/events.jsonl").read_text().splitlines()]
        for row in rows:
            row["tenant_id"] = credential["tenant"]
            row["event_id"] = credential["tenant"] + "-" + row["event_id"]
            row["entity"]["asset_id"] += ":" + credential["tenant"]
            row["evidence"]["evidence_id"] += "-" + credential["tenant"]
            row["evidence"]["uri"] = row["evidence"]["uri"].replace("acme-prod", credential["tenant"])
        raw.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with writer.write(credential["tenant"]) as lake:
            run_pipeline(raw, lake, tenant_id=credential["tenant"])
        return rt.catalog.head(credential["tenant"]).version

    started = time.monotonic()
    with ThreadPoolExecutor(4) as pool:
        assert list(pool.map(seed, credentials)) == [1] * 4
    save(
        "prepare",
        {
            "conditional_create_racers": 8,
            "conditional_create_winners": 1,
            "multipart_bytes_verified": reference["size"],
            "concurrent_tenants": 4,
            "seed_seconds": time.monotonic() - started,
            "worker_shards": assignments,
        },
    )
    rt.catalog.engine.dispose()


def enqueue():
    ready()
    credentials = load("credentials")

    def submit(index):
        credential = credentials[index]
        response = request(
            "api-a" if index % 2 == 0 else "api-b",
            "POST",
            "/api/v1/ingestion/eval",
            credential,
            headers={"Prefer": "respond-async", "Idempotency-Key": "qualification-" + uuid.uuid4().hex},
            json={},
        )
        assert response.status_code == 202, f"queue admission returned {response.status_code}"
        return {"tenant": credential["tenant"], "job": response.json()["data"]}

    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(submit, range(4)))
    save("jobs", jobs)


def verify():
    from security_lakehouse.distributed.commands import download_partitions

    ready()
    credentials = load("credentials")
    rt, _ = runtime()
    versions = {}
    signatures = {}
    deadline = time.monotonic() + 180
    for credential, job in zip(credentials, load("jobs"), strict=True):
        while True:
            response = request("api-b", "GET", job["job"]["status_url"], credential)
            assert response.status_code == 200
            status = response.json()["data"]["status"]
            if status == "succeeded":
                break
            assert status in {"queued", "running"}, f"unexpected job terminal state {status}"
            assert time.monotonic() < deadline, "workers did not finish before deadline"
            time.sleep(0.5)
        samples = []
        for service in ("api-a", "api-b", "reader"):
            response = request(service, "GET", "/api/v1/evidence?limit=100", credential)
            assert response.status_code == 200
            rows = response.json()["data"]
            assert rows, "published evidence is empty"
            samples.append(hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())
        assert len(set(samples)) == 1, "replicas disagree about committed evidence"
        versions[credential["tenant"]] = rt.catalog.head(credential["tenant"]).version
        signatures[credential["tenant"]] = samples[0]
        selected = download_partitions(
            rt, credential["tenant"], ROOT / "partitions" / credential["tenant"], source="cloud-cspm"
        )
        assert selected["row_count"] > 0
    assert request("reader", "POST", "/api/v1/ingestion/eval", credentials[0], json={}).status_code == 405
    assert request("api-b", "GET", load("jobs")[0]["job"]["status_url"], credentials[1]).status_code == 404
    assert len(set(signatures.values())) == len(credentials), "different tenants must have distinct evidence"
    save("baseline", {"versions": versions, "evidence_sha256": signatures})
    save(
        "verify",
        {
            "jobs_succeeded": len(credentials),
            "replicas_agree": 3,
            "reader_rejects_mutation": True,
            "tenant_job_isolation": True,
            "partition_downloads_verified": len(credentials),
        },
    )
    rt.catalog.engine.dispose()


def stable(phase):
    ready()
    rt, _ = runtime()
    baseline = load("baseline")
    deadline = time.monotonic() + 90
    retries = 0
    try:
        for credential in load("credentials"):
            while True:
                assert rt.catalog.head(credential["tenant"]).version == baseline["versions"][credential["tenant"]]
                remaining = deadline - time.monotonic()
                assert remaining > 0, "evidence recovery deadline exceeded"
                try:
                    response = request(
                        "api-b", "GET", "/api/v1/evidence?limit=100", credential, timeout=min(10, remaining)
                    )
                except httpx.TransportError:
                    # A restarted service can accept connections before its
                    # data plane is available. The same bounded deadline applies.
                    response = None
                if response is not None and response.status_code != 503:
                    assert response.status_code == 200
                    actual = hashlib.sha256(json.dumps(response.json()["data"], sort_keys=True).encode()).hexdigest()
                    assert actual == baseline["evidence_sha256"][credential["tenant"]]
                    break
                retries += 1
                time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        save(
            phase,
            {"committed_versions_preserved": True, "evidence_sha256_preserved": True, "recovery_retries": retries},
        )
    finally:
        rt.catalog.engine.dispose()


def outage(kind):
    credential = load("credentials")[0]
    readiness = request("api-a", "GET", "/api/readyz")
    assert readiness.status_code == 503, "unavailable dependency must fail readiness"
    if kind == "object":
        response = request("api-a", "POST", "/api/v1/ingestion/eval", credential, json={})
    else:
        response = request("api-a", "GET", "/api/v1/operations", credential)
    assert response.status_code == 503, f"dependency outage returned {response.status_code}"
    save(kind + "-outage", {"readiness_status": readiness.status_code, "operation_status": response.status_code})


@contextmanager
def qualification_writer_lease():
    # Only this disposable crash-writer process uses a shorter real lease.
    # Keep natural expiry and heartbeat behavior; production defaults stay intact.
    original = workspace.LEASE_SECONDS, workspace.HEARTBEAT_SECONDS
    workspace.LEASE_SECONDS, workspace.HEARTBEAT_SECONDS = 20, 5
    try:
        yield
    finally:
        workspace.LEASE_SECONDS, workspace.HEARTBEAT_SECONDS = original


def hold_writer():
    rt, factory = runtime()
    credential = load("credentials")[0]
    with qualification_writer_lease(), rt.write(credential["tenant"]) as lake:
        (lake / "uncommitted-crash-marker").write_text("must never publish")
        with factory.begin() as session:
            session.get(Tenant, credential["tenant"]).name = "uncommitted crash mutation"
        save(
            "writer-held",
            {
                "tenant": credential["tenant"],
                "version": rt.catalog.head(credential["tenant"]).version,
                "lease_seconds": workspace.LEASE_SECONDS,
            },
        )
        while True:
            time.sleep(1)


def crash_recovery():
    rt, factory = runtime()
    credential = load("credentials")[0]
    old = load("writer-held")
    assert rt.catalog.head(credential["tenant"]).version == old["version"]
    with factory() as session:
        assert session.scalar(select(Tenant.name).where(Tenant.id == credential["tenant"])) == credential["name"]
    try:
        with rt.write(credential["tenant"]):
            raise AssertionError("killed writer lease was not fenced")
    except Conflict:
        pass
    started = time.monotonic()
    with rt.write(credential["tenant"], wait_seconds=old["lease_seconds"] + 5) as lake:
        assert not (lake / "uncommitted-crash-marker").exists()
        (lake / "recovered-writer").write_text("new fenced owner")
    assert rt.catalog.head(credential["tenant"]).version == old["version"] + 1
    save(
        "crash-recovery",
        {
            "sql_rolled_back": True,
            "partial_evidence_not_published": True,
            "lease_fenced_before_expiry": True,
            "lease_seconds": old["lease_seconds"],
            "recovered_seconds": time.monotonic() - started,
        },
    )
    rt.catalog.engine.dispose()


def backup_prepare():
    ready()
    jobs = []
    for credential in load("credentials"):
        response = request(
            "api-a",
            "POST",
            "/api/v1/snapshots",
            credential,
            headers={"Prefer": "respond-async", "Idempotency-Key": "recovery-snapshot"},
            json={"reason": "recovery qualification"},
        )
        assert response.status_code == 202
        job = response.json()["data"]
        deadline = time.monotonic() + 120
        while True:
            response = request("api-b", "GET", job["status_url"], credential)
            assert response.status_code == 200
            state = response.json()["data"]["status"]
            if state == "succeeded":
                break
            assert state in {"queued", "running"}
            assert time.monotonic() < deadline
            time.sleep(0.5)
        receipt = request("api-b", "GET", job["status_url"] + "/result", credential)
        assert receipt.status_code == 200
        jobs.append({"status_url": job["status_url"], "receipt_sha256": receipt.json()["data"]["sha256"]})
    save("backup-jobs", jobs)


def backup_capture():
    from security_lakehouse.distributed.recovery import capture_objects

    rt, _ = runtime()
    try:
        result = capture_objects(rt, WORK / "object-backup")
        baseline = load("baseline")
        baseline["versions"] = result["heads"]
        save("baseline", baseline)
        save("backup-capture", result)
    finally:
        rt.catalog.engine.dispose()


def backup_restore():
    from security_lakehouse.distributed.objects import IntegrityError
    from security_lakehouse.distributed.recovery import restore_objects, validate_backup

    rt, _ = runtime()
    try:
        root = WORK / "object-backup"
        index = validate_backup(root, rt.catalog.config)
        # Reject corruption before uploading anything; restore the test bytes.
        sample = root / index["objects"][0]["path"]
        original = sample.read_bytes()
        try:
            sample.write_bytes(b"deliberately corrupt qualification backup")
            try:
                validate_backup(root, rt.catalog.config)
            except IntegrityError:
                pass
            else:
                raise AssertionError("corrupt backup accepted")
        finally:
            sample.write_bytes(original)
        deadline = time.monotonic() + 60
        while True:
            try:
                rt.objects.client.list_buckets()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        rt.objects.client.create_bucket(Bucket=rt.catalog.config.bucket)
        started = time.monotonic()
        restored = restore_objects(rt.objects, root)
        for tenant, version in restored["heads"].items():
            assert rt.catalog.head(tenant).version == version
        save(
            "backup-restore",
            {
                "objects": restored["objects"],
                "corrupt_backup_rejected": True,
                "object_restore_seconds": time.monotonic() - started,
            },
        )
    finally:
        rt.catalog.engine.dispose()


def backup_verify():
    from security_lakehouse.distributed.recovery import inspect_tenant

    stable("backup-recovered")
    rt, _ = runtime()
    try:
        reports = []
        credentials = load("credentials")
        jobs = load("backup-jobs")
        for credential, job in zip(credentials, jobs, strict=True):
            report = inspect_tenant(rt, credential["tenant"])
            assert report["recovery_ready"], report
            integrity = request("api-a", "GET", "/api/v1/snapshots/integrity", credential)
            assert integrity.status_code == 200 and integrity.json()["data"]["ok"]
            assert integrity.json()["data"]["length"] >= 1
            receipt = request("api-b", "GET", job["status_url"] + "/result", credential)
            assert receipt.status_code == 200
            assert receipt.json()["data"]["sha256"] == job["receipt_sha256"]
            reports.append(report)
        assert request("api-b", "GET", jobs[0]["status_url"] + "/result", credentials[1]).status_code == 404
        save(
            "backup-verify",
            {
                "tenant_isolation": True,
                "snapshot_chains_verified": len(reports),
                "operation_receipts_preserved": len(reports),
                "reports": reports,
            },
        )
    finally:
        rt.catalog.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase",
        choices=[
            "prepare",
            "enqueue",
            "verify",
            "cold-restart",
            "object-outage",
            "database-outage",
            "objects-recovered",
            "database-recovered",
            "hold-writer",
            "crash-recovery",
            "backup-prepare",
            "backup-capture",
            "backup-restore",
            "backup-verify",
        ],
    )
    phase = parser.parse_args().phase
    try:
        if phase.startswith("backup-"):
            {
                "backup-prepare": backup_prepare,
                "backup-capture": backup_capture,
                "backup-restore": backup_restore,
                "backup-verify": backup_verify,
            }[phase]()
        elif phase == "prepare":
            prepare()
        elif phase == "enqueue":
            enqueue()
        elif phase == "verify":
            verify()
        elif phase in {"cold-restart", "objects-recovered", "database-recovered"}:
            stable(phase)
        elif phase.endswith("-outage"):
            outage(phase.removesuffix("-outage"))
        elif phase == "hold-writer":
            hold_writer()
        else:
            crash_recovery()
    except Exception as exc:
        save("failure", {"phase": phase, "type": type(exc).__name__})
        raise


if __name__ == "__main__":
    main()
