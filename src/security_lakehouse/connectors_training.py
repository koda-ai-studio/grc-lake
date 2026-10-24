"""Vendor-neutral security-awareness training completion exports.

Most learning-management and security-awareness platforms can export
assignment and completion records as CSV or JSON. This connector reads such an
export from a local file or directory and emits one
``training.assignment.record`` observation per person and course. It makes no
vendor API calls, so there is no provider paging or rate-limit contract to
qualify; the export's completeness is the operator's responsibility and the
file's SHA-256 is kept as provenance.

Column contract (header names, case-sensitive; rename with
``options.column_map``):

* ``person_email`` and/or ``employee_id`` — at least one per row
* ``course_id`` (required), ``course_name``
* ``assigned_at``, ``due_at``, ``completed_at`` — ``YYYY-MM-DD`` or ISO-8601
* ``status`` (required) — ``completed``, ``in_progress``, ``not_started`` or
  ``overdue`` (common vendor spellings are normalized)
* ``score`` (0-100), ``required`` (boolean, default true)

Any other column is ignored and never stored. A malformed or empty export
fails the sync with row numbers and column names only; values are never
echoed, so personal data cannot leak into errors or logs. Evaluation against
the HR population happens in :mod:`security_lakehouse.training_coverage`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from security_lakehouse import strict_json
from security_lakehouse.hris import PERSONNEL_SENSITIVITY
from security_lakehouse.io import canonical_sha256
from security_lakehouse.models import utc_iso

CONNECTOR_ID = "training-completion"
SOURCE = "training_export"
EVENT_TYPE = "training.assignment.record"
ASSET_TYPE = "training_assignment"

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 50
MAX_RECORDS = 200_000
MAX_FIELD_CHARS = 512
MAX_REPORTED_ERRORS = 10
DEFAULT_WINDOW_DAYS = 365
MAX_WINDOW_DAYS = 1095
DEFAULT_GRACE_DAYS = 30
MAX_GRACE_DAYS = 365
DEFAULT_SYSTEM = "training-export"

COLUMNS = (
    "person_email",
    "employee_id",
    "course_id",
    "course_name",
    "assigned_at",
    "due_at",
    "completed_at",
    "status",
    "score",
    "required",
)
STATUSES = ("completed", "in_progress", "not_started", "overdue")
STATUS_ALIASES = {
    "completed": "completed",
    "complete": "completed",
    "passed": "completed",
    "finished": "completed",
    "in_progress": "in_progress",
    "in progress": "in_progress",
    "started": "in_progress",
    "not_started": "not_started",
    "not started": "not_started",
    "assigned": "not_started",
    "enrolled": "not_started",
    "overdue": "overdue",
    "past_due": "overdue",
    "past due": "overdue",
}
_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SYSTEM = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A completion recorded slightly ahead of collection (timezone skew) is tolerated.
_FUTURE_SKEW = timedelta(days=1)


# (kind, number, values): "row" numbers count CSV lines, "record" numbers JSON items.
_Row = tuple[str, int, dict[str, Any]]


class TrainingExportError(ValueError):
    """The export is unreadable or breaks the column contract."""


@dataclass(frozen=True)
class TrainingExportSettings:
    completion_window_days: int = DEFAULT_WINDOW_DAYS
    new_hire_grace_days: int = DEFAULT_GRACE_DAYS
    system: str = DEFAULT_SYSTEM
    column_map: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_options(cls, options: Mapping[str, Any] | None) -> TrainingExportSettings:
        options = options or {}
        return cls(
            completion_window_days=_bounded_int(
                options, "completion_window_days", DEFAULT_WINDOW_DAYS, 1, MAX_WINDOW_DAYS
            ),
            new_hire_grace_days=_bounded_int(options, "new_hire_grace_days", DEFAULT_GRACE_DAYS, 0, MAX_GRACE_DAYS),
            system=_system(options.get("system")),
            column_map=_column_map(options.get("column_map")),
        )


@dataclass(frozen=True)
class TrainingRecord:
    person_email: str | None
    employee_id: str | None
    course_id: str
    course_name: str | None
    assigned_at: str | None
    due_at: str | None
    completed_at: str | None
    status: str
    score: float | None
    required: bool
    source_file: str
    source_row: int
    export_sha256: str


def read_training_export(
    path: str | Path, *, settings: TrainingExportSettings, collected_at: datetime
) -> list[TrainingRecord]:
    """Read every export file at ``path`` (a file, or a directory of them)."""
    records: list[TrainingRecord] = []
    for file_path in _export_files(Path(path)):
        records.extend(_read_file(file_path, settings=settings, collected_at=collected_at))
        if len(records) > MAX_RECORDS:
            raise TrainingExportError(f"training export exceeds {MAX_RECORDS} records")
    if not records:
        raise TrainingExportError("training export contains no training records")
    return _latest_per_assignment(records)


def collect_training_evidence(
    path: str | Path,
    *,
    settings: TrainingExportSettings,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    records = read_training_export(path, settings=settings, collected_at=now)
    return [_event(record, settings=settings, collected_at=now, tenant_id=tenant_id) for record in records]


def person_key(email: str | None, employee_id: str | None) -> str:
    return f"email:{email}" if email else f"employee:{employee_id}"


def _event(
    record: TrainingRecord, *, settings: TrainingExportSettings, collected_at: datetime, tenant_id: str
) -> dict[str, Any]:
    digest = canonical_sha256([settings.system, person_key(record.person_email, record.employee_id), record.course_id])[
        :32
    ]
    return {
        "event_id": f"{CONNECTOR_ID}-{digest}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": SOURCE,
        "event_type": EVENT_TYPE,
        "entity": {
            "asset_id": f"training-assignment:{digest}",
            "asset_type": ASSET_TYPE,
            "asset_owner": settings.system,
            "environment": "prod",
            "org": settings.system,
        },
        "severity": "info",
        "status": "observed",
        "controls": [],
        "evidence": {
            "evidence_id": f"ev-{CONNECTOR_ID}-{digest}",
            "evidence_ref": f"training-export://{settings.system}/{record.source_file}#row={record.source_row}",
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": {
            "person_email": record.person_email,
            "employee_id": record.employee_id,
            "course_id": record.course_id,
            "course_name": record.course_name,
            "assigned_at": record.assigned_at,
            "due_at": record.due_at,
            "completed_at": record.completed_at,
            "training_status": record.status,
            "score": record.score,
            "required": record.required,
            "system": settings.system,
            "source_file": record.source_file,
            "source_row": record.source_row,
            "export_sha256": record.export_sha256,
            "completion_window_days": settings.completion_window_days,
            "new_hire_grace_days": settings.new_hire_grace_days,
            "data_sensitivity": PERSONNEL_SENSITIVITY,
        },
    }


# --- files ------------------------------------------------------------------------


def _export_files(path: Path) -> list[Path]:
    if not path.exists():
        raise TrainingExportError("training export path does not exist")
    if path.is_file():
        if path.suffix.lower() not in {".csv", ".json"}:
            raise TrainingExportError("training export files must be .csv or .json")
        return [path]
    if not path.is_dir():
        raise TrainingExportError("training export path must be a file or directory")
    directory = path.resolve()
    files = sorted(
        child
        for child in path.iterdir()
        if child.suffix.lower() in {".csv", ".json"} and not child.name.startswith(".")
    )
    if not files:
        raise TrainingExportError("training export directory has no .csv or .json files")
    if len(files) > MAX_FILES:
        raise TrainingExportError(f"training export directory has more than {MAX_FILES} export files")
    for child in files:
        resolved = child.resolve()
        if resolved.parent != directory or not resolved.is_file():
            raise TrainingExportError(f"{child.name}: resolves outside the export directory")
    return files


def _read_file(path: Path, *, settings: TrainingExportSettings, collected_at: datetime) -> list[TrainingRecord]:
    name = path.name
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise TrainingExportError(f"{name}: exceeds the {MAX_FILE_BYTES}-byte export limit")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise TrainingExportError(f"{name}: exceeds the {MAX_FILE_BYTES}-byte export limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TrainingExportError(f"{name}: is not UTF-8 text") from exc
    sha256 = hashlib.sha256(data).hexdigest()
    rows = _csv_rows(name, text, settings) if path.suffix.lower() == ".csv" else _json_rows(name, text, settings)
    return _parse(name, rows, sha256=sha256, collected_at=collected_at)


def _csv_rows(name: str, text: str, settings: TrainingExportSettings) -> list[_Row]:
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if not header or not any(cell.strip() for cell in header):
            raise TrainingExportError(f"{name}: CSV has no header row")
        header = [cell.strip() for cell in header]
        if len(set(header)) != len(header):
            raise TrainingExportError(f"{name}: CSV header has duplicate column names")
        source = _source_columns(name, set(header), settings)
        rows: list[_Row] = []
        for line, cells in enumerate(reader, start=2):
            if not any(cell.strip() for cell in cells):
                continue
            if len(cells) > len(header):
                rows.append(("row", line, {"__error__": "has more fields than the header"}))
                continue
            values = dict(zip(header, cells, strict=False))
            rows.append(("row", line, {column: values.get(src) for column, src in source.items()}))
    except csv.Error as exc:
        raise TrainingExportError(f"{name}: malformed CSV ({exc.__class__.__name__})") from exc
    return rows


def _json_rows(name: str, text: str, settings: TrainingExportSettings) -> list[_Row]:
    try:
        payload = strict_json.loads(text)
    except ValueError as exc:
        raise TrainingExportError(f"{name}: not valid JSON") from exc
    if isinstance(payload, dict) and set(payload) == {"records"}:
        payload = payload["records"]
    if not isinstance(payload, list):
        raise TrainingExportError(f"{name}: JSON must be a list of records or an object with a records list")
    present: set[str] = set()
    for item in payload:
        if isinstance(item, dict):
            present.update(str(key) for key in item)
    source = _source_columns(name, present, settings, require_header=False)
    rows: list[_Row] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            rows.append(("record", index, {"__error__": "must be an object"}))
            continue
        rows.append(("record", index, {column: item.get(src) for column, src in source.items()}))
    return rows


def _source_columns(
    name: str, present: set[str], settings: TrainingExportSettings, *, require_header: bool = True
) -> dict[str, str]:
    source = {column: settings.column_map.get(column, column) for column in COLUMNS}
    if require_header:
        for column in ("course_id", "status"):
            if source[column] not in present:
                raise TrainingExportError(f"{name}: missing required column: {column}")
        if source["person_email"] not in present and source["employee_id"] not in present:
            raise TrainingExportError(f"{name}: needs a person_email or employee_id column")
    return source


# --- rows -------------------------------------------------------------------------


def _parse(name: str, rows: list[_Row], *, sha256: str, collected_at: datetime) -> list[TrainingRecord]:
    records: list[TrainingRecord] = []
    errors: list[str] = []
    for kind, number, values in rows:
        try:
            records.append(_record(number, values, name=name, sha256=sha256, collected_at=collected_at))
        except _RowError as exc:
            errors.append(f"{kind} {number}: {exc}")
    if errors:
        shown = "; ".join(errors[:MAX_REPORTED_ERRORS])
        more = f" (first {MAX_REPORTED_ERRORS} shown)" if len(errors) > MAX_REPORTED_ERRORS else ""
        raise TrainingExportError(f"{name}: {len(errors)} invalid rows{more}: {shown}")
    return records


class _RowError(ValueError):
    pass


def _record(number: int, values: dict[str, Any], *, name: str, sha256: str, collected_at: datetime) -> TrainingRecord:
    if "__error__" in values:
        raise _RowError(values["__error__"])
    email = _text(values, "person_email")
    if email is not None:
        email = email.lower()
        if not _EMAIL.fullmatch(email):
            raise _RowError("invalid person_email")
    employee_id = _text(values, "employee_id")
    if email is None and employee_id is None:
        raise _RowError("needs person_email or employee_id")
    course_id = _text(values, "course_id")
    if course_id is None:
        raise _RowError("missing course_id")
    raw_status = _text(values, "status")
    if raw_status is None:
        raise _RowError("missing status")
    status = STATUS_ALIASES.get(raw_status.lower())
    if status is None:
        raise _RowError("unknown status (expected one of " + ", ".join(STATUSES) + ")")
    completed_at = _date(values, "completed_at")
    if status == "completed" and completed_at is None:
        raise _RowError("completed without completed_at")
    if status != "completed" and completed_at is not None:
        raise _RowError("completed_at set on a record that is not completed")
    if completed_at is not None and completed_at > (collected_at + _FUTURE_SKEW).date():
        raise _RowError("completed_at is in the future")
    return TrainingRecord(
        person_email=email,
        employee_id=employee_id,
        course_id=course_id,
        course_name=_text(values, "course_name"),
        assigned_at=_iso(_date(values, "assigned_at")),
        due_at=_iso(_date(values, "due_at")),
        completed_at=_iso(completed_at),
        status=status,
        score=_score(values),
        required=_required(values),
        source_file=name,
        source_row=number,
        export_sha256=sha256,
    )


def _text(values: dict[str, Any], column: str) -> str | None:
    value = values.get(column)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise _RowError(f"{column} must be text")
    text = str(value).strip()
    if len(text) > MAX_FIELD_CHARS:
        raise _RowError(f"{column} exceeds {MAX_FIELD_CHARS} characters")
    return text or None


def _date(values: dict[str, Any], column: str) -> date | None:
    text = _text(values, column)
    if text is None:
        return None
    try:
        if _DATE.fullmatch(text):
            return date.fromisoformat(text)
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _RowError(f"invalid {column} (use YYYY-MM-DD or ISO-8601)") from exc
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.date()


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _score(values: dict[str, Any]) -> float | None:
    value = values.get("score")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise _RowError("invalid score (expected 0-100)") from exc
    if not 0 <= score <= 100:
        raise _RowError("invalid score (expected 0-100)")
    return score


def _required(values: dict[str, Any]) -> bool:
    value = values.get("required")
    if value is None or isinstance(value, bool):
        return True if value is None else value
    text = str(value).strip().lower()
    if not text or text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise _RowError("invalid required (expected true or false)")


def _latest_per_assignment(records: Iterable[TrainingRecord]) -> list[TrainingRecord]:
    """Keep one record per person and course: the most recent activity wins.

    A reassignment dated after an earlier completion supersedes it; on the same
    date a completion wins over an open assignment.
    """
    best: dict[tuple[str, str], TrainingRecord] = {}
    for record in records:
        key = (person_key(record.person_email, record.employee_id), record.course_id)
        current = best.get(key)
        if current is None or _rank(record) > _rank(current):
            best[key] = record
    return sorted(best.values(), key=lambda r: (r.source_file, r.source_row))


def _rank(record: TrainingRecord) -> tuple[str, int]:
    return (max(record.completed_at or "", record.assigned_at or ""), 1 if record.completed_at else 0)


def _bounded_int(options: Mapping[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise TrainingExportError(f"options.{key} must be an integer from {low} to {high}")
    return value


def _system(value: Any) -> str:
    if value is None or value == "":
        return DEFAULT_SYSTEM
    if not isinstance(value, str) or not _SYSTEM.fullmatch(value):
        raise TrainingExportError("options.system must be a short lowercase label such as 'lms'")
    return value


def _column_map(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > len(COLUMNS):
        raise TrainingExportError("options.column_map must map contract columns to export column names")
    for key, header in value.items():
        if key not in COLUMNS:
            raise TrainingExportError(f"options.column_map has an unknown column: {key}")
        if not isinstance(header, str) or not header.strip() or len(header) > 128:
            raise TrainingExportError(f"options.column_map.{key} must name an export column")
    headers = [header.strip() for header in value.values()]
    if len(set(headers)) != len(headers):
        raise TrainingExportError("options.column_map maps two columns to the same export column")
    return {key: header.strip() for key, header in value.items()}
