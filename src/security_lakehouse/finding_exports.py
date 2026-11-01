"""Portable finding exports: the ``grc-lake.findings.v1`` CSV/JSONL contract.

One shared projection turns the open violations of a posture (the findings) into
flat, stable rows for SIEM and ticketing round trips. The API, CLI, MCP tool and
SDK all render through this module so the columns never drift between surfaces.

Rows carry references only (``evidence_ref``), never raw evidence payloads, and
every export is bounded by ``limit`` (default :data:`DEFAULT_EXPORT_LIMIT`, hard
maximum :data:`MAX_EXPORT_LIMIT`); rows are produced lazily so nothing beyond
the limit is materialised by this module.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any

from security_lakehouse.io import read_jsonl

EXPORT_SCHEMA_VERSION = "grc-lake.findings.v1"
EXPORT_FORMATS: tuple[str, ...] = ("csv", "jsonl")
DEFAULT_EXPORT_LIMIT = 1_000
MAX_EXPORT_LIMIT = 10_000
EXPORT_COLUMNS: tuple[str, ...] = (
    "export_schema_version",
    "finding_id",
    "tenant_id",
    "source_account_id",
    "control_id",
    "framework_ids",
    "asset_id",
    "severity",
    "state",
    "detected_at",
    "evaluated_at",
    "snapshot_id",
    "assessment_hash",
    "source",
    "event_type",
    "evidence_ref",
)
MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "jsonl": "application/x-ndjson"}
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def parse_export_limit(raw: str | int | None) -> int:
    """Return a validated row limit; ``None`` selects the default."""
    if raw is None or raw == "":
        return DEFAULT_EXPORT_LIMIT
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if limit < 1 or limit > MAX_EXPORT_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_EXPORT_LIMIT}")
    return limit


def parse_export_format(raw: str | None) -> str:
    fmt = (raw or "jsonl").strip().lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"format must be one of {list(EXPORT_FORMATS)}")
    return fmt


def frameworks_by_control(lake: str | Path) -> dict[str, list[str]]:
    """Control id -> framework ids, from the same ``control_posture`` rows the CLI joins on."""
    lookup: dict[str, list[str]] = {}
    for row in read_jsonl(Path(lake) / "gold" / "control_posture.jsonl", missing_ok=True):
        control_id, framework = row.get("control_id"), row.get("framework")
        if isinstance(control_id, str) and isinstance(framework, str) and framework:
            frameworks = lookup.setdefault(control_id, [])
            if framework not in frameworks:
                frameworks.append(framework)
    return lookup


def iter_export_rows(
    posture: Mapping[str, Any],
    *,
    tenant_id: str,
    frameworks: Mapping[str, Sequence[str]],
    limit: int,
    snapshot_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Project at most ``limit`` posture violations onto :data:`EXPORT_COLUMNS`, lazily."""
    evaluated_at = posture.get("evaluated_at")
    assessment_hash = posture.get("assessment_hash")
    violations = posture.get("violations") or ()
    for violation in islice(violations, limit):
        if not isinstance(violation, Mapping):
            continue
        control_id = violation.get("control_id")
        yield {
            "export_schema_version": EXPORT_SCHEMA_VERSION,
            "finding_id": violation.get("violation_id"),
            "tenant_id": tenant_id,
            "source_account_id": violation.get("source_account_id") or None,
            "control_id": control_id,
            "framework_ids": list(frameworks.get(control_id, ())) if isinstance(control_id, str) else [],
            "asset_id": violation.get("asset_id"),
            "severity": violation.get("severity"),
            "state": violation.get("state"),
            "detected_at": violation.get("detected_at"),
            "evaluated_at": evaluated_at,
            "snapshot_id": snapshot_id,
            "assessment_hash": assessment_hash,
            "source": violation.get("source"),
            "event_type": violation.get("event_type"),
            "evidence_ref": violation.get("evidence_ref"),
        }


def csv_safe(value: Any) -> str:
    """Render one CSV cell; a leading formula trigger is neutralised with an apostrophe."""
    if value is None:
        return ""
    text = ";".join(csv_safe(item) for item in value) if isinstance(value, list) else str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return f"'{text}"
    return text


def render_csv(rows: Iterable[Mapping[str, Any]]) -> Iterator[str]:
    """RFC 4180 CSV (CRLF, quoted as needed) with a header row, one chunk per line."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")

    def _flush() -> str:
        chunk = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return chunk

    writer.writerow(EXPORT_COLUMNS)
    yield _flush()
    for row in rows:
        writer.writerow([csv_safe(row.get(column)) for column in EXPORT_COLUMNS])
        yield _flush()


def render_jsonl(rows: Iterable[Mapping[str, Any]]) -> Iterator[str]:
    """One JSON object per line, in column order."""
    for row in rows:
        yield json.dumps({column: row.get(column) for column in EXPORT_COLUMNS}, sort_keys=False) + "\n"


def export_filename(fmt: str, evaluated_at: str | None) -> str:
    stamp = "".join(ch for ch in (evaluated_at or "") if ch.isalnum())[:15] or "current"
    return f"grc-lake-findings-{stamp}.{fmt}"


@dataclass(frozen=True)
class FindingExport:
    """A prepared, bounded export: lazily rendered text chunks plus honest truncation facts."""

    chunks: Iterator[str]
    media_type: str
    filename: str
    limit: int
    total_count: int
    truncated: bool


def prepare_export(lake: str | Path, *, tenant_id: str, fmt: str, limit: int) -> FindingExport:
    """Build the current posture bounded to ``limit`` violations and render it as ``fmt``."""
    from security_lakehouse.assessment import build_current_posture

    fmt = parse_export_format(fmt)
    limit = parse_export_limit(limit)
    # ``max_violations`` streams the lake through a bounded heap, so only the
    # ``limit`` highest-severity violations are ever held for this export while
    # the summary counts still reflect the whole lake.
    posture = build_current_posture(lake, max_violations=limit, inline_violation_cap=None)
    summary = posture.get("violation_summary") or {}
    total_count = int(summary.get("total_count") or len(posture.get("violations") or ()))
    posture["violations"] = sorted(
        posture.get("violations") or (),
        key=lambda row: (-int(row.get("severity_score") or 0), str(row.get("control_id")), str(row.get("event_id"))),
    )
    rows = iter_export_rows(posture, tenant_id=tenant_id, frameworks=frameworks_by_control(lake), limit=limit)
    chunks = render_csv(rows) if fmt == "csv" else render_jsonl(rows)
    return FindingExport(
        chunks=chunks,
        media_type=MEDIA_TYPES[fmt],
        filename=export_filename(fmt, posture.get("evaluated_at")),
        limit=limit,
        total_count=total_count,
        truncated=total_count > limit,
    )


__all__ = [
    "DEFAULT_EXPORT_LIMIT",
    "EXPORT_COLUMNS",
    "EXPORT_FORMATS",
    "EXPORT_SCHEMA_VERSION",
    "MAX_EXPORT_LIMIT",
    "MEDIA_TYPES",
    "FindingExport",
    "csv_safe",
    "export_filename",
    "frameworks_by_control",
    "iter_export_rows",
    "parse_export_format",
    "parse_export_limit",
    "prepare_export",
    "render_csv",
    "render_jsonl",
]
