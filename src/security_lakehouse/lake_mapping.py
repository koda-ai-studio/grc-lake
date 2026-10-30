"""Declarative lake mapping (experimental, spec v1).

A mapping spec describes how rows in a table the customer already owns become
GRC Lake raw evidence, so a lake reader can consume existing security tables
(for example OCSF tables in AWS Security Lake) instead of requiring
GRC Lake-shaped views.

Safety model:

* A spec only names columns. Column references are dotted paths
  (``actor.user.name``, ``resources[0].uid``) validated against a strict
  grammar; the *top-level* segment is the only thing that reaches SQL, as a
  validated identifier. Nested segments are resolved in Python on the fetched
  row, so no dialect-specific path or expression syntax is ever generated.
* Filters are a closed set of comparison operators on top-level columns, and
  every value (filters and the incremental watermark) is bound as a query
  parameter in the backend's native binding syntax, never spliced into SQL.
* The same filters and watermark bound are re-applied in Python to every
  fetched row, so readers without SQL (Iceberg, Parquet, fixtures) have the
  same semantics.
* Rules classify a row from its own field values. They run only in Python and
  set nothing but the outcome vocabulary, framework tags, and catalog
  safeguard IDs, so a verdict and the safeguards it applies to stay together.

The spec reference lives in docs/BRING_YOUR_OWN_LAKE.md.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.models import parse_event_time, utc_iso

logger = logging.getLogger(__name__)

SPEC_VERSION = 1
MAX_SPEC_BYTES = 64 * 1024
MAX_ATTRIBUTES = 64
MAX_FILTERS = 20
MAX_IN_VALUES = 100
MAX_COALESCE = 8
MAX_RULES = 32
MAX_RULE_CONDITIONS = 8
MAX_RULE_IDS = 64
DEFAULT_MAX_ROWS = 50_000

SEVERITIES = ("critical", "high", "medium", "low", "info", "none")
# ``not_evaluated`` marks evidence that needs review: it blocks a pass without
# asserting a failure. ``observed`` carries no verdict at all.
STATUSES = ("pass", "open", "observed", "not_evaluated")
TIME_FORMATS = ("timestamp", "epoch_ms", "epoch_s")
FILTER_OPS = ("eq", "ne", "in", "not_in", "is_null", "is_not_null")
DIALECTS = ("snowflake", "databricks", "clickhouse", "bigquery")

REQUIRED_FIELDS = ("id", "observed_at", "asset_id")
OPTIONAL_FIELDS = (
    "source",
    "source_account_id",
    "event_type",
    "asset_type",
    "owner",
    "environment",
    "severity",
    "status",
    "controls",
    "safeguard_ids",
    "evidence_ref",
)
RULE_OUTPUTS = ("status", "severity", "controls", "safeguard_ids")
PRESET_PACKAGE = "security_lakehouse.lake_presets"

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ATTRIBUTE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SEGMENT = r"[A-Za-z_][A-Za-z0-9_]{0,254}"
_COLUMN_PATH = re.compile(rf"^{_SEGMENT}(?:\.{_SEGMENT}|\[\d{{1,4}}\])*$")
_TOP_COLUMN = re.compile(rf"^{_SEGMENT}$")
_TABLE_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,254}$")
_BIGQUERY_PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
_TABLE_REF = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,254}(?:\.[A-Za-z_][A-Za-z0-9_]{0,254}){0,2}$")
_PATH_TOKEN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
# Connector state redacts option keys containing these words before storing them.
_REDACTED_KEY_WORDS = ("password", "secret", "token", "private_key", "api_key")
_PRESET_NAME = re.compile(r"^[a-z0-9_-]{1,32}/[a-z0-9_]{1,64}$")


class MappingError(ValueError):
    """A mapping spec (or reference to one) is invalid; ``errors`` lists every problem."""

    def __init__(self, errors: list[str] | str) -> None:
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__("invalid lake mapping: " + "; ".join(self.errors))


@dataclass(frozen=True)
class ValueExpr:
    """A value taken from a column path, a constant, or the first non-empty of several."""

    column: str | None = None
    const: Any = None
    coalesce: tuple[ValueExpr, ...] = ()
    map: dict[str, Any] = field(default_factory=dict)
    default: Any = None
    prefix: str = ""
    split: str | None = None
    format: str | None = None

    def columns(self) -> list[str]:
        if self.column:
            return [self.column]
        return [column for item in self.coalesce for column in item.columns()]


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any = None


@dataclass(frozen=True)
class Rule:
    """First matching rule sets the row's outcome, framework tags, and safeguard binding."""

    name: str
    when: tuple[Filter, ...]
    status: str | None = None
    severity: str | None = None
    controls: tuple[str, ...] | None = None
    safeguard_ids: tuple[str, ...] | None = None


@dataclass(frozen=True)
class MappingSpec:
    name: str
    source_table: str
    fields: dict[str, ValueExpr]
    id_columns: tuple[str, ...]
    attributes: dict[str, ValueExpr]
    filters: tuple[Filter, ...] = ()
    incremental: bool = True
    lookback_minutes: int = 0
    description: str = ""
    preset: str | None = None
    rules: tuple[Rule, ...] = ()

    @property
    def observed_column(self) -> str:
        column = self.fields["observed_at"].column
        assert column is not None  # enforced by validation
        return column

    @property
    def observed_format(self) -> str:
        return self.fields["observed_at"].format or "timestamp"

    def top_level_columns(self) -> list[str]:
        """Every top-level column the mapping reads, in stable first-seen order."""
        paths: list[str] = list(self.id_columns)
        for expr in [*self.fields.values(), *self.attributes.values()]:
            paths.extend(expr.columns())
        paths.extend(item.column for item in self.filters)
        paths.extend(condition.column for rule in self.rules for condition in rule.when)
        out: list[str] = []
        seen: set[str] = set()
        for path in paths:
            top = _top(path)
            if top.lower() not in seen:
                seen.add(top.lower())
                out.append(top)
        return out


