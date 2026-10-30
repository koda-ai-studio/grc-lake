"""Explicit safeguard evidence evaluated once within the observed asset scope.

Framework tags never imply a safeguard assertion. Proposed mappings and missing
asset evidence cannot become passes. Inventory completeness is a separate claim.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime

from security_lakehouse.catalog import framework_registry_view
from security_lakehouse.control_verdict import evaluate_evidence_verdict
from security_lakehouse.domain_identity import source_asset_key
from security_lakehouse.evidence_freshness import build_evidence_freshness, current_evidence_is_stale
from security_lakehouse.jsontypes import JsonObject
from security_lakehouse.safeguards import ATTESTABLE_STATES, contributes_to_coverage, effective_review_state
from security_lakehouse.vocabulary import ControlVerdict

__all__ = ["INVALID_ASSET_TYPE_REASON", "binding_applies", "evaluate_safeguards", "framework_provider_sources"]

INVALID_ASSET_TYPE_REASON = "The asset type does not establish safeguard applicability."
COLLECTION_SCOPE = "collection_scope"


def binding_applies(asset_types: set[str], eligible_types: set[str]) -> bool:
    """A binding is assessable only when its asset has one type the safeguard accepts."""
    return len(asset_types) == 1 and asset_types <= eligible_types


def _combine(states: list[str]) -> str:
    if ControlVerdict.FAIL in states:
        return ControlVerdict.FAIL.value
    if not states or ControlVerdict.NOT_EVALUATED in states:
        return ControlVerdict.NOT_EVALUATED.value
    if ControlVerdict.STALE in states:
        return ControlVerdict.STALE.value
    return ControlVerdict.PASS.value


def framework_provider_sources() -> dict[str, frozenset[str]]:
    """Evidence sources each provider-scoped framework (a provider benchmark) accepts."""
    return {
        framework_id: frozenset(framework["provider_sources"])
        for framework_id, framework in framework_registry_view().items()
        if framework.get("provider_sources")
    }


def evaluate_safeguards(
    events: list[JsonObject],
    payload: JsonObject,
    controls: dict[str, JsonObject],
    *,
    now: datetime | None = None,
    provider_sources: Mapping[str, Iterable[str]] | None = None,
) -> JsonObject:
    # Validate before a dict can hide duplicate definitions or a mapping can
    # transfer a passing safeguard to a different framework's requirement.
    # ``controls`` is the assessment scope; mappings outside it are not assessed.
    definitions: dict[str, JsonObject] = {}
    for row in payload["safeguards"]:
        safeguard_id = row["safeguard_id"]
        if not isinstance(safeguard_id, str) or not safeguard_id.strip():
            raise ValueError("CCF safeguard_id must be a nonempty identifier")
        if safeguard_id in definitions:
            raise ValueError(f"CCF duplicate safeguard identity: {safeguard_id}")
        seen: set[str] = set()
        for member in row["satisfies"]:
            control_id = member["control_id"]
            if not isinstance(control_id, str) or not control_id.strip():
                raise ValueError("CCF mapping control_id must be a nonempty identifier")
            if control_id in seen:
                raise ValueError(f"CCF duplicate mapping target: {safeguard_id}/{control_id}")
            seen.add(control_id)
            control = controls.get(control_id)
            if control is not None and member.get("framework_id", control.get("framework_id")) != control.get(
                "framework_id"
            ):
                raise ValueError(f"CCF mapping framework disagrees with target: {safeguard_id}/{control_id}")
        definitions[safeguard_id] = row
    assets: dict[tuple[str, str], set[str]] = defaultdict(set)
    bound: dict[str, dict[tuple[str, str], list[JsonObject]]] = defaultdict(lambda: defaultdict(list))
    freshness = {(row["tenant_id"], row["event_id"]): row for row in build_evidence_freshness(events, now=now)}
    # Combined results cover all observed source accounts. An account with only
    # a collection gap cannot borrow another account's passing provider evidence.
    gap_sources: set[str] = set()
    bound_sources: dict[str, set[str]] = defaultdict(set)
    observed_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    for event in events:
        asset_key: tuple[str, str] = source_asset_key(event)
        assets[asset_key].add(str(event["asset_type"]))
        source_key = str(event.get("source", ""))
        observed_sources[asset_key].add(source_key)
        if event["asset_type"] == COLLECTION_SCOPE:
            gap_sources.add(source_key)
        for safeguard_id in event.get("safeguard_ids", []):
            if safeguard_id not in definitions:
                raise ValueError("evidence references an unknown safeguard")
            bound[safeguard_id][asset_key].append(event)
            bound_sources[safeguard_id].add(source_key)
    # Index the observed population once. Avoid a safeguards x events scan.
    type_counts = Counter(next(iter(types)) for types in assets.values() if len(types) == 1)
    global_ambiguous_count = sum(len(types) != 1 for types in assets.values())
    results = []
    asset_results = []
    # Per-asset states with their evidence sources, so a provider benchmark is
    # assessed only from its own provider's evidence.
    asset_states: dict[str, list[tuple[frozenset[str], str]]] = defaultdict(list)
    incomplete: set[str] = set()
    incomplete_sources: dict[str, set[str]] = defaultdict(set)
    for safeguard_id, definition in definitions.items():
        eligible_types = set(definition.get("asset_types") or [])
        eligible_count = sum(type_counts[t] for t in eligible_types)
        ambiguous_count = sum(len(types) != 1 and bool(types & eligible_types) for types in assets.values())
        for asset_key, types in assets.items():
            if types & eligible_types and (len(types) != 1 or asset_key not in bound[safeguard_id]):
                incomplete_sources[safeguard_id].update(observed_sources[asset_key])
        states = []
        assessed = 0
        invalid = 0
        for asset_key, rows in sorted(bound.get(safeguard_id, {}).items()):
            source_tenant_id, asset_id = asset_key
            reasons = []
            types = assets[asset_key]
            if not binding_applies(types, eligible_types):
                status = ControlVerdict.NOT_EVALUATED.value
                reasons.append(INVALID_ASSET_TYPE_REASON)
                invalid += 1
            else:
                assessed += 1
                stale = current_evidence_is_stale(
                    [freshness[(str(row.get("tenant_id", "")), str(row["event_id"]))] for row in rows],
                    required_types=definition.get("required_evidence_types"),
                )
                verdict = evaluate_evidence_verdict(safeguard_id, rows, definition["evaluation_rule"], stale=stale)
                status = verdict.status
                reasons = list(verdict.reasons)
            states.append(status)
            asset_states[safeguard_id].append((frozenset(str(row.get("source", "")) for row in rows), status))
            asset_results.append(
                {
                    "safeguard_id": safeguard_id,
                    "asset_id": asset_id,
                    "source_tenant_id": source_tenant_id,
                    "status": status,
                    "event_ids": sorted({str(row["event_id"]) for row in rows}),
                    "evidence_hashes": sorted({str(row["raw_sha256"]) for row in rows}),
                    "reasons": reasons,
                }
            )
        missing = max(0, eligible_count - assessed)
        if missing or ambiguous_count or invalid:
            incomplete.add(safeguard_id)
        if safeguard_id in incomplete or bound_sources[safeguard_id] & gap_sources:
            states.append(ControlVerdict.NOT_EVALUATED.value)
        results.append(
            {
                "safeguard_id": safeguard_id,
                "title": definition["title"],
                "status": _combine(states),
                "applicable_asset_count": eligible_count,
                "assessed_asset_count": assessed,
                "unassessed_asset_count": missing,
                "invalid_binding_count": invalid,
            }
        )
    by_id = {row["safeguard_id"]: row["status"] for row in results}
    scopes = {
        framework_id: frozenset(sources)
        for framework_id, sources in (
            framework_provider_sources() if provider_sources is None else provider_sources
        ).items()
    }

    def provider_status(safeguard_id: str, sources: frozenset[str]) -> str:
        states = [status for asset_sources, status in asset_states[safeguard_id] if asset_sources & sources]
        if not states:
            return ControlVerdict.NOT_EVALUATED.value
        gaps = bound_sources[safeguard_id] & gap_sources
        if incomplete_sources[safeguard_id] & sources or gaps & sources:
            states.append(ControlVerdict.NOT_EVALUATED.value)
        return _combine(states)

    mappings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    contextual: dict[str, list[JsonObject]] = defaultdict(list)
    for safeguard_id, definition in definitions.items():
        for member in definition["satisfies"]:
            state = effective_review_state(member)
            if state != "rejected" and not contributes_to_coverage(member):
                contextual[str(member["control_id"])].append(
                    {"safeguard_id": safeguard_id, "role": member.get("role"), "review_state": state}
                )
            elif state != "rejected":
                mappings[str(member["control_id"])].append((safeguard_id, state))
    requirements = []
    for control_id, control in sorted(controls.items()):
        links = mappings.get(control_id, [])
        reviewed = [sid for sid, state in links if state in ATTESTABLE_STATES]
        pending = sum(state not in ATTESTABLE_STATES for _, state in links)
        scope = scopes.get(str(control.get("framework_id")))
        if scope is None:
            statuses = [by_id[sid] for sid in reviewed]
        else:
            statuses = [provider_status(sid, scope) for sid in reviewed]
        required = control.get("required_evidence_types") or []
        if reviewed and required:
            requirement_rows = [
                freshness[(str(row.get("tenant_id", "")), str(row["event_id"]))]
                for sid in reviewed
                for asset_rows in bound.get(sid, {}).values()
                for row in asset_rows
                if scope is None or str(row.get("source", "")) in scope
            ]
            if current_evidence_is_stale(requirement_rows, required_types=required):
                statuses.append(ControlVerdict.STALE.value)
        if pending or not payload.get("review_log_verified", False):
            statuses.append(ControlVerdict.NOT_EVALUATED.value)
        requirements.append(
            {
                "control_id": control_id,
                "framework_id": control.get("framework_id"),
                "status": _combine(statuses) if links else "unmapped",
                "reviewed_safeguard_ids": sorted(reviewed),
                "pending_mapping_count": pending,
                "contextual_mappings": contextual.get(control_id, []),
            }
        )
    return {
        "schema_version": "trustops.ccf_assessment.v1",
        "scope": "observed_assets",
        "population_completeness": "not_established",
        "asset_count": len(assets),
        "ambiguous_asset_count": global_ambiguous_count,
        "review_log_verified": payload.get("review_log_verified", False),
        "safeguards": results,
        "asset_results": asset_results,
        "requirements": requirements,
    }
