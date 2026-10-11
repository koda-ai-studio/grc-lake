"""Bound input bytes and relation fan-out before building in-memory assessments.

These are admission limits, not an RSS or production-capacity guarantee.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from security_lakehouse.generations import pinned_path
from security_lakehouse.io import _parse_jsonl_line, resolve_path
from security_lakehouse.runtime_environment import runtime_env


def _positive(name: str, default: int, maximum: int) -> int:
    try:
        value = int(runtime_env().get(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def bounded_raw_events(path: str | Path) -> Iterator[dict[str, Any]]:
    budget = _positive("GRC_LAKE_EVALUATION_INPUT_BYTES", 256 * 1024**2, 4 * 1024**3)
    edge_limit = _positive("GRC_LAKE_EVALUATION_RELATIONS", 1_000_000, 10_000_000)
    target = resolve_path(pinned_path(Path(path)))
    if target.stat().st_size > budget:
        raise ValueError("evaluation input byte budget exceeded; split the scope or qualify a larger limit")
    consumed = edges = line_number = 0
    with target.open("rb") as stream:
        while line := stream.readline(min(budget - consumed + 1, 8 * 1024**2 + 1)):
            line_number += 1
            consumed += len(line)
            if consumed > budget:
                raise ValueError("evaluation input byte budget exceeded")
            if len(line) > 8 * 1024**2:
                raise ValueError("evaluation record exceeds 8 MiB; split the record")
            if not line.strip():
                continue
            row = _parse_jsonl_line(target, line_number, line.decode("utf-8"))
            edges += sum(
                len(row.get(key, [])) for key in ("controls", "safeguard_ids") if isinstance(row.get(key, []), list)
            )
            if edges > edge_limit:
                raise ValueError("evaluation relation budget exceeded; split the scope")
            yield row