@dataclass
class MapResult:
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    filtered: int = 0


@dataclass(frozen=True)
class QueryParam:
    name: str
    value: Any
    kind: str  # "string" | "int" | "bool" | "timestamp" (BigQuery watermark only)


@dataclass(frozen=True)
class CompiledQuery:
    """SQL text with every value held out as a named parameter."""

    dialect: str
    sql: str
    bound: tuple[QueryParam, ...]

    @property
    def params(self) -> dict[str, Any]:
        return {param.name: param.value for param in self.bound}

    def databricks_parameters(self) -> list[dict[str, str]]:
        types = {"string": "STRING", "int": "BIGINT", "bool": "BOOLEAN"}
        return [{"name": p.name, "value": _param_text(p.value), "type": types[p.kind]} for p in self.bound]

    def clickhouse_parameters(self) -> dict[str, str]:
        return {p.name: _param_text(p.value) for p in self.bound}

    def bigquery_parameters(self) -> list[tuple[str, str, Any]]:
        types = {"string": "STRING", "int": "INT64", "bool": "BOOL", "timestamp": "TIMESTAMP"}
        return [(p.name, types[p.kind], p.value) for p in self.bound]


# --------------------------------------------------------------------------------
# Loading and validation
# --------------------------------------------------------------------------------


def load_mapping_file(path: str | Path) -> MappingSpec:
    """Load a spec from a local JSON or YAML file (operator CLI use only)."""
    target = Path(path)
    size = target.stat().st_size
    if size > MAX_SPEC_BYTES:
        raise MappingError(f"{target.name}: mapping file is larger than {MAX_SPEC_BYTES} bytes")
    text = target.read_text(encoding="utf-8")
    if target.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:
            raise MappingError("YAML mapping files require PyYAML; install it or use JSON") from exc
        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise MappingError(f"{target.name}: invalid YAML ({exc.__class__.__name__})") from exc
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MappingError(f"{target.name}: invalid JSON at line {exc.lineno} column {exc.colno}") from exc
    return resolve_mapping_ref(payload)


