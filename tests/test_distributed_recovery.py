"""Read-only diagnostics and quiesced backups never invent a recovered checkpoint."""

import pytest

from security_lakehouse.distributed.objects import ObjectStore
from security_lakehouse.distributed.workspace import Runtime
from test_distributed_objects import MemoryObjects


def test_integrity_report_checks_storage_not_cached_reads(catalog, tmp_path):
    from security_lakehouse.distributed.recovery import inspect_tenant

    memory = MemoryObjects()
    runtime = Runtime(catalog, ObjectStore(catalog.config, client=memory), tmp_path)
    with runtime.write("tenant-a") as lake:
        (lake / "proof").write_text("original")
    with runtime.read("tenant-a"):
        pass
    before = catalog.head("tenant-a")
    report = inspect_tenant(runtime, "tenant-a")
    assert report["ok"] and report["revision"] == before.version
    key = runtime.objects.key("tenant-a", before.manifest["files"]["proof"]["sha256"])
    memory.data[key] = b"corrupt"
    report = inspect_tenant(runtime, "tenant-a")
    assert not report["ok"]
    assert report["issues"][0]["code"] == "integrity_failure"
    assert catalog.head("tenant-a") == before


def test_inspection_budget_is_incomplete_not_healthy(catalog, tmp_path):
    from security_lakehouse.distributed.recovery import inspect_tenant

    runtime = Runtime(catalog, ObjectStore(catalog.config, client=MemoryObjects()), tmp_path)
    with runtime.write("tenant-a") as lake:
        (lake / "one").write_text("one")
        (lake / "two").write_text("two")
    report = inspect_tenant(runtime, "tenant-a", max_objects=1)
    assert not report["ok"] and not report["complete"]


def test_corrupt_download_still_consumes_inspection_byte_budget(catalog, tmp_path):
    from security_lakehouse.distributed.recovery import inspect_tenant

    memory = MemoryObjects()
    runtime = Runtime(catalog, ObjectStore(catalog.config, client=memory), tmp_path)
    with runtime.write("tenant-a") as lake:
        (lake / "one").write_text("one")
        (lake / "two").write_text("two")
    head = catalog.head("tenant-a")
    first = next(iter(head.manifest["files"].values()))
    memory.data[runtime.objects.key("tenant-a", first["sha256"])] = b"bad"
    report = inspect_tenant(runtime, "tenant-a", max_bytes=3)
    assert report["checked_objects"] == 1
    assert report["verified_bytes"] == 0
    assert not report["complete"]
    assert [issue["code"] for issue in report["issues"]] == ["integrity_failure", "inspection_limit"]


