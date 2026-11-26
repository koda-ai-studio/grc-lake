"""POC source setup gates describe recorded collection, never compliance."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from security_lakehouse.models import parse_event_time


def source_sync_readiness(
    connectors: list[dict[str, Any]], *, evidence_count: int, now: datetime, synthetic: bool = False
) -> tuple[bool, str]:
    enabled = [row for row in connectors if row.get("state") == "enabled"]
    if not enabled:
        return False, "Connect, test, enable, and sync at least one source."
    blockers: Counter[str] = Counter()
    for connector in enabled:
        sync = connector.get("last_sync") or {}
        metadata = sync.get("metadata") or {}
        if not connector.get("is_implemented"):
            blockers["unavailable"] += 1
        elif sync.get("result") != "ok":
            blockers["unsuccessful"] += 1
        elif metadata.get("partial") is True or metadata.get("coverage_gaps"):
            blockers["partial"] += 1
        elif type(sync.get("evidence_count")) is not int or sync["evidence_count"] <= 0:
            blockers["empty"] += 1
        else:
            try:
                timestamp = parse_event_time(str(sync.get("occurred_at") or ""))
                minutes = int(connector.get("freshness_slo_minutes") or 60)
                current = minutes > 0 and timedelta(0) <= now - timestamp <= timedelta(minutes=minutes)
            except (TypeError, ValueError, OverflowError):
                current = False
            if not current:
                blockers["stale"] += 1
    reasons = {
        "unavailable": "source(s) have no executable collector",
        "unsuccessful": "source(s) need a successful sync",
        "partial": "source(s) have partial collection; review gaps and retry",
        "empty": "source(s) collected no evidence; verify scope and permissions",
        "stale": "source(s) have stale or invalid sync times; check the clock and sync again",
    }
    if blockers:
        return False, "; ".join(f"{count} {reasons[reason]}" for reason, count in blockers.items()) + "."
    if evidence_count <= 0:
        return False, "Collection is recorded; materialize the lake to inspect evidence."
    provenance = " Includes synthetic/demo evidence." if synthetic else ""
    return True, (
        f"{len(enabled)} enabled source(s) have recent, non-empty syncs without recorded collection gaps."
        f"{provenance} Collection is not provider qualification or a compliance verdict."
    )