def parse_mapping(payload: Any, *, preset: str | None = None) -> MappingSpec:
    """Validate a spec object and return it compiled; raise with every error found."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        raise MappingError("mapping spec must be a JSON object")
    if len(json.dumps(payload, default=str)) > MAX_SPEC_BYTES:
        raise MappingError(f"mapping spec is larger than {MAX_SPEC_BYTES} bytes")
    _unexpected(
        payload,
        {"spec_version", "name", "description", "source", "filters", "fields", "attributes", "rules"},
        "",
        errors,
    )

    if payload.get("spec_version") != SPEC_VERSION:
        errors.append(f"spec_version: must be {SPEC_VERSION}")
    name = payload.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        errors.append("name: must be 1-64 lowercase letters, digits, '_' or '-'")
    description = payload.get("description", "")
    if not isinstance(description, str) or len(description) > 500:
        errors.append("description: must be a string of at most 500 characters")

    source = payload.get("source")
    table = ""
    incremental = True
    lookback = 0
    if not isinstance(source, dict):
        errors.append("source: required object with a 'table'")
    else:
        _unexpected(source, {"table", "incremental", "lookback_minutes"}, "source", errors)
        raw_table = source.get("table")
        if isinstance(raw_table, str) and _TABLE_REF.fullmatch(raw_table):
            table = raw_table
        else:
            errors.append("source.table: must be 1-3 dot-separated identifiers (letters, digits, '_')")
        incremental = source.get("incremental", True)
        if not isinstance(incremental, bool):
            errors.append("source.incremental: must be true or false")
            incremental = True
        lookback = source.get("lookback_minutes", 0)
        if not isinstance(lookback, int) or isinstance(lookback, bool) or not 0 <= lookback <= 10_080:
            errors.append("source.lookback_minutes: must be an integer between 0 and 10080")
            lookback = 0

    raw_fields = payload.get("fields")
    fields: dict[str, ValueExpr] = {}
    id_columns: tuple[str, ...] = ()
    if not isinstance(raw_fields, dict):
        errors.append("fields: required object")
    else:
        _unexpected(raw_fields, set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS), "fields", errors)
        for required in REQUIRED_FIELDS:
            if required not in raw_fields:
                errors.append(f"fields.{required}: required")
        if "id" in raw_fields:
            id_columns = _parse_id(raw_fields["id"], errors)
        if "observed_at" in raw_fields:
            observed = _parse_expr(raw_fields["observed_at"], "fields.observed_at", errors, allow={"format"})
            if observed is not None:
                if not observed.column:
                    errors.append("fields.observed_at: must be a single {'column': ...} reference")
                elif not _TOP_COLUMN.fullmatch(observed.column):
                    errors.append("fields.observed_at.column: must be a top-level column (it is the watermark)")
                fields["observed_at"] = observed
        for key in ("asset_id", *OPTIONAL_FIELDS):
            if key not in raw_fields:
                continue
            allow = {"split"} if key in {"controls", "safeguard_ids"} else set()
            expr = _parse_expr(raw_fields[key], f"fields.{key}", errors, allow=allow)
            if expr is None:
                continue
            if key == "severity":
                _check_vocab(expr, f"fields.{key}", SEVERITIES, errors)
            elif key == "status":
                _check_vocab(expr, f"fields.{key}", STATUSES, errors)
            elif key == "safeguard_ids":
                _check_safeguard_expr(expr, errors)
            fields[key] = expr

    attributes: dict[str, ValueExpr] = {}
    raw_attributes = payload.get("attributes", {})
    if not isinstance(raw_attributes, dict):
        errors.append("attributes: must be an object")
    elif len(raw_attributes) > MAX_ATTRIBUTES:
        errors.append(f"attributes: at most {MAX_ATTRIBUTES} entries")
    else:
        for key, value in raw_attributes.items():
            if not isinstance(key, str) or not _ATTRIBUTE_KEY.fullmatch(key):
                errors.append(f"attributes.{key}: key must be an identifier (letters, digits, '_')")
                continue
            if any(word in key.lower() for word in _REDACTED_KEY_WORDS):
                errors.append(f"attributes.{key}: key names a secret-like field and would be redacted when stored")
                continue
            expr = _parse_expr(value, f"attributes.{key}", errors, allow=set())
            if expr is not None:
                attributes[key] = expr

    filters = _parse_filters(payload.get("filters", []), errors)
    rules = _parse_rules(payload.get("rules", []), errors)

    if errors:
        raise MappingError(errors)
    return MappingSpec(
        name=str(name),
        source_table=str(table),
        fields=fields,
        id_columns=id_columns,
        attributes=attributes,
        filters=filters,
        incremental=bool(incremental),
        lookback_minutes=int(lookback),
        description=str(description),
        preset=preset,
        rules=rules,
    )


def _unexpected(payload: dict[str, Any], allowed: set[str], path: str, errors: list[str]) -> None:
    for key in payload:
        if key not in allowed:
            label = f"{path}.{key}" if path else str(key)
            errors.append(f"{label}: unexpected key (allowed: {', '.join(sorted(allowed))})")


def _parse_id(raw: Any, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(raw, dict):
        errors.append("fields.id: must be {'column': ...} or {'columns': [...]}")
        return ()
    _unexpected(raw, {"column", "columns"}, "fields.id", errors)
    if ("column" in raw) == ("columns" in raw):
        errors.append("fields.id: exactly one of 'column' or 'columns'")
        return ()
    columns = [raw["column"]] if "column" in raw else raw["columns"]
    key = "fields.id.column" if "column" in raw else "fields.id.columns"
    if not isinstance(columns, list) or not 1 <= len(columns) <= 8:
        errors.append(f"{key}: must list 1-8 column paths")
        return ()
    for column in columns:
        if not isinstance(column, str) or not _COLUMN_PATH.fullmatch(column):
            errors.append(f"{key}: {column!r} is not a column path (identifiers joined by '.', optional [n])")
            return ()
    return tuple(columns)


def _parse_expr(raw: Any, path: str, errors: list[str], *, allow: set[str], depth: int = 0) -> ValueExpr | None:
    if not isinstance(raw, dict):
        errors.append(f"{path}: must be an object with 'column', 'const', or 'coalesce'")
        return None
    modifiers = {"map", "default", "prefix"} | allow
    _unexpected(raw, {"column", "const", "coalesce"} | modifiers, path, errors)
    sources = [key for key in ("column", "const", "coalesce") if key in raw]
    if len(sources) != 1:
        errors.append(f"{path}: exactly one of 'column', 'const', or 'coalesce'")
        return None
    kind = sources[0]
    column = None
    const = None
    coalesce: tuple[ValueExpr, ...] = ()
    if kind == "column":
        column = raw["column"]
        if not isinstance(column, str) or not _COLUMN_PATH.fullmatch(column):
            errors.append(f"{path}.column: {column!r} is not a column path (identifiers joined by '.', optional [n])")
            return None
    elif kind == "const":
        const = raw["const"]
        if not _scalar(const) and not (isinstance(const, list) and all(isinstance(v, str) for v in const)):
            errors.append(f"{path}.const: must be a string, number, boolean, or list of strings")
            return None
    else:
        items = raw["coalesce"]
        if depth > 0 or not isinstance(items, list) or not 1 <= len(items) <= MAX_COALESCE:
            errors.append(f"{path}.coalesce: must be a list of 1-{MAX_COALESCE} column/const objects (not nested)")
            return None
        parsed = [
            _parse_expr(item, f"{path}.coalesce[{i}]", errors, allow=set(), depth=1) for i, item in enumerate(items)
        ]
        if any(item is None for item in parsed):
            return None
        coalesce = tuple(item for item in parsed if item is not None)

    mapping = raw.get("map", {})
    if not isinstance(mapping, dict) or not all(_scalar(v) for v in mapping.values()) or len(mapping) > 200:
        errors.append(f"{path}.map: must be an object of at most 200 source value -> scalar entries")
        mapping = {}
    default = raw.get("default")
    if default is not None and not _scalar(default):
        errors.append(f"{path}.default: must be a scalar")
    prefix = raw.get("prefix", "")
    if not isinstance(prefix, str) or len(prefix) > 64:
        errors.append(f"{path}.prefix: must be a string of at most 64 characters")
        prefix = ""
    split = raw.get("split")
    if split is not None and (not isinstance(split, str) or not 1 <= len(split) <= 4):
        errors.append(f"{path}.split: must be a 1-4 character separator")
    fmt = raw.get("format")
    if fmt is not None and fmt not in TIME_FORMATS:
        errors.append(f"{path}.format: must be one of {', '.join(TIME_FORMATS)}")
    return ValueExpr(
        column=column,
        const=const,
        coalesce=coalesce,
        map={str(k): v for k, v in mapping.items()},
        default=default,
        prefix=prefix,
        split=split,
        format=fmt,
    )


def _check_vocab(expr: ValueExpr, path: str, vocab: tuple[str, ...], errors: list[str]) -> None:
    allowed = ", ".join(vocab)
    if expr.const is not None and str(expr.const) not in vocab:
        errors.append(f"{path}.const: {expr.const!r} is not one of {allowed}")
    for key, value in expr.map.items():
        if str(value) not in vocab:
            errors.append(f"{path}.map.{key}: {value!r} is not one of {allowed}")
    if expr.default is not None and str(expr.default) not in vocab:
        errors.append(f"{path}.default: {expr.default!r} is not one of {allowed}")
    for index, item in enumerate(expr.coalesce):
        if item.const is not None and str(item.const) not in vocab:
            errors.append(f"{path}.coalesce[{index}].const: {item.const!r} is not one of {allowed}")


def _parse_filters(raw: Any, errors: list[str]) -> tuple[Filter, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_FILTERS:
        errors.append(f"filters: must be a list of at most {MAX_FILTERS} filters")
        return ()
    out: list[Filter] = []
    for index, item in enumerate(raw):
        parsed = _parse_condition(item, f"filters[{index}]", errors, nested=False)
        if parsed is not None:
            out.append(parsed)
    return tuple(out)


def _parse_condition(item: Any, path: str, errors: list[str], *, nested: bool) -> Filter | None:
    """One comparison. SQL filters name top-level columns; rule conditions may name nested paths."""
    if not isinstance(item, dict):
        errors.append(f"{path}: must be an object")
        return None
    _unexpected(item, {"column", "op", "value"}, path, errors)
    column, op, value = item.get("column"), item.get("op"), item.get("value")
    ok = True
    if nested:
        if not isinstance(column, str) or not _COLUMN_PATH.fullmatch(column):
            errors.append(f"{path}.column: must be a column path (identifiers joined by '.', optional [n])")
            ok = False
    elif not isinstance(column, str) or not _TOP_COLUMN.fullmatch(column):
        errors.append(f"{path}.column: must be a top-level column name")
        ok = False
    if op not in FILTER_OPS:
        errors.append(f"{path}.op: must be one of {', '.join(FILTER_OPS)}")
        ok = False
    elif op in {"in", "not_in"}:
        if not isinstance(value, list) or not 1 <= len(value) <= MAX_IN_VALUES or not all(_bindable(v) for v in value):
            errors.append(f"{path}.value: must be a list of 1-{MAX_IN_VALUES} strings, integers, or booleans")
            ok = False
    elif op in {"eq", "ne"}:
        if not _bindable(value):
            errors.append(f"{path}.value: must be a string, integer, or boolean")
            ok = False
    elif value is not None:
        errors.append(f"{path}.value: must be omitted for {op}")
        ok = False
    return Filter(column=str(column), op=str(op), value=value) if ok else None


def _parse_rules(raw: Any, errors: list[str]) -> tuple[Rule, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_RULES:
        errors.append(f"rules: must be a list of at most {MAX_RULES} rules")
        return ()
    out: list[Rule] = []
    names: set[str] = set()
    for index, item in enumerate(raw):
        path = f"rules[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{path}: must be an object")
            continue
        _unexpected(item, {"name", "when", *RULE_OUTPUTS}, path, errors)
        name = item.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            errors.append(f"{path}.name: must be 1-64 lowercase letters, digits, '_' or '-'")
        elif name in names:
            errors.append(f"{path}.name: duplicate rule name {name!r}")
        else:
            names.add(name)
        raw_when = item.get("when")
        when: list[Filter] = []
        if not isinstance(raw_when, list) or not 1 <= len(raw_when) <= MAX_RULE_CONDITIONS:
            errors.append(f"{path}.when: must list 1-{MAX_RULE_CONDITIONS} conditions (all must hold)")
        else:
            for position, condition in enumerate(raw_when):
                parsed = _parse_condition(condition, f"{path}.when[{position}]", errors, nested=True)
                if parsed is not None:
                    when.append(parsed)
        if not any(key in item for key in RULE_OUTPUTS):
            errors.append(f"{path}: must set at least one of {', '.join(RULE_OUTPUTS)}")
        status = item.get("status")
        if status is not None and status not in STATUSES:
            errors.append(f"{path}.status: {status!r} is not one of {', '.join(STATUSES)}")
        severity = item.get("severity")
        if severity is not None and severity not in SEVERITIES:
            errors.append(f"{path}.severity: {severity!r} is not one of {', '.join(SEVERITIES)}")
        controls = _parse_id_list(item, "controls", path, errors)
        safeguard_ids = _parse_id_list(item, "safeguard_ids", path, errors)
        if safeguard_ids:
            _check_safeguard_ids(safeguard_ids, f"{path}.safeguard_ids", errors)
        out.append(
            Rule(
                name=str(name),
                when=tuple(when),
                status=status,
                severity=severity,
                controls=controls,
                safeguard_ids=safeguard_ids,
            )
        )
    return tuple(out)


def _parse_id_list(item: dict[str, Any], key: str, path: str, errors: list[str]) -> tuple[str, ...] | None:
    """A rule's identifier list; an empty list deliberately clears the field-level value."""
    if key not in item:
        return None
    values = item[key]
    if (
        not isinstance(values, list)
        or len(values) > MAX_RULE_IDS
        or not all(isinstance(v, str) and v.strip() and len(v) <= 128 for v in values)
    ):
        errors.append(f"{path}.{key}: must be a list of 1-{MAX_RULE_IDS} identifiers (or [] to clear)")
        return None
    return tuple(dict.fromkeys(v.strip() for v in values))


