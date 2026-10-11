"""Shared evidence predicates; collection health is separate from verdict support."""

from typing import Any

from security_lakehouse.event_status import normalize_event_status
from security_lakehouse.vocabulary import EventStatus


def has_verdict(row: dict[str, Any]) -> bool:
    """Unknown outcomes remain verdict-bearing blockers; observations do not."""
    return normalize_event_status(row.get("status", "observed")) != EventStatus.OBSERVED


def evidence_available(row: dict[str, Any]) -> bool:
    """A retained internal bronze reference is valid; explicit unavailability wins."""
    return bool(row.get("evidence_ref")) and row.get("evidence_available", True) is True
