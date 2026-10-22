"""Append-only, local operational revisions of caller-asserted entity bindings."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from security_lakehouse import strict_json
from security_lakehouse.entity_registry import _digest, _object, _text, _time, build_entity_registry, entity_registry
from security_lakehouse.generations import assert_mutable, generation_identity, generation_reader
from security_lakehouse.io import canonical_sha256, iter_jsonl, read_jsonl
from security_lakehouse.ledger import append_chained_jsonl_batch, canonical_record_hash, chain_lock
from security_lakehouse.timeutil import utc_now_iso_z

MAX_HISTORY_BYTES = 32 * 1024 * 1024
MAX_REVISIONS = 1000
MAX_BINDINGS = 1000
_RECORD_FIELDS = (
    "schema_version",
    "identity_version",
    "platform_tenant_id",
    "revision",
    "request_id",
    "request_sha256",
    "actor",
    "reason",
    "recorded_at",
    "bindings",
    "evidence",
    "generation",
    "changes",
    "prev_hash",
    "record_hash",
)


def _path(lake: Path) -> Path:
    root = Path(lake).resolve()
    if not root.is_dir():
        raise FileNotFoundError("entity history requires an existing lake")
    path = root / "entities/bindings.jsonl"
    if any(p.is_symlink() for p in (path.parent, path, path.with_name(path.name + ".lock"))):
        raise ValueError("entity history symlinks are not allowed")
    assert_mutable(path)
    return path


def _check_size(path: Path, extra: int = 0) -> None:
    if (path.stat().st_size if path.exists() else 0) + extra > MAX_HISTORY_BYTES:
        raise ValueError("entity history byte limit exceeded; retain history and use a larger-storage implementation")


def _request_hash(tenant: str, bindings: Any, actor: str, reason: str, expected: int) -> str:
    return canonical_sha256([tenant, bindings, actor, reason, expected])


def _changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[str]]:
    old = {a["source_entity_id"]: a["id"] for a in before.get("aliases", [])}
    new = {a["source_entity_id"]: a["id"] for a in after["aliases"]}
    return {
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
        "changed": sorted(key for key in old.keys() & new.keys() if old[key] != new[key]),
    }


def _check_types(types: dict[str, str], registry: dict[str, Any]) -> None:
    for entity in registry["canonical_entities"]:
        key, kind = entity["key"], entity["entity_type"]
        if key in types and types[key] != kind:
            raise ValueError("canonical entity key cannot change type across revisions")
        types[key] = kind


def _verify(rows: list[dict[str, Any]], tenant: str) -> tuple[dict[str, Any], dict[str, str]]:
    if len(rows) > MAX_REVISIONS:
        raise ValueError("entity history revision limit exceeded")
    previous = None
    registry: dict[str, Any] = {"aliases": []}
    types: dict[str, str] = {}
    requests: set[str] = set()
    for index, row in enumerate(rows, 1):
        _object(row, _RECORD_FIELDS)
        if (
            row["schema_version"] != "1.0"
            or row["identity_version"] != "entity-identity-v1"
            or row["platform_tenant_id"] != tenant
        ):
            raise ValueError("entity history version or platform tenant mismatch")
        if type(row["revision"]) is not int or row["revision"] != index:
            raise ValueError("entity history revision sequence is invalid")
        if row["prev_hash"] != previous or row["record_hash"] != canonical_record_hash(row):
            raise ValueError("entity history hash chain is invalid")
        request_id = _text(row["request_id"], "request_id")
        if request_id in requests:
            raise ValueError("duplicate entity history request")
        requests.add(request_id)
        _time(row["recorded_at"], "recorded_at")
        actor, reason = _text(row["actor"], "actor"), _text(row["reason"], "reason")
        if row["request_sha256"] != _request_hash(tenant, row["bindings"], actor, reason, index - 1):
            raise ValueError("entity history request digest is invalid")
        if not isinstance(row["evidence"], list) or len(row["evidence"]) > MAX_BINDINGS:
            raise ValueError("entity history evidence limit or shape is invalid")
        if not all(isinstance(event, dict) for event in row["evidence"]):
            raise ValueError("entity history evidence rows must be objects")
        generation = row["generation"]
        if generation is not None:
            _object(generation, ("generation_id", "manifest_sha256"))
            _text(generation["generation_id"], "generation_id")
            _digest(generation["manifest_sha256"])
        current = build_entity_registry(row["evidence"], platform_tenant_id=tenant, bindings=row["bindings"])
        referenced = {alias["assertion"]["evidence_sha256"] for alias in current["aliases"]}
        if (
            len(row["evidence"]) != len(referenced)
            or {canonical_sha256(event) for event in row["evidence"]} != referenced
        ):
            raise ValueError("entity history must retain exactly the referenced evidence")
        if len(current["aliases"]) > MAX_BINDINGS or row["changes"] != _changes(registry, current):
            raise ValueError("entity history change summary is invalid")
        _check_types(types, current)
        registry, previous = current, row["record_hash"]
    return registry, types


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"bindings", "evidence"}}


def _read(lake: Path, tenant: str) -> list[dict[str, Any]]:
    path = _path(lake)
    with chain_lock(path, shared=True):
        _check_size(path)
        rows = read_jsonl(path, missing_ok=True)
        _verify(rows, tenant)
        return rows


@generation_reader
def record_bindings(
    lake: Path,
    *,
    platform_tenant_id: str,
    bindings: dict[str, Any],
    actor: str,
    reason: str,
    expected_revision: int,
    request_id: str,
) -> dict[str, Any]:
    """Replace the entire binding set under a revision check; omissions revoke aliases.

    The actor is caller supplied, not authenticated approval. Store only the
    normalized observations referenced by bindings, not an entire inventory.
    """
    tenant = _text(platform_tenant_id, "platform_tenant_id")
    actor, reason = _text(actor, "actor"), _text(reason, "reason")
    request_id = _text(request_id, "request_id")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("expected revision must be a nonnegative integer")
    bindings = deepcopy(bindings)
    strict_json.dumps(bindings)
    request_hash = _request_hash(tenant, bindings, actor, reason, expected_revision)
    path = _path(lake)
    _check_size(path)
    replay: list[dict[str, Any]] = []

    def build(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _check_size(path)
        before, types = _verify(rows, tenant)
        for row in rows:
            if row["request_id"] == request_id:
                if row["request_sha256"] != request_hash:
                    raise ValueError("request ID was already used with a different payload")
                replay.append(row)
                return []
        if len(rows) != expected_revision:
            raise ValueError("entity binding revision changed; refresh history before recording")
        if len(rows) >= MAX_REVISIONS:
            raise ValueError("entity history revision limit exceeded")
        # Validate even an empty replacement without requiring source files: an
        # operator must be able to revoke bindings after source data is removed.
        _object(bindings, ("schema_version", "platform_tenant_id", "entities"))
        evidence: list[dict[str, Any]] = []
        if bindings["entities"]:
            # Validation uses the full current generation; retain only exact
            # referenced rows after it passes, so no unbound observations persist.
            current = entity_registry(lake, platform_tenant_id=tenant, bindings=bindings)
            wanted = {alias["assertion"]["evidence_sha256"] for alias in current["aliases"]}
            if len(current["aliases"]) > MAX_BINDINGS:
                raise ValueError("entity history binding limit exceeded")
            unique = {}
            for event in iter_jsonl(Path(lake) / "silver/normalized_events.jsonl", base_dir=lake):
                digest = canonical_sha256(event)
                if digest in wanted:
                    unique[digest] = event
            evidence = [unique[key] for key in sorted(unique)]
        registry = build_entity_registry(evidence, platform_tenant_id=tenant, bindings=bindings)
        _check_types(types, registry)
        record = {
            "schema_version": "1.0",
            "identity_version": "entity-identity-v1",
            "platform_tenant_id": tenant,
            "revision": len(rows) + 1,
            "request_id": request_id,
            "request_sha256": request_hash,
            "actor": actor,
            "reason": reason,
            "recorded_at": utc_now_iso_z(),
            "bindings": bindings,
            "evidence": evidence,
            "generation": generation_identity(lake),
            "changes": _changes(before, registry),
        }
        # Reserve exact linkage overhead before the common ledger appends.
        candidate = {**record, "prev_hash": rows[-1]["record_hash"] if rows else None}
        candidate["record_hash"] = canonical_record_hash(candidate)
        _check_size(path, len((strict_json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n").encode()))
        return [record]

    written = append_chained_jsonl_batch(path, build)
    return _summary((written or replay)[0])


def binding_history(lake: Path, *, platform_tenant_id: str) -> dict[str, Any]:
    tenant = _text(platform_tenant_id, "platform_tenant_id")
    rows = _read(lake, tenant)
    return {
        "schema_version": "1.0",
        "platform_tenant_id": tenant,
        "tip_hash": rows[-1]["record_hash"] if rows else None,
        "revisions": [_summary(row) for row in rows],
    }


def stored_entity_registry(lake: Path, *, platform_tenant_id: str, revision: int | None = None) -> dict[str, Any]:
    """Current reads revalidate live evidence; numbered reads retain recording-time evidence."""
    tenant = _text(platform_tenant_id, "platform_tenant_id")
    rows = _read(lake, tenant)
    if not rows:
        raise ValueError("no recorded entity bindings")
    if revision is not None and (type(revision) is not int or not 1 <= revision <= len(rows)):
        raise ValueError("unknown entity binding revision")
    row = rows[-1] if revision is None else rows[revision - 1]
    if revision is None:
        registry = entity_registry(lake, platform_tenant_id=tenant, bindings=row["bindings"])
    else:
        registry = build_entity_registry(row["evidence"], platform_tenant_id=tenant, bindings=row["bindings"])
        registry["generation"] = row["generation"]
    return {
        **registry,
        "binding_history": {
            "revision": row["revision"],
            "record_hash": row["record_hash"],
            "recorded_at": row["recorded_at"],
            "mode": "current_evidence" if revision is None else "recorded_binding_evidence",
        },
    }


def register_history(actions: Any) -> None:
    from security_lakehouse.io import read_json

    def record(args: Any) -> int:
        result = record_bindings(
            Path(args.lake),
            platform_tenant_id=args.tenant_id,
            bindings=read_json(args.bindings),
            actor=args.actor,
            reason=args.reason,
            expected_revision=args.expected_revision,
            request_id=args.request_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    def history(args: Any) -> int:
        print(json.dumps(binding_history(Path(args.lake), platform_tenant_id=args.tenant_id), indent=2, sort_keys=True))
        return 0

    for name, handler in (("record", record), ("history", history)):
        command = actions.add_parser(
            name, help="record a complete binding revision" if name == "record" else "verify and list binding revisions"
        )
        command.add_argument("--lake", required=True)
        command.add_argument("--tenant-id", required=True)
        command.set_defaults(func=handler)
        if name == "record":
            command.add_argument(
                "--bindings", required=True, help="complete replacement manifest; omitted aliases are revoked"
            )
            command.add_argument("--actor", required=True, help="caller identity; not authenticated approval")
            command.add_argument("--reason", required=True)
            command.add_argument("--expected-revision", required=True, type=int, help="0 for the first revision")
            command.add_argument("--request-id", required=True, help="unique retry key for this exact request")