def _check_safeguard_expr(expr: ValueExpr, errors: list[str]) -> None:
    """Constant safeguard bindings must name catalog safeguards; column values are checked per row."""
    ids: list[str] = []
    for value in (expr.const, expr.default, *expr.map.values(), *(item.const for item in expr.coalesce)):
        if isinstance(value, list):
            ids.extend(str(v) for v in value)
        elif isinstance(value, str):
            parts = value.split(expr.split) if expr.split else [value]
            ids.extend(part.strip() for part in parts if part.strip())
    _check_safeguard_ids(ids, "fields.safeguard_ids", errors)


def _check_safeguard_ids(ids: Any, path: str, errors: list[str]) -> None:
    known = known_safeguard_ids()
    for safeguard_id in ids:
        if safeguard_id not in known:
            errors.append(f"{path}: unknown safeguard {safeguard_id!r} (see controls/safeguards.json)")


@lru_cache(maxsize=1)
def known_safeguard_ids() -> frozenset[str]:
    """Safeguard IDs shipped in the CCF catalog, read once per process."""
    from security_lakehouse.safeguards import DEFAULT_SAFEGUARDS

    payload = json.loads(DEFAULT_SAFEGUARDS.read_text(encoding="utf-8"))
    return frozenset(str(row["safeguard_id"]) for row in payload["safeguards"])


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _bindable(value: Any) -> bool:
    return isinstance(value, str | bool) or (isinstance(value, int) and abs(value) < 2**63)


