"""IAM identity-policy normalization adapted from Agent-Bom (see NOTICE).

Preserves deny and condition semantics; does not evaluate authorization.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class EvidenceCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


def _strings(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, list) else [value]
    return tuple(sorted({item.strip() for item in values if isinstance(item, str) and item.strip()}))


def _canonical_condition_scalar(item: Any) -> str | None:
    # bool is a subclass of int, so it must be checked first; a JSON bool/number
    # condition value must reach the evaluator, not be dropped as a non-string.
    if isinstance(item, bool):
        return "true" if item else "false"
    if isinstance(item, str):
        stripped = item.strip()
        return stripped or None
    if isinstance(item, (int, float)):
        return str(item)
    return None


def _condition_values(value: Any) -> tuple[str, ...]:
    values = value if isinstance(value, list) else [value]
    canonical = {resolved for item in values if (resolved := _canonical_condition_scalar(item)) is not None}
    return tuple(sorted(canonical))


def _conditions(value: Any) -> tuple[tuple[str, str, tuple[str, ...]], ...] | None:
    """Retain every guard, or mark the whole condition unreadable."""
    if not isinstance(value, Mapping) or not value:
        return None
    normalized: list[tuple[str, str, tuple[str, ...]]] = []
    for operator, entries in value.items():
        if not isinstance(operator, str) or not operator.strip() or not isinstance(entries, Mapping) or not entries:
            return None
        for key, raw_values in entries.items():
            if not isinstance(key, str) or not key.strip():
                return None
            items = raw_values if isinstance(raw_values, list) else [raw_values]
            if not items or any(_canonical_condition_scalar(item) is None for item in items):
                return None
            normalized.append((operator.strip(), key.strip(), _condition_values(raw_values)))
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class NormalizedIamStatement:
    effect: Literal["Allow", "Deny"]
    actions: tuple[str, ...] = ()
    not_actions: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    not_resources: tuple[str, ...] = ()
    conditions: tuple[tuple[str, str, tuple[str, ...]], ...] = ()
    sid: str | None = None


@dataclass(frozen=True)
class NormalizedIamPolicy:
    version: str | None
    statements: tuple[NormalizedIamStatement, ...]
    completeness: EvidenceCompleteness
    diagnostics: tuple[str, ...] = ()
    source_policy_arn: str | None = None


def normalize_iam_policy_document(
    document: Any,
    *,
    source_policy_arn: str | None = None,
) -> NormalizedIamPolicy:
    """Canonicalize an IAM policy document without raising on provider input."""
    if not isinstance(document, Mapping):
        return NormalizedIamPolicy(
            version=None,
            statements=(),
            completeness=EvidenceCompleteness.UNAVAILABLE,
            diagnostics=("policy_document_not_mapping",),
            source_policy_arn=source_policy_arn,
        )

    version_value = document.get("Version")
    version = version_value.strip() if isinstance(version_value, str) and version_value.strip() else None
    raw_statements = document.get("Statement", [])
    if isinstance(raw_statements, Mapping):
        raw_statements = [raw_statements]
    if not isinstance(raw_statements, list):
        raw_statements = []

    statements: list[NormalizedIamStatement] = []
    diagnostics: list[str] = []
    for index, raw in enumerate(raw_statements):
        if not isinstance(raw, Mapping):
            diagnostics.append(f"statement_{index}_not_mapping")
            continue
        effect = raw.get("Effect")
        if effect not in {"Allow", "Deny"}:
            diagnostics.append(f"statement_{index}_invalid_effect")
            continue
        forms = ("Action", "NotAction", "Resource", "NotResource")
        if any(key not in {"Sid", "Effect", "Condition", *forms} for key in raw) or any(
            not isinstance(raw[key], (str, list))
            or not (values := raw[key] if isinstance(raw[key], list) else [raw[key]])
            or any(not isinstance(item, str) or not item.strip() for item in values)
            for key in forms
            if key in raw
        ):
            diagnostics.append(f"statement_{index}_invalid_fields")
            continue
        actions = _strings(raw.get("Action"))
        not_actions = _strings(raw.get("NotAction"))
        resources = _strings(raw.get("Resource"))
        not_resources = _strings(raw.get("NotResource"))
        if bool(actions) == bool(not_actions):
            diagnostics.append(f"statement_{index}_requires_exactly_one_action_form")
            continue
        if bool(resources) == bool(not_resources):
            diagnostics.append(f"statement_{index}_conflicting_resource_forms")
            continue
        conditions = _conditions(raw["Condition"]) if "Condition" in raw else ()
        if conditions is None:
            diagnostics.append(f"statement_{index}_invalid_condition")
            continue
        sid_value = raw.get("Sid")
        statements.append(
            NormalizedIamStatement(
                effect=effect,
                actions=actions,
                not_actions=not_actions,
                resources=resources,
                not_resources=not_resources,
                conditions=conditions,
                sid=sid_value.strip() if isinstance(sid_value, str) and sid_value.strip() else None,
            )
        )

    if not statements:
        completeness = EvidenceCompleteness.UNAVAILABLE
        if not diagnostics:
            diagnostics.append("policy_has_no_statements")
    elif diagnostics:
        completeness = EvidenceCompleteness.PARTIAL
    else:
        completeness = EvidenceCompleteness.COMPLETE
    return NormalizedIamPolicy(
        version=version,
        statements=tuple(statements),
        completeness=completeness,
        diagnostics=tuple(diagnostics),
        source_policy_arn=source_policy_arn,
    )