def test_manifest_with_future_schema_is_rejected_before_download(tmp_path):
    from security_lakehouse.distributed.config import ClusterConfig

    store = ObjectStore(ClusterConfig("test", "test"), client=MemoryObjects())
    with pytest.raises(ValueError, match="schema"):
        store.restore("a", {"schema": 999, "files": {}}, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_backup_retains_historical_objects_and_rejects_corruption(catalog, tmp_path):
    from security_lakehouse.distributed.recovery import capture_objects, validate_backup

    runtime = Runtime(catalog, ObjectStore(catalog.config, client=MemoryObjects()), tmp_path / "scratch")
    with runtime.write("tenant-a") as lake:
        (lake / "proof").write_text("original")
    with runtime.write("tenant-a") as lake:
        (lake / "proof").write_text("replacement")
    backup = tmp_path / "backup"
    report = capture_objects(runtime, backup)
    assert report["objects"] == 2
    manifest = validate_backup(backup, catalog.config)
    first = backup / manifest["objects"][0]["path"]
    first.write_bytes(b"corrupted backup")
    with pytest.raises(ValueError, match="integrity"):
        validate_backup(backup, catalog.config)


def test_lost_lease_stops_upload_before_any_object_write(catalog, tmp_path):
    from security_lakehouse.distributed.catalog import Conflict
    from security_lakehouse.distributed.context import WorkspaceBinding, binding

    memory = MemoryObjects()
    store = ObjectStore(catalog.config, client=memory)
    (tmp_path / "file").write_text("bytes")

    def lost():
        raise Conflict("writer lease lost")

    token = binding.set(WorkspaceBinding("a", tmp_path, check_active=lost))
    try:
        with pytest.raises(Conflict):
            store.put("a", tmp_path / "file")
    finally:
        binding.reset(token)
    assert not memory.data


def test_restore_into_fresh_postgres_and_object_store_preserves_history(catalog, tmp_path):
    import shutil
    import subprocess
    import uuid

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from security_lakehouse.distributed.catalog import Catalog
    from security_lakehouse.distributed.recovery import capture_objects, inspect_tenant, restore_objects
    from security_lakehouse.pipeline import run_pipeline

    if not shutil.which("pg_dump") or not shutil.which("psql"):
        pytest.skip("requires PostgreSQL client tools")
    memory = MemoryObjects()
    original = Runtime(catalog, ObjectStore(catalog.config, client=memory), tmp_path / "source")
    for tenant in ("tenant-a", "tenant-b"):
        with original.write(tenant) as lake:
            run_pipeline("data/raw/security_events.jsonl", lake, tenant_id=tenant)
    backup = tmp_path / "backup"
    capture_objects(original, backup)
    dump = tmp_path / "database.sql"
    source_url = catalog.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with dump.open("wb") as stream:
        subprocess.run(
            ["pg_dump", "--no-owner", "--no-privileges", source_url],
            stdout=stream,
            capture_output=False,
            check=True,
            timeout=60,
        )
    name = "grc_recovery_" + uuid.uuid4().hex
    admin = create_engine(catalog.engine.url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    target_url = make_url(source_url).set(database=name)
    engine = None
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        with dump.open("rb") as stream:
            subprocess.run(
                ["psql", "-v", "ON_ERROR_STOP=1", target_url.render_as_string(hide_password=False)],
                stdin=stream,
                capture_output=True,
                check=True,
                timeout=60,
            )
        engine = create_engine(target_url.set(drivername="postgresql+psycopg"))
        restored_catalog = Catalog(engine, catalog.config)
        fresh_store = ObjectStore(catalog.config, client=MemoryObjects())
        # Original storage is deliberately unavailable to the restored runtime.
        memory.data.clear()
        restore_objects(fresh_store, backup)
        restored = Runtime(restored_catalog, fresh_store, tmp_path / "restored")
        for tenant in ("tenant-a", "tenant-b"):
            assert restored_catalog.head(tenant) == catalog.head(tenant)
            assert inspect_tenant(restored, tenant)["recovery_ready"]
            with restored.read(tenant) as lake:
                from security_lakehouse.io import read_json

                assert read_json(lake / "manifest.json")["tenant_id"] == tenant
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_storage_failures_have_stable_codes_without_exception_details():
    import errno

    from botocore.exceptions import ClientError

    from security_lakehouse.distributed.recovery import failure_code

    assert failure_code(OSError(errno.ENOSPC, "private disk")) == "resource_exhausted"
    assert failure_code(ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")) == "missing_object"
    assert failure_code(ConnectionError("private endpoint")) == "storage_unavailable"


def test_uncertain_worker_failure_has_result_reconciliation_reference():
    from security_lakehouse.operation_receipts import failure_response

    code, response = failure_response("operation-id", ConnectionError("secret endpoint"))
    assert code == 503
    assert response["errors"][0]["code"] == "storage_unavailable"
    assert response["meta"]["publication"] == "unknown"
    assert response["meta"]["result_url"] == "/api/v1/operations/operation-id/result"
    assert "secret" not in str(response)


def test_inspection_reports_malformed_reference_without_crashing(catalog, tmp_path):
    from security_lakehouse.distributed.recovery import inspect_tenant

    catalog.publish("a", expected=0, manifest={"schema": 1, "tenant_id": "a", "files": {"proof": None}})
    runtime = Runtime(catalog, ObjectStore(catalog.config, client=MemoryObjects()), tmp_path)
    report = inspect_tenant(runtime, "a")
    assert not report["ok"]
    assert report["issues"][0]["code"] == "integrity_failure"