# --------------------------------------------------------------------------------
# Resolution from connector options (inline objects and presets only)
# --------------------------------------------------------------------------------


def list_presets() -> list[str]:
    root = resources.files(PRESET_PACKAGE)
    names: list[str] = []
    for family in root.iterdir():
        if family.is_dir() and not family.name.startswith("_"):
            names.extend(f"{family.name}/{item.name[:-5]}" for item in family.iterdir() if item.name.endswith(".json"))
    return sorted(names)


def load_preset(name: str) -> dict[str, Any]:
    if not isinstance(name, str) or not _PRESET_NAME.fullmatch(name) or name not in list_presets():
        raise MappingError(f"unknown preset {name!r} (available: {', '.join(list_presets())})")
    family, preset = name.split("/", 1)
    text = resources.files(PRESET_PACKAGE).joinpath(family, f"{preset}.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    payload.pop("$comment", None)
    return payload


def resolve_mapping_ref(ref: Any) -> MappingSpec:
    """Resolve one inline spec, or ``{"preset": name, ...overrides}``.

    A string is never treated as a file path here: connector options arrive
    from the API, and reading operator-named server files would be a file
    disclosure primitive. Local files go through :func:`load_mapping_file`.
    """
    if isinstance(ref, str):
        raise MappingError(
            "mapping must be an inline spec object or {'preset': name, 'source': {'table': ...}}; "
            "file paths are only accepted by the CLI"
        )
    if not isinstance(ref, dict):
        raise MappingError("mapping must be an object")
    if "preset" not in ref:
        return parse_mapping(ref)
    overrides = {key: value for key, value in ref.items() if key != "preset"}
    base = load_preset(str(ref["preset"]))
    return parse_mapping(_merge(base, overrides), preset=str(ref["preset"]))


def resolve_mappings(options: dict[str, Any]) -> list[MappingSpec]:
    """Mappings configured on a connector (``options.mapping`` or ``options.mappings``)."""
    refs: list[Any] = []
    if options.get("mapping") not in (None, "", {}):
        refs.append(options["mapping"])
    many = options.get("mappings")
    if many not in (None, "", []):
        if not isinstance(many, list) or len(many) > 32:
            raise MappingError("mappings: must be a list of at most 32 mapping specs")
        refs.extend(many)
    specs = [resolve_mapping_ref(ref) for ref in refs]
    names = [spec.name for spec in specs]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise MappingError(f"duplicate mapping name(s): {', '.join(duplicates)}")
    return specs


def write_mode_for_options(options: dict[str, Any]) -> str | None:
    """``append`` for incremental mappings, ``snapshot`` for full re-reads, None without mappings."""
    specs = resolve_mappings(options)
    if not specs:
        return None
    modes = {spec.incremental for spec in specs}
    if len(modes) > 1:
        raise MappingError("mappings on one connector must all be incremental or all be full re-reads")
    return "append" if modes == {True} else "snapshot"


def _merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


# --------------------------------------------------------------------------------
# Row mapping
# --------------------------------------------------------------------------------


def map_rows(
    spec: MappingSpec,
    rows: list[dict[str, Any]],
    *,
    since: str | None = None,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    default_source: str = "lake",
) -> MapResult:
    """Map fetched source rows to GRC Lake raw events.

    Rows that fail a filter or fall before the watermark bound are counted in
    ``filtered``. Rows that cannot be mapped (no id, unparseable time) are
    reported in ``errors`` by 1-based position and never emitted.
    """
    now = collected_at or datetime.now(UTC)
    bound = lower_bound(spec, since)
    result = MapResult()
    for index, raw in enumerate(rows, start=1):
        row = _lower_keys(raw)
        if not _passes_filters(spec, row):
            result.filtered += 1
            continue
        try:
            event = _map_row(spec, row, raw, now=now, tenant_id=tenant_id, default_source=default_source)
        except _RowError as exc:
            result.errors.append({"row": index, "error": str(exc)})
            continue
        if bound is not None and parse_event_time(event["event_time"]) < bound:
            result.filtered += 1
            continue
        result.events.append(event)
    return result


class _RowError(ValueError):
    pass


def _map_row(
    spec: MappingSpec,
    row: dict[str, Any],
    raw: dict[str, Any],
    *,
    now: datetime,
    tenant_id: str,
    default_source: str,
) -> dict[str, Any]:
    id_values = [resolve_path(row, column) for column in spec.id_columns]
    if all(_empty(value) for value in id_values):
        raise _RowError(f"fields.id: no value at {', '.join(spec.id_columns)}")
    observed = _observed_time(spec, row)
    source = _text(_evaluate(spec.fields.get("source"), row)) or default_source
    event_type = _text(_evaluate(spec.fields.get("event_type"), row)) or f"{source}.{spec.name}"
    asset_id = _text(_evaluate(spec.fields["asset_id"], row))
    if not asset_id:
        raise _RowError("fields.asset_id: no value")
    source_account_id = tenant_id
    if "source_account_id" in spec.fields:
        scope = _evaluate(spec.fields["source_account_id"], row)
        if scope is not None and (not isinstance(scope, str | int) or isinstance(scope, bool)):
            raise _RowError("fields.source_account_id: must be a string or integer identifier")
        source_account_id = _text(scope)
        if not source_account_id:
            raise _RowError("fields.source_account_id: no value")
    rule = next((item for item in spec.rules if _matches(item.when, row)), None)
    severity = _text(_evaluate(spec.fields.get("severity"), row)).lower() or "info"
    if severity not in SEVERITIES:
        severity = "info"
    status = _text(_evaluate(spec.fields.get("status"), row)).lower() or "observed"
    if status not in STATUSES:
        status = "observed"
    controls = _controls(spec.fields.get("controls"), row)
    safeguard_ids = _controls(spec.fields.get("safeguard_ids"), row)
    if rule is not None:
        status = rule.status or status
        severity = rule.severity or severity
        controls = list(rule.controls) if rule.controls is not None else controls
        safeguard_ids = list(rule.safeguard_ids) if rule.safeguard_ids is not None else safeguard_ids
    unknown = sorted(set(safeguard_ids) - known_safeguard_ids())
    if unknown:
        raise _RowError(f"fields.safeguard_ids: unknown safeguard {unknown[0]!r}")

    identity = [spec.name, *[_json_safe(v) for v in id_values]]
    if "source_account_id" in spec.fields:
        identity.append({"source_account_id": source_account_id})
    id_digest = _digest(json.dumps(identity, sort_keys=True, default=str))
    source_slug = re.sub(r"[^a-z0-9_.-]+", "-", source.lower()).strip("-") or "lake"
    stable = f"{source_slug}-{spec.name}-{id_digest[:24]}"
    raw_sha256 = _digest(json.dumps(_json_safe(raw), sort_keys=True, separators=(",", ":"), default=str))
    evidence_ref = _text(_evaluate(spec.fields.get("evidence_ref"), row)) or (
        f"lake://{spec.source_table}/{id_digest[:24]}"
    )
    attributes: dict[str, Any] = {key: _json_safe(_evaluate(expr, row)) for key, expr in spec.attributes.items()}
    attributes.update(
        {
            "source_id": _json_safe(id_values[0] if len(id_values) == 1 else id_values),
            "raw_sha256": raw_sha256,
            "mapping": spec.name,
            "mapping_spec_version": SPEC_VERSION,
            "source_table": spec.source_table,
        }
    )
    if spec.preset:
        attributes["mapping_preset"] = spec.preset
    if rule is not None:
        attributes["mapping_rule"] = rule.name
    event: dict[str, Any] = {
        "event_id": stable,
        "tenant_id": source_account_id,
        "workspace_id": "default",
        "event_time": utc_iso(observed),
        "source": source,
        "event_type": event_type,
        "entity": {
            "asset_id": asset_id,
            "asset_type": _text(_evaluate(spec.fields.get("asset_type"), row)) or "lake_record",
            "asset_owner": _text(_evaluate(spec.fields.get("owner"), row)) or "unassigned",
            "environment": _text(_evaluate(spec.fields.get("environment"), row)) or "unknown",
            "org": source,
        },
        "severity": severity,
        "status": status,
        "controls": controls,
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": attributes,
    }
    if safeguard_ids:
        event["safeguard_ids"] = sorted(safeguard_ids)
    return event


def _observed_time(spec: MappingSpec, row: dict[str, Any]) -> datetime:
    value = resolve_path(row, spec.observed_column)
    try:
        return coerce_time(value, spec.observed_format)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise _RowError(
            f"fields.observed_at: cannot read {spec.observed_column}={value!r} as {spec.observed_format}"
        ) from exc


def coerce_time(value: Any, fmt: str) -> datetime:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("empty time")
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if fmt in {"epoch_ms", "epoch_s"}:
        number = float(value)
        return datetime.fromtimestamp(number / 1000 if fmt == "epoch_ms" else number, UTC)
    return parse_event_time(str(value).strip().replace(" ", "T", 1))


def _evaluate(expr: ValueExpr | None, row: dict[str, Any]) -> Any:
    if expr is None:
        return None
    if expr.column:
        value = resolve_path(row, expr.column)
    elif expr.coalesce:
        value = next((v for v in (_evaluate(item, row) for item in expr.coalesce) if not _empty(v)), None)
    else:
        value = expr.const
    if expr.map and not _empty(value):
        value = expr.map.get(_map_key(value), expr.default if expr.default is not None else value)
    if _empty(value) and expr.default is not None:
        value = expr.default
    if expr.prefix and not _empty(value):
        value = f"{expr.prefix}{value}"
    return value


def _map_key(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float | Decimal) and value == int(value):
        return str(int(value))
    return str(value)


def _controls(expr: ValueExpr | None, row: dict[str, Any]) -> list[str]:
    if expr is None:
        return []
    value = _evaluate(expr, row)
    if isinstance(value, str) and expr.split:
        items: list[Any] = value.split(expr.split)
    elif isinstance(value, list):
        items = value
    elif _empty(value):
        items = []
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def resolve_path(row: dict[str, Any], path: str) -> Any:
    """Resolve a validated column path on a fetched row (top-level keys already lower-cased)."""
    current: Any = row
    for index, (name, position) in enumerate(_PATH_TOKEN.findall(path)):
        if isinstance(current, str) and current[:1] in "{[":
            try:
                current = json.loads(current)
            except json.JSONDecodeError:
                return None
        if name:
            if not isinstance(current, dict):
                return None
            key = name.lower() if index == 0 else name
            if key in current:
                current = current[key]
            else:
                current = next((v for k, v in current.items() if str(k).lower() == name.lower()), None)
        else:
            if not isinstance(current, list | tuple):
                return None
            offset = int(position)
            current = current[offset] if offset < len(current) else None
        if current is None:
            return None
    return current


def _passes_filters(spec: MappingSpec, row: dict[str, Any]) -> bool:
    return _matches(spec.filters, row)


def _matches(conditions: tuple[Filter, ...], row: dict[str, Any]) -> bool:
    """Every condition holds; a missing value fails every op except ``is_null``."""
    for item in conditions:
        value = resolve_path(row, item.column)
        if item.op == "is_null" and value is not None:
            return False
        if item.op == "is_not_null" and value is None:
            return False
        if item.op == "eq" and not _same(value, item.value):
            return False
        if item.op == "ne" and (value is None or _same(value, item.value)):
            return False
        if item.op == "in" and not any(_same(value, v) for v in item.value):
            return False
        if item.op == "not_in" and (value is None or any(_same(value, v) for v in item.value)):
            return False
    return True


def _same(left: Any, right: Any) -> bool:
    if left is None:
        return False
    if isinstance(right, bool) or isinstance(left, bool):
        return str(left).lower() == str(right).lower()
    if isinstance(right, int):
        try:
            return int(left) == right
        except (TypeError, ValueError):
            return False
    return str(left) == str(right)


def lower_bound(spec: MappingSpec, since: str | None) -> datetime | None:
    if not since or not spec.incremental:
        return None
    return parse_event_time(since) - timedelta(minutes=spec.lookback_minutes)


def _lower_keys(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).lower(): value for key, value in row.items()}


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def _text(value: Any) -> str:
    if _empty(value):
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value).strip()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime):
        return utc_iso(value if value.tzinfo else value.replace(tzinfo=UTC))
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value


