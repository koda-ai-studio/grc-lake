"""Versioned, read-only entity identities and explicit cross-source alias claims.

Source observations remain separate. A caller assertion is never an inferred
identity match, an authenticated approval, or a change to compliance truth.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from security_lakehouse.generations import generation_identity, generation_reader
from security_lakehouse.io import canonical_sha256, iter_jsonl
from security_lakehouse.timeutil import utc_iso_z

_SOURCE_FIELDS = ("source", "source_account_id", "asset_type", "asset_id")
_ASSERTION_FIELDS = (*_SOURCE_FIELDS, "evidence_sha256", "asserted_by", "asserted_at", "reason")
_ENTITY_TYPES = {"person", "account", "device", "resource", "repository", "service", "organization", "unknown"}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"entity registry requires nonempty {field}")
    return value


def _object(value: Any, fields: Iterable[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("entity registry object has missing or unknown fields")
    return value


def _time(value: Any, field: str) -> str:
    parsed = datetime.fromisoformat(_text(value, field).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"entity registry requires timezone in {field}")
    return utc_iso_z(parsed)


def _digest(value: Any) -> str:
    text = _text(value, "evidence hash")
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ValueError("entity registry requires a SHA-256 hex digest")
    return text


def _source(row: dict[str, Any]) -> dict[str, str]:
    return {key: _text(row.get(key), key) for key in _SOURCE_FIELDS}


def _id(kind: str, tenant: str, value: Any) -> str:
    return f"{kind}:v1:" + canonical_sha256([tenant, value])


def build_entity_registry(
    events: Iterable[dict[str, Any]],
    *,
    platform_tenant_id: str,
    bindings: dict[str, Any] | None = None,
    max_observations: int = 100_000,
) -> dict[str, Any]:
    """Project exact native identity and validated caller-supplied alias claims.

    ``platform_tenant_id`` is supplied by a trusted local caller, never inferred
    from vendor account IDs. This function does not authorize access to evidence.
    The row cap counts deliveries, including duplicates, to bound input work.
    """
    tenant = _text(platform_tenant_id, "platform_tenant_id")
    if type(max_observations) is not int or not 1 <= max_observations <= 100_000:
        raise ValueError("invalid observation limit (1–100000)")
    sources: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, dict[str, Any]]] = {}
    for count, row in enumerate(events, 1):
        if count > max_observations:
            raise ValueError("entity registry observation limit exceeded")
        source = _source(row)
        if "tenant_id" in row and row["tenant_id"] != source["source_account_id"]:
            raise ValueError("source account identity aliases disagree")
        sid = _id("source-entity", tenant, source)
        observed = _time(row.get("event_time"), "event_time")
        raw_hash = _digest(row.get("raw_sha256"))
        evidence_hash = canonical_sha256(row)
        if sid not in sources:
            sources[sid] = {"id": sid, **source, "first_observed_at": observed, "last_observed_at": observed}
            observations[sid] = {}
        entity = sources[sid]
        entity["first_observed_at"] = min(entity["first_observed_at"], observed, key=datetime.fromisoformat)
        entity["last_observed_at"] = max(entity["last_observed_at"], observed, key=datetime.fromisoformat)
        observations[sid][evidence_hash] = {
            "evidence_sha256": evidence_hash,
            "raw_sha256": raw_hash,
            "event_id": _text(row.get("event_id"), "event_id"),
            "observed_at": observed,
        }
    canonical: dict[str, dict[str, Any]] = {}
    aliases: dict[str, dict[str, Any]] = {}
    if bindings is not None:
        _object(bindings, ("schema_version", "platform_tenant_id", "entities"))
        if bindings["schema_version"] != "1.0" or bindings["platform_tenant_id"] != tenant:
            raise ValueError("entity binding version or platform tenant mismatch")
        if not isinstance(bindings["entities"], list):
            raise ValueError("entity bindings must contain an entities array")
        binding_count = 0
        for item in bindings["entities"]:
            _object(item, ("key", "entity_type", "bindings"))
            key = _text(item["key"], "canonical entity key")
            kind = _text(item["entity_type"], "entity_type")
            if kind not in _ENTITY_TYPES:
                raise ValueError("unknown canonical entity type")
            cid = _id("canonical-entity", tenant, key)
            if cid in canonical:
                raise ValueError("duplicate canonical entity key")
            if not isinstance(item["bindings"], list) or not item["bindings"]:
                raise ValueError("canonical entities require at least one binding")
            canonical[cid] = {"id": cid, "key": key, "entity_type": kind, "basis": "caller_asserted"}
            for assertion in item["bindings"]:
                binding_count += 1
                if binding_count > max_observations:
                    raise ValueError("entity registry binding limit exceeded")
                _object(assertion, _ASSERTION_FIELDS)
                source = _source(assertion)
                sid = _id("source-entity", tenant, source)
                digest = _digest(assertion["evidence_sha256"])
                if sid not in sources or digest not in observations[sid]:
                    raise ValueError("entity binding evidence does not match the exact source entity")
                _text(assertion["asserted_by"], "asserted_by")
                _text(assertion["reason"], "reason")
                instant = _time(assertion["asserted_at"], "asserted_at")
                claim = {**assertion, "asserted_at": instant}
                alias = {
                    "source_entity_id": sid,
                    "canonical_entity_id": cid,
                    "basis": "caller_asserted",
                    "assertion": claim,
                }
                alias["id"] = _id("entity-alias", tenant, alias)
                if sid in aliases and aliases[sid] != alias:
                    raise ValueError("conflicting bindings for one source entity")
                aliases[sid] = alias
    for sid, entity in sources.items():
        entity["observations"] = [observations[sid][key] for key in sorted(observations[sid])]
    result = {
        "schema_version": "1.0",
        "identity_version": "entity-identity-v1",
        "platform_tenant_id": tenant,
        "source_entities": [sources[key] for key in sorted(sources)],
        "canonical_entities": [canonical[key] for key in sorted(canonical)],
        "aliases": [aliases[key] for key in sorted(aliases)],
    }
    return {**result, "content_sha256": canonical_sha256(result)}


@generation_reader
def entity_registry(lake: Path, *, platform_tenant_id: str, bindings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read one pinned generation; never mutate lake artifacts or workflow state."""
    lake = Path(lake)
    result = build_entity_registry(
        iter_jsonl(lake / "silver/normalized_events.jsonl", base_dir=lake),
        platform_tenant_id=platform_tenant_id,
        bindings=bindings,
    )
    return {**result, "generation": generation_identity(lake)}
