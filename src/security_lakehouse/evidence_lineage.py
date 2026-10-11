"""Exact event provenance and frozen result references, without raw payloads."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from security_lakehouse.event_identity import event_identity
from security_lakehouse.generations import generation_identity, pin_generation, verify_generation
from security_lakehouse.io import canonical_sha256, iter_jsonl


class LineageUnavailable(ValueError):
    """A sealed, internally consistent lineage could not be established."""


class EventNotFound(LookupError):
    """No exact normalized event exists in this generation."""


def _unique_event(generation: Path, identity: str) -> dict[str, Any]:
    found = None
    for row in iter_jsonl(generation / "silver/normalized_events.jsonl"):
        if row.get("event_id") == identity:
            if found is not None:
                raise LineageUnavailable("ambiguous normalized event")
            found = row
    if found is None:
        raise EventNotFound(identity)
    matches = 0
    for row in iter_jsonl(generation / "bronze/raw_events.jsonl"):
        raw = row.get("raw")
        if isinstance(raw, dict) and event_identity(raw) == identity:
            matches += 1
            if row.get("raw_sha256") != found.get("raw_sha256") or canonical_sha256(raw) != found.get("raw_sha256"):
                raise LineageUnavailable("raw and normalized evidence disagree")
    if matches != 1:
        raise LineageUnavailable("missing or ambiguous source event")
    return found


def _links(generation: Path, event: dict[str, Any]):
    # Control associations are declared by the source. They are not proof that
    # this individual event satisfied the control's operating-evidence rules.
    controls = set(event.get("control_ids") or [])
    for row in iter_jsonl(generation / "gold/control_tests.jsonl"):
        if row["control_id"] in controls:
            yield {"kind": "declared_control", "control_id": row["control_id"], "result": row["result"]}
    database = generation / "mart/security_lakehouse.sqlite"
    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA cache_size=-1024")
        connection.execute("PRAGMA temp_store=FILE")
        # Select scalar columns only; a single asset may reference many events.
        rows = connection.execute(
            "SELECT safeguard_id, asset_id, status FROM ccf_asset_results "
            "WHERE source_tenant_id = ? AND asset_id = ? "
            "AND EXISTS (SELECT 1 FROM json_each(event_ids) WHERE value = ?) "
            "AND EXISTS (SELECT 1 FROM json_each(evidence_hashes) WHERE value = ?) "
            "ORDER BY safeguard_id, asset_id, ordinal",
            (
                event.get("source_account_id", event.get("tenant_id", "")),
                event["asset_id"],
                event["event_id"],
                event["raw_sha256"],
            ),
        )
        for safeguard, asset, status in rows:
            yield {"kind": "safeguard_result", "safeguard_id": safeguard, "asset_id": asset, "result": status}


def read_lineage(
    lake: Path, identity: str, *, limit: int = 25, offset: int = 0, generation_id: str | None = None
) -> tuple[dict[str, Any], int]:
    """Stream evidence and result references while holding one generation lease.

    Memory is bounded by one stored record and one response page. Hash checking
    and source lookup still read the generation; this is an audit drill-down,
    not an indexed constant-time lookup or an authenticity attestation.
    """
    if not identity or len(identity) > 1024 or not 1 <= limit <= 100 or offset < 0:
        raise ValueError("invalid lineage request")
    try:
        with pin_generation(lake) as generation:
            if generation is None:
                raise LineageUnavailable("sealed assessment required")
            if generation_id is not None and generation.name != generation_id:
                raise LineageUnavailable("assessment generation changed")
            verify_generation(generation)
            event = _unique_event(generation, identity)
            page = []
            count = 0
            for link in _links(generation, event):
                if offset <= count < offset + limit:
                    page.append(link)
                count += 1
            return {
                "event_id": identity,
                "raw_sha256": event["raw_sha256"],
                "source": {
                    "connector_id": event.get("connector_id"),
                    "source_event_id": event.get("source_event_id", identity),
                    "source_account_id": event.get("source_account_id", event.get("tenant_id")),
                    "source": event["source"],
                    "event_time": event["event_time"],
                },
                "asset_id": event["asset_id"],
                "status": event["status"],
                "integrity": {"verified": True, "external_authenticity": "not_established"},
                "generation": generation_identity(lake),
                "links": page,
            }, count
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        raise LineageUnavailable("evidence lineage is unavailable") from exc