def _top(path: str) -> str:
    return path.split(".", 1)[0].split("[", 1)[0]


# --------------------------------------------------------------------------------
# Collection helpers shared by every lake reader
# --------------------------------------------------------------------------------

RowFetcher = Callable[[MappingSpec, str | None, int], list[dict[str, Any]]]


# Set by a dry-run preview to receive per-mapping stats from connector builders.
_PREVIEW_SINK: ContextVar[list[dict[str, Any]] | None] = ContextVar("lake_mapping_preview", default=None)


@contextmanager
def capture_mapping_stats() -> Iterator[list[dict[str, Any]]]:
    """Collect per-mapping ``rows_read``/``filtered``/``errors`` from collections inside the block."""
    sink: list[dict[str, Any]] = []
    token = _PREVIEW_SINK.set(sink)
    try:
        yield sink
    finally:
        _PREVIEW_SINK.reset(token)


class MappedRowsError(RuntimeError):
    """Every fetched row failed to map: the spec almost certainly does not match the table."""


def collect_mapped_evidence(
    fetch: RowFetcher,
    specs: list[MappingSpec],
    *,
    since: str | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    default_source: str = "lake",
) -> list[dict[str, Any]]:
    """Fetch and map rows for each spec.

    Unmappable rows make a collection partial and prevent positive verdicts
    for that mapping. If every fetched row fails, the sync fails closed.
    """
    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    events: list[dict[str, Any]] = []
    for spec in specs:
        rows = fetch(spec, since if spec.incremental else None, max_rows + 1)
        truncated = len(rows) > max_rows
        result = map_rows(
            spec,
            rows[:max_rows],
            since=since,
            collected_at=collected_at,
            tenant_id=tenant_id,
            default_source=default_source,
        )
        sink = _PREVIEW_SINK.get()
        if sink is not None:
            sink.append(
                {
                    "mapping": spec.name,
                    "table": spec.source_table,
                    "rows_read": len(rows),
                    "row_limit": max_rows,
                    "truncated": truncated,
                    "mapped_count": len(result.events),
                    "filtered": result.filtered,
                    "errors": result.errors,
                }
            )
            events.extend(result.events)
            continue
        if result.errors and not result.events:
            raise MappedRowsError(
                f"mapping {spec.name!r}: none of {len(result.errors)} fetched rows could be mapped "
                f"(first error: {result.errors[0]['error']}); run 'grc-lake lake map --dry-run'"
            )
        if result.errors or truncated:
            if result.errors:
                logger.warning("mapping %r skipped %d unmappable row(s)", spec.name, len(result.errors))
            for event in result.events:
                event["attributes"]["mapping_partial"] = True
                if event["status"] == "pass":
                    event["attributes"]["mapping_original_status"] = "pass"
                    event["status"] = "not_evaluated"
            if result.errors:
                events.append(_mapping_gap(spec, result, tenant_id=tenant_id, source=default_source, now=collected_at))
            if truncated:
                events.append(
                    _mapping_gap(
                        spec,
                        result,
                        tenant_id=tenant_id,
                        source=default_source,
                        now=collected_at,
                        row_limit=max_rows,
                    )
                )
        events.extend(result.events)
    return events


