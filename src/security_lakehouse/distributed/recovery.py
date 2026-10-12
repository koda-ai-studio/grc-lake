"""Read-only storage inspection and bounded, quiesced qualification backups.

Inspection bypasses replica caches and never changes a catalog head. Backup
capture requires all application writers to be stopped by the operator/driver.
"""

from __future__ import annotations

import errno
import json
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from security_lakehouse.db.models import DistributedRevision, DistributedTenantHead, OperationJob
from security_lakehouse.distributed.config import identifier
from security_lakehouse.distributed.objects import IntegrityError
from security_lakehouse.io import canonical_sha256, file_sha256, read_json, resolve_path, write_json


def failure_code(exc: Exception) -> str:
    if isinstance(exc, OSError) and exc.errno in {errno.ENOSPC, errno.EDQUOT}:
        return "resource_exhausted"
    if isinstance(exc, IntegrityError):
        return "integrity_failure"
    if getattr(exc, "response", {}).get("Error", {}).get("Code") in {"NoSuchKey", "NoSuchBucket", "404"}:
        return "missing_object"
    return "storage_unavailable"


def storage_identity(config) -> str:
    return canonical_sha256(
        {name: getattr(config, name) for name in ("cluster_id", "bucket", "endpoint", "region", "shards")}
    )


def inspect_tenant(
    runtime, tenant_id: str, *, max_objects: int = 10000, max_bytes: int = 1024**3, max_seconds: float = 120
) -> dict:
    identifier(tenant_id)
    if type(max_objects) is not int or not 1 <= max_objects <= 100000:
        raise ValueError("max_objects must be between 1 and 100000")
    import math

    if type(max_bytes) is not int or max_bytes < 1 or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("inspection budgets must be positive and finite")
    deadline = time.monotonic() + max_seconds
    downloaded = 0
    reserved_bytes = 0
    verified = set()
    head = runtime.catalog.head(tenant_id)
    files = head.manifest.get("files", {})
    report: dict[str, Any] = {
        "schema_version": "grc.recovery_report.v1",
        "tenant_id": tenant_id,
        "revision": head.version,
        "manifest_sha256": canonical_sha256(head.manifest),
        "ok": False,
        "recovery_ready": False,
        "complete": False,
        "checked_objects": 0,
        "issue_count": 0,
        "issues": [],
        "unresolved_operations": [],
    }

    def issue(code, path=None):
        report["issue_count"] += 1
        if len(report["issues"]) < 100:
            report["issues"].append({"code": code, "path": path})

    if head.manifest.get("schema", 1) != 1 or not isinstance(files, dict):
        issue("unsupported_schema")
        return report
    if head.manifest.get("tenant_id", tenant_id) != tenant_id:
        issue("tenant_mismatch")
        return report
    if head.version == 0:
        issue("no_committed_revision")
        return report
    with tempfile.TemporaryDirectory(prefix="inspect-", dir=runtime.scratch) as folder:
        target = Path(folder) / "object"
        for index, (path, entry) in enumerate(files.items()):
            if index >= max_objects:
                issue("inspection_limit")
                break
            if not isinstance(entry, dict) or type(entry.get("size")) is not int or entry["size"] < 0:
                issue("integrity_failure", path)
                report["checked_objects"] += 1
                continue
            if time.monotonic() >= deadline or reserved_bytes + entry["size"] > max_bytes:
                issue("inspection_limit")
                break
            try:
                from security_lakehouse.distributed.objects import _relative

                _relative(path)
                if shutil.disk_usage(runtime.scratch).free < entry.get("size", 0) + 256 * 1024**2:
                    raise OSError(errno.ENOSPC, "insufficient inspection scratch space")
                # Failed integrity verification may still download all bytes.
                # Reserve before I/O so repeated corruption cannot evade the cap.
                reserved_bytes += entry["size"]
                runtime.objects.get(tenant_id, entry, target)
                downloaded += entry["size"]
                verified.add(path)
            except Exception as exc:  # noqa: BLE001 - report each failure without disclosing provider exceptions
                issue(failure_code(exc), path)
            finally:
                target.unlink(missing_ok=True)
            report["checked_objects"] += 1
    report["complete"] = report["checked_objects"] == len(files)
    with runtime.catalog.engine.connect() as conn:
        rows = conn.execute(
            select(OperationJob.id, OperationJob.status)
            .where(
                OperationJob.root_key == runtime.catalog.config.root_key,
                OperationJob.tenant_id == tenant_id,
                OperationJob.status.in_(["running", "cancelling", "interrupted"]),
            )
            .order_by(OperationJob.created_at, OperationJob.id)
            .limit(101)
        ).all()
    report["unresolved_operations"] = [
        {
            "id": row.id,
            "status": row.status,
            "result_receipt": "verified"
            if f"operations/results/{row.id}.json" in verified
            else "unverified"
            if f"operations/results/{row.id}.json" in files
            else "absent",
        }
        for row in rows[:100]
    ]
    report["verified_bytes"] = downloaded
    report["reserved_download_bytes"] = reserved_bytes
    report["operations_truncated"] = len(rows) > 100
    report["ok"] = report["complete"] and report["issue_count"] == 0
    report["recovery_ready"] = report["ok"] and not rows
    return report


