"""Idempotent upsert keyed on a natural key.

**Idempotent** means: re-running the same sync produces the same silver state,
never duplicates. Pulls overlap (watermarks are inclusive, retries re-deliver),
so the merge must collapse repeats deterministically. With a ``recency`` key the
newest row per natural key wins (last-writer-wins on a load/updated timestamp);
without one the first occurrence is kept. Input order is otherwise preserved.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

R = TypeVar("R")


def dedupe_by_key(
    rows: Iterable[R],
    *,
    key: Callable[[R], Any],
    recency: Callable[[R], Any] | None = None,
) -> list[R]:
    """Collapse ``rows`` to one entry per ``key`` (idempotent).

    With ``recency`` the row with the highest recency value wins; ties and the
    no-recency case keep the first-seen row. Re-running over a superset of the
    same rows yields the same result — no duplicates.
    """
    chosen: dict[Any, R] = {}
    for row in rows:
        k = key(row)
        existing = chosen.get(k)
        if existing is None or recency is not None and recency(row) > recency(existing):
            chosen[k] = row
    return list(chosen.values())