def _mapping_gap(
    spec: MappingSpec,
    result: MapResult,
    *,
    tenant_id: str,
    source: str,
    now: datetime | None,
    row_limit: int | None = None,
) -> dict[str, Any]:
    reason = "row_limit_exceeded" if row_limit is not None else "unmappable_rows"
    message = (
        "The mapped read exceeded its row limit. Increase max_rows_per_sync within the evaluation budget "
        "or partition the mapping into explicit bounded scopes, then replay. The watermark is held."
        if row_limit is not None
        else "Some rows could not be mapped; inspect the mapping dry-run and replay the affected window."
    )
    gap = CollectionGapError(message, collection=spec.name, reason=reason)
    identity = [tenant_id, source, spec.name, spec.source_table]
    if row_limit is not None:
        identity.append(reason)
    stable = "lake-mapping-gap-" + _digest(json.dumps(identity))[:24]
    # A diagnostic must not move the shared watermark beyond the collected evidence.
    event_time = max((event["event_time"] for event in result.events), default=utc_iso(now or datetime.now(UTC)))
    return {
        "event_id": stable,
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": event_time,
        "source": source,
        "event_type": "lake.collection_gap",
        "entity": {
            "asset_id": stable,
            "asset_type": "collection_scope",
            "asset_owner": "unassigned",
            "environment": "unknown",
            "org": source,
        },
        "severity": "info",
        "status": "not_evaluated",
        "controls": [],
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": f"lake://{spec.source_table}/mapping-gap",
            "evidence_collected_at": utc_iso(now or datetime.now(UTC)),
        },
        "attributes": {
            **gap.attributes(),
            "mapping": spec.name,
            "unmapped_rows": len(result.errors),
            **({"row_limit": row_limit} if row_limit is not None else {}),
        },
    }


def probe_mappings(client: Any, specs: list[MappingSpec]) -> dict[str, Any]:
    """Read one row per mapped table to prove the read scope; errors carry the exception class only."""
    checks: list[dict[str, Any]] = []
    for spec in specs:
        try:
            rows = client.fetch_mapping_rows(spec, since=None, limit=1)
        except Exception as exc:  # noqa: BLE001 - probes surface sanitized errors
            checks.append(
                {
                    "mapping": spec.name,
                    "table": spec.source_table,
                    "ok": False,
                    "sample_rows": None,
                    "error": exc.__class__.__name__,
                }
            )
            continue
        checks.append(
            {"mapping": spec.name, "table": spec.source_table, "ok": True, "sample_rows": len(rows), "error": None}
        )
    return {"ok": all(check["ok"] for check in checks), "mappings": checks}