def capture_objects(runtime, output: Path, *, max_objects: int = 10000) -> dict:
    """Capture every object referenced by retained revisions; caller quiesces writes."""
    if type(max_objects) is not int or not 1 <= max_objects <= 100000:
        raise ValueError("invalid backup object budget")
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    config = runtime.catalog.config
    records = []
    seen: set[tuple[str, str]] = set()
    with runtime.catalog.engine.connect() as conn:
        heads = list(
            conn.execute(
                select(
                    DistributedTenantHead.tenant_id, DistributedTenantHead.version, DistributedTenantHead.manifest_json
                ).where(DistributedTenantHead.cluster_id == config.cluster_id)
            )
        )
        baseline = {row.tenant_id: row.version for row in heads}
        revisions = conn.execute(
            select(DistributedRevision.tenant_id, DistributedRevision.manifest_json)
            .where(DistributedRevision.cluster_id == config.cluster_id)
            .execution_options(yield_per=100)
        )
        from itertools import chain

        for row in chain(heads, revisions):
            manifest = json.loads(row.manifest_json)
            if manifest.get("schema", 1) != 1 or manifest.get("tenant_id", row.tenant_id) != row.tenant_id:
                raise IntegrityError("unsupported backup manifest schema or tenant")
            for entry in manifest.get("files", {}).values():
                identity = (row.tenant_id, entry["sha256"])
                if identity in seen:
                    continue
                if len(seen) >= max_objects:
                    raise ValueError("backup object budget exceeded")
                seen.add(identity)
                relative = f"objects/{identifier(row.tenant_id)}/{entry['sha256']}"
                target = resolve_path(output / relative, base_dir=output)
                if shutil.disk_usage(output).free < entry["size"] + 256 * 1024**2:
                    raise OSError(errno.ENOSPC, "insufficient backup space")
                runtime.objects.get(row.tenant_id, entry, target)
                records.append({"tenant_id": row.tenant_id, "path": relative, **entry})
    if any(runtime.catalog.head(tenant).version != revision for tenant, revision in baseline.items()):
        raise ValueError("catalog changed during backup; quiesce all writers")
    content = {
        "schema_version": "grc.object_backup.v1",
        "storage_identity": storage_identity(config),
        "heads": baseline,
        "objects": records,
    }
    if len(json.dumps(content).encode()) > 32 * 1024**2:
        raise ValueError("backup index exceeds 32 MiB")
    write_json(output / "index.json", {**content, "sha256": canonical_sha256(content)})
    return {"objects": len(records), "tenants": len(baseline), "heads": baseline}


def validate_backup(root: Path, config) -> dict:
    index = resolve_path(root / "index.json", base_dir=root)
    if index.stat().st_size > 32 * 1024**2:
        raise IntegrityError("backup index exceeds limit")
    manifest = read_json(index)
    if not isinstance(manifest, dict):
        raise IntegrityError("invalid backup index")
    content = {k: v for k, v in manifest.items() if k != "sha256"}
    if (
        manifest.get("schema_version") != "grc.object_backup.v1"
        or manifest.get("storage_identity") != storage_identity(config)
        or manifest.get("sha256") != canonical_sha256(content)
        or not isinstance(manifest.get("heads"), dict)
        or not isinstance(manifest.get("objects"), list)
        or len(manifest["objects"]) > 100000
    ):
        raise IntegrityError("backup integrity or storage identity mismatch")
    seen = set()
    for entry in manifest["objects"]:
        if not isinstance(entry, dict) or set(entry) != {"tenant_id", "path", "sha256", "size"}:
            raise IntegrityError("invalid backup object entry")
        tenant = identifier(entry["tenant_id"])

        if (
            not isinstance(entry["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
            or entry["path"] != f"objects/{tenant}/{entry['sha256']}"
            or type(entry["size"]) is not int
            or not 0 <= entry["size"] <= config.workspace_limit
            or tenant not in manifest["heads"]
            or entry["path"] in seen
        ):
            raise IntegrityError("invalid backup object identity or limit")
        seen.add(entry["path"])
        path = resolve_path(root / entry["path"], base_dir=root)
        if not path.is_file() or path.stat().st_size != entry["size"] or file_sha256(path) != entry["sha256"]:
            raise IntegrityError("backup object integrity failure")
    return manifest


def restore_objects(store, root: Path) -> dict:
    """Qualification helper: verify the entire backup before conditional uploads."""
    manifest = validate_backup(root, store.config)
    for entry in manifest["objects"]:
        restored = store.put(entry["tenant_id"], resolve_path(root / entry["path"], base_dir=root))
        if restored != {"sha256": entry["sha256"], "size": entry["size"]}:
            raise IntegrityError("restored object differs from backup")
    return {"objects": len(manifest["objects"]), "heads": manifest["heads"]}