def read_fixture_table(fixture_dir: str | Path, table: str) -> list[dict[str, Any]]:
    """Rows for ``table`` from ``<fixture_dir>/<table>.json`` (a list) or ``.jsonl``."""
    base = Path(fixture_dir)
    for name in (table, table.rsplit(".", 1)[-1]):
        json_path = base / f"{name}.json"
        if json_path.is_file():
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
        jsonl_path = base / f"{name}.jsonl"
        if jsonl_path.is_file():
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            return [row for row in (json.loads(line) for line in lines if line.strip()) if isinstance(row, dict)]
    return []


def json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Lower-case top-level keys and convert driver types to JSON-safe values."""
    return {str(key).lower(): _json_safe(value) for key, value in row.items()}


# --------------------------------------------------------------------------------
# SQL compilation
# --------------------------------------------------------------------------------


def compile_select(
    spec: MappingSpec,
    dialect: str,
    *,
    since: str | None = None,
    limit: int | None = None,
    default_namespace: tuple[str, ...] = (),
) -> CompiledQuery:
    """Compile a spec to one parameterized, read-only SELECT for ``dialect``.

    Only validated identifiers reach the SQL text. Filter values and the
    watermark bound are returned as parameters for the driver to bind.
    """
    if dialect not in DIALECTS:
        raise MappingError(f"unsupported dialect {dialect!r}")
    table = _table_sql(spec.source_table, dialect, default_namespace)
    bound: list[QueryParam] = []

    def placeholder(value: Any, *, kind: str | None = None) -> str:
        name = f"p{sum(1 for p in bound if p.name != 'since')}"
        param = QueryParam(name, value, kind or _kind(value))
        bound.append(param)
        return _marker(dialect, param)

    conditions: list[str] = []
    for item in spec.filters:
        column = _quote(item.column, dialect)
        if item.op == "is_null":
            conditions.append(f"{column} IS NULL")
        elif item.op == "is_not_null":
            conditions.append(f"{column} IS NOT NULL")
        elif item.op in {"eq", "ne"}:
            conditions.append(f"{column} {'=' if item.op == 'eq' else '!='} {placeholder(item.value)}")
        else:
            markers = ", ".join(placeholder(value) for value in item.value)
            conditions.append(f"{column} {'IN' if item.op == 'in' else 'NOT IN'} ({markers})")

    observed = _quote(spec.observed_column, dialect)
    lower = lower_bound(spec, since)
    if lower is not None:
        bound_param = watermark_param(spec, lower)
        if dialect == "bigquery" and bound_param.kind == "string":
            # A typed TIMESTAMP parameter needs no string parsing on the server.
            bound_param = QueryParam("since", lower, "timestamp")
        bound.append(bound_param)
        conditions.append(f"{observed} >= {_watermark_expr(dialect, bound_param, spec.observed_format)}")

    columns = ", ".join(_quote(column, dialect) for column in spec.top_level_columns())
    sql = f"SELECT {columns} FROM {table}"  # noqa: S608 - identifiers validated; values bound
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += f" ORDER BY {observed}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    if dialect == "clickhouse":
        sql += " FORMAT JSONEachRow"
    return CompiledQuery(dialect=dialect, sql=sql, bound=tuple(bound))


def watermark_param(spec: MappingSpec, lower: datetime) -> QueryParam:
    if spec.observed_format == "epoch_ms":
        return QueryParam("since", int(lower.timestamp() * 1000), "int")
    if spec.observed_format == "epoch_s":
        return QueryParam("since", int(lower.timestamp()), "int")
    return QueryParam("since", utc_iso(lower), "string")


def _watermark_expr(dialect: str, param: QueryParam, fmt: str) -> str:
    marker = _marker(dialect, param)
    if fmt != "timestamp":
        return marker
    return {
        "snowflake": f"TO_TIMESTAMP_TZ({marker})",
        "databricks": f"CAST({marker} AS TIMESTAMP)",
        "clickhouse": f"parseDateTime64BestEffort({marker})",
        "bigquery": marker,
    }[dialect]


def _marker(dialect: str, param: QueryParam) -> str:
    if dialect == "snowflake":
        return f"%({param.name})s"
    if dialect == "databricks":
        return f":{param.name}"
    if dialect == "bigquery":
        return f"@{param.name}"
    kind = {"string": "String", "int": "Int64", "bool": "Bool"}[param.kind]
    return f"{{{param.name}:{kind}}}"


def _kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    return "string"


def _quote(identifier: str, dialect: str) -> str:
    if not _TOP_COLUMN.fullmatch(identifier):
        raise MappingError(f"unsafe identifier {identifier!r}")
    if dialect in {"databricks", "bigquery"}:
        return f"`{identifier}`"
    # Snowflake and ClickHouse: strictly validated bare identifiers (Snowflake
    # resolves them case-insensitively, matching how the views are read today).
    return identifier


def _table_sql(table: str, dialect: str, default_namespace: tuple[str, ...]) -> str:
    parts = table.split(".")
    if len(parts) == 1 and default_namespace:
        parts = [*default_namespace, *parts]
    limit = 2 if dialect == "clickhouse" else 3
    if len(parts) > limit:
        raise MappingError(f"source.table {table!r} has too many parts for {dialect}")
    for index, part in enumerate(parts):
        project_slot = dialect == "bigquery" and index == 0 and len(parts) == 3
        if project_slot and _BIGQUERY_PROJECT.fullmatch(part):
            continue
        if not _TABLE_PART.fullmatch(part):
            raise MappingError(f"source.table part {part!r} is not a valid {dialect} identifier")
    if dialect in {"databricks", "bigquery"}:
        return ".".join(f"`{part}`" for part in parts)
    return ".".join(parts)


def _param_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
