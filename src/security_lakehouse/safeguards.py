"""Common Control Framework: safeguards as the operated object.

The control catalog is framework-first, with each requirement carrying its own
``evidence_requirement``. Answering all of them means answering the same question
once per framework.

A safeguard inverts that. It is the thing an operator actually runs: one evidence
requirement, one evaluation rule, one owner. Framework requirements map *into* it,
many-to-one, and framework readiness is derived from safeguard posture rather than
computed alongside it.

The relationship is many-to-many in both directions, and deliberately so:

* one safeguard satisfies many requirements across frameworks — the point of a CCF
* one requirement may need several safeguards — SOC2 CC7.2 wants both detection
  and audit logging, so it is met only when *both* pass

That second case is why :func:`requirement_status` requires every mapped safeguard
to pass. Treating "any" as sufficient would let a passing logging safeguard report
a monitoring requirement as met.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from security_lakehouse.catalog import ROOT, load_control_catalog, load_framework_registry
from security_lakehouse.jsontypes import JsonObject
from security_lakehouse.policy import validate_rule

DEFAULT_SAFEGUARDS = ROOT / "controls" / "safeguards.json"

SCHEMA = "trustops.safeguards.v1"
IMPLEMENTATION_ROLES = frozenset({"primary", "equivalent"})
VALID_ROLES = IMPLEMENTATION_ROLES | {"supporting", "inherited"}
VALID_REVIEW_STATES = {"reviewed", "proposed"}

# Effective review state of one safeguard->requirement mapping for one tenant.
# The shipped ``review_status`` is the maintainer's call; an org decision from
# the tenant's review log (see :mod:`security_lakehouse.mapping_review`) is
# layered on top and never written back to ``controls/safeguards.json``.
REVIEW_STATE_LABELS = {
    "maintainer_reviewed": "maintainer-reviewed",
    "org_reviewed": "org-reviewed",
    "proposed": "proposed",
    "needs_changes": "needs changes",
    "rejected": "rejected",
}
# One-line meaning of each state; the console glossary (console-copy.ts) and
# the CLI help repeat these verbatim, and a test pins them together.
REVIEW_STATE_DEFINITIONS = {
    "maintainer_reviewed": "Confirmed by the catalog maintainers and shipped as reviewed.",
    "org_reviewed": "Approved by a reviewer in your organization, with a rationale.",
    "proposed": "Suggested mapping that no one has reviewed; not attestable.",
    "needs_changes": "Sent back by your organization; stays in the review queue.",
    "rejected": "Rejected by your organization; excluded from coverage.",
}
ATTESTABLE_STATES = frozenset({"maintainer_reviewed", "org_reviewed"})
# Who stands behind an attestable mapping. A maintainer review is either bound
# to a decision receipt under controls/reviews/ or predates receipts and names
# no reviewer; the legacy record lists what is known about the latter.
LEGACY_REVIEW_RECORD = "controls/reviews/legacy-unattributed.json"
REVIEW_PROVENANCE_LABELS = {
    "maintainer_receipt": "maintainer receipt",
    "legacy_unattributed": "legacy, no reviewer recorded",
    "org_decision": "org decision",
}
PENDING_STATES = frozenset({"proposed", "needs_changes"})

# These labels describe the operated CCF safeguard families, not official
# framework names. Keep the ids stable so the CLI, API, and console can join on
# the same family even when a safeguard title changes.
DEFAULT_FAMILIES = ROOT / "controls" / "families.json"


def _families_payload(path: str | Path | None = None) -> JsonObject:
    payload: JsonObject = json.loads(Path(path or DEFAULT_FAMILIES).read_text(encoding="utf-8"))
    return payload


def load_ccf_families(path: str | Path | None = None) -> dict[str, JsonObject]:
    """Return the canonical CCF control families keyed by ``family_id``."""
    payload = _families_payload(path)
    problems = validate_ccf_taxonomy(payload)
    if problems:
        raise ValueError("invalid CCF taxonomy: " + "; ".join(problems))
    return {row["family_id"]: row for row in payload["families"]}


def load_ccf_categories(path: str | Path | None = None) -> list[JsonObject]:
    """Return the CCF categories in taxonomy order.

    A category groups control families for navigation and roll-up. Each family
    names exactly one category; see :func:`validate_ccf_taxonomy`.
    """
    payload = _families_payload(path)
    problems = validate_ccf_taxonomy(payload)
    if problems:
        raise ValueError("invalid CCF taxonomy: " + "; ".join(problems))
    return list(payload["categories"])


def validate_ccf_taxonomy(payload: Any) -> list[str]:
    """Return problems with the category -> family taxonomy; empty means consistent."""
    if not isinstance(payload, dict):
        return ["CCF taxonomy must be an object"]
    problems: list[str] = []
    for field in ("categories", "families"):
        if not isinstance(payload.get(field), list):
            problems.append(f"{field} must be a list")
    if problems:
        return problems

    seen: set[str] = set()
    for row in payload["categories"]:
        if not isinstance(row, dict):
            problems.append("each category must be an object")
            continue
        category_id = row.get("category_id")
        if not isinstance(category_id, str) or not category_id.strip():
            problems.append("a category is missing category_id (must be a non-empty string)")
            continue
        if category_id in seen:
            problems.append(f"duplicate category {category_id!r}")
        seen.add(category_id)

    seen_families: set[str] = set()
    used: set[str] = set()
    for family in payload["families"]:
        if not isinstance(family, dict):
            problems.append("each family must be an object")
            continue
        family_id = family.get("family_id")
        if not isinstance(family_id, str) or not family_id.strip():
            problems.append("a family is missing family_id (must be a non-empty string)")
        elif family_id in seen_families:
            problems.append(f"duplicate family {family_id!r}")
        else:
            seen_families.add(family_id)
        category = family.get("category")
        if not isinstance(category, str) or not category.strip():
            problems.append(f"family {family_id!r} is missing category (must be a non-empty string)")
        elif category not in seen:
            problems.append(f"family {family_id!r} names unknown category {category!r}")
        else:
            used.add(category)
    for category_id in sorted(seen - used):
        problems.append(f"category {category_id!r} has no families")
    return problems


def _validate_mapping_source(source: Any, *, context: str) -> list[str]:
    """Validate provenance for a published crosswalk mapping."""
    if not isinstance(source, dict):
        return [f"{context}: mapping_source must be an object"]

    problems: list[str] = []
    for field in ("name", "locator"):
        if not isinstance(source.get(field), str) or not source[field].strip():
            problems.append(f"{context}: mapping_source.{field} must be a non-empty string")

    url = source.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        problems.append(f"{context}: mapping_source.url must use https")

    digest = source.get("sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        problems.append(f"{context}: mapping_source.sha256 must be 64 lowercase hexadecimal characters")
    return problems


_LOAD_TIME_KEYS = ("inherited_review_valid", "current_control_version")


def load_safeguards(path: str | Path | None = None) -> JsonObject:
    """Return the raw safeguards payload."""
    payload = json.loads(Path(path or DEFAULT_SAFEGUARDS).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("safeguards"), list):
        raise ValueError("safeguards file must contain a `safeguards` list")
    catalog = load_control_catalog()
    for entry in payload["safeguards"]:
        for member in entry.get("satisfies", []):
            # Computed below from the catalog; a shipped value (including a
            # re-saved loaded payload) is never trusted, only recomputed.
            for runtime_key in _LOAD_TIME_KEYS:
                member.pop(runtime_key, None)
            if "control_version" in member:
                member["current_control_version"] = catalog.get(member["control_id"], {}).get("version", "1.0.0")
        _check_inherited_reviews(entry, catalog)
    return payload


def _check_inherited_reviews(entry: JsonObject, catalog: dict[str, Any]) -> None:
    """Invalidate inherited maintainer reviews when their cited chain is stale.

    Sources must exist in this safeguard and retain a current maintainer review.
    Do not annotate valid mappings: their existing org-decision fingerprints must
    remain stable. Invalid mappings can still receive their own explicit review.
    """
    members = entry.get("satisfies", [])
    by_id = {row.get("control_id"): row for row in members}
    counts = Counter(row.get("control_id") for row in members)
    for member in members:
        if "review_basis" not in member:
            continue
        current = member
        seen: set[str] = set()
        valid = True
        while True:
            control_id = current.get("control_id")
            if (
                control_id in seen
                or counts[control_id] != 1
                or control_id not in catalog
                or current.get("review_status", "proposed") != "reviewed"
                or current.get("control_version")
                != current.get("current_control_version", current.get("control_version"))
            ):
                valid = False
                break
            seen.add(control_id)
            if "review_basis" not in current:
                break
            basis = current["review_basis"]
            source = basis.get("inherited_from") if isinstance(basis, dict) else None
            if not isinstance(source, str) or source not in by_id:
                valid = False
                break
            current = by_id[source]
        if not valid:
            member["inherited_review_valid"] = False


def validate_safeguards(payload: JsonObject, *, catalog: dict[str, Any] | None = None) -> list[str]:
    """Return a list of problems; empty means the CCF is internally consistent.

    Returns rather than raises so a caller can report every problem at once —
    a curation pass wants the whole list, not the first failure.
    """
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append(f"schema must be {SCHEMA!r}, got {payload.get('schema')!r}")

    controls = catalog if catalog is not None else load_control_catalog()
    known = set(controls)
    taxonomy = _families_payload()
    taxonomy_problems = validate_ccf_taxonomy(taxonomy)
    if taxonomy_problems:
        return [*problems, *taxonomy_problems]
    families = {row["family_id"]: row for row in taxonomy["families"]}
    seen_ids: set[str] = set()

    entries = payload.get("safeguards")
    if not isinstance(entries, list):
        return [*problems, "safeguards must be a list"]
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append("each safeguard must be an object")
            continue
        sid = entry.get("safeguard_id")
        if not isinstance(sid, str) or not sid.strip():
            problems.append("a safeguard is missing safeguard_id")
            continue
        if sid in seen_ids:
            problems.append(f"{sid}: duplicate safeguard_id")
        seen_ids.add(sid)
        if not isinstance(entry.get("risk_domain"), str) or entry.get("risk_domain") not in families:
            problems.append(f"{sid}: unknown CCF family {entry.get('risk_domain')!r}")

        if not isinstance(entry.get("asset_types"), list) or not entry.get("asset_types"):
            problems.append(f"{sid}: missing asset_types — a safeguard must say what it applies to")

        for field in ("asset_types", "required_evidence_types"):
            values = entry.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                problems.append(f"{sid}: {field} must be a list of nonempty identifiers")
            elif len(set(values)) != len(values):
                problems.append(f"{sid}: duplicate {field}")
        problems.extend(f"{sid}: {error}" for error in validate_rule(entry.get("evaluation_rule")))
        for field in ("title", "risk_domain", "objective", "evidence_requirement", "evaluation_rule", "owner"):
            if not entry.get(field):
                problems.append(f"{sid}: missing {field}")

        if "mapping_source" in entry:
            problems.extend(_validate_mapping_source(entry["mapping_source"], context=str(sid)))

        satisfies = entry.get("satisfies")
        if not isinstance(satisfies, list) or not satisfies:
            problems.append(f"{sid}: must satisfy at least one framework requirement")
            continue

        primaries = [m for m in satisfies if isinstance(m, dict) and m.get("role") == "primary"]
        if len(primaries) != 1:
            problems.append(f"{sid}: expected exactly one primary requirement, found {len(primaries)}")

        seen_members = set()
        for member in satisfies:
            if not isinstance(member, dict):
                problems.append(f"{sid}: mapping must be an object")
                continue
            control_id = member.get("control_id")
            if not isinstance(control_id, str) or not control_id.strip():
                problems.append(f"{sid}: mapping control_id must be a nonempty identifier")
                continue
            if control_id in seen_members:
                problems.append(f"{sid}: duplicate mapping to {control_id!r}")
            seen_members.add(control_id)
            if control_id in controls and member.get("framework_id") != controls[control_id].get("framework_id"):
                problems.append(f"{sid}: framework_id disagrees with {control_id!r}")
            for field in ("review_status", "control_version"):
                if not isinstance(member.get(field), str) or not member[field].strip():
                    problems.append(f"{sid}: {control_id!r} requires explicit {field}")
            if control_id not in known:
                problems.append(f"{sid}: unknown control_id {control_id!r}")
            role = member.get("role", "equivalent")
            if not isinstance(role, str) or role not in VALID_ROLES:
                problems.append(f"{sid}: invalid role {role!r} on {control_id!r}")
            review = member.get("review_status", "proposed")
            if not isinstance(review, str) or review not in VALID_REVIEW_STATES:
                problems.append(f"{sid}: invalid review_status {review!r} on {control_id!r}")
            if "effective_review_state" in member:
                # Only the org overlay may annotate this at runtime; a shipped value would bypass review.
                problems.append(f"{sid}: {control_id!r} must not ship an effective_review_state annotation")
            if review == "reviewed":
                for field in ("reviewed_by", "maintainer_review_ref"):
                    if not isinstance(member.get(field), str) or not member[field].strip():
                        problems.append(f"{sid}: reviewed mapping {control_id!r} requires {field}")
            if "mapping_source" in member:
                problems.extend(_validate_mapping_source(member["mapping_source"], context=f"{sid}/{control_id}"))

    return problems


def effective_review_state(member: JsonObject, decision: str | None = None) -> str:
    """Return a mapping's effective review state. Every "is it reviewed" check calls this.

    Coverage counts, the review queue, OSCAL, and the snapshot attestation all
    read it. ``decision`` is the tenant's latest org decision for the mapping
    (``approve`` / ``reject`` / ``needs_changes``) or ``None``; with ``None`` a
    member already annotated by the org overlay keeps its annotated state.

    * no org decision: explicit shipped ``reviewed`` is
      ``maintainer_reviewed``; anything else is ``proposed``
    * ``approve``: ``org_reviewed`` for a proposed mapping; a maintainer-reviewed
      mapping stays ``maintainer_reviewed`` so the two are never double counted
    * ``needs_changes``: not attestable for this tenant, still evaluatable
    * ``reject``: removed from this tenant's evaluated coverage
    """
    if decision is None:
        annotated = member.get("effective_review_state")
        if isinstance(annotated, str) and annotated in REVIEW_STATE_LABELS:
            return annotated
    if decision == "reject":
        return "rejected"
    if decision == "needs_changes":
        return "needs_changes"
    version_matches = member.get("control_version") == member.get(
        "current_control_version", member.get("control_version")
    )
    if (
        member.get("review_status", "proposed") == "reviewed"
        and version_matches
        and member.get("inherited_review_valid", True)
    ):
        return "maintainer_reviewed"
    if decision == "approve":
        return "org_reviewed"
    return "proposed"


def review_provenance(member: JsonObject) -> str | None:
    """Return who stands behind an attestable mapping, or ``None`` when it is not attestable."""
    state = effective_review_state(member)
    if state == "org_reviewed":
        return "org_decision"
    if state != "maintainer_reviewed":
        return None
    ref = member.get("maintainer_review_ref")
    return "maintainer_receipt" if isinstance(ref, str) and ref else "legacy_unattributed"


def contributes_to_coverage(member: JsonObject) -> bool:
    """Only implementation relationships can establish requirement coverage.

    Supporting evidence and inherited responsibility are context, even when the
    relationship is reviewed. They require separate assessment and never imply
    that this safeguard implements the requirement. Missing roles retain the
    legacy equivalent contract; unknown roles fail closed.
    """
    return member.get("role", "equivalent") in IMPLEMENTATION_ROLES


def unambiguous_safeguards(payload: JsonObject) -> list[JsonObject]:
    """Project only uniquely identified definitions and mapping targets.

    A repeated safeguard ID makes all definitions with that ID ambiguous; a
    repeated control ID within one safeguard makes every link to that target
    ambiguous, even if the roles or review states differ. Distinct safeguards
    may still cover the same requirement. Keep raw data intact for validation
    and repair; never resolve a conflict by selecting the most favorable row.
    """
    entries = payload.get("safeguards", [])
    ids = Counter(entry.get("safeguard_id") for entry in entries)
    result = []
    for entry in entries:
        if ids[entry.get("safeguard_id")] != 1:
            continue
        members = entry.get("satisfies", [])
        targets = Counter(member.get("control_id") for member in members)
        result.append({**entry, "satisfies": [m for m in members if targets[m.get("control_id")] == 1]})
    return result


def safeguards_by_requirement(
    payload: JsonObject | None = None, *, reviewed_only: bool = False
) -> dict[str, list[str]]:
    """Map each framework control_id to the safeguard ids that satisfy it.

    ``reviewed_only`` drops mappings nobody has confirmed (maintainer or org).
    Attestation should use it; discovery and curation queues should not.
    Org-rejected mappings are never returned.
    """
    data = payload or load_safeguards()
    out: dict[str, list[str]] = {}
    for entry in unambiguous_safeguards(data):
        for member in entry.get("satisfies", []):
            state = effective_review_state(member)
            if state == "rejected" or not contributes_to_coverage(member):
                continue
            if reviewed_only and state not in ATTESTABLE_STATES:
                continue
            out.setdefault(str(member.get("control_id")), []).append(str(entry["safeguard_id"]))
    return out


def mapping_review_queue(
    payload: JsonObject | None = None,
    *,
    framework_id: str | None = None,
    risk_domain: str | None = None,
) -> list[JsonObject]:
    """Proposed (unreviewed) safeguard→requirement mappings awaiting expert sign-off.

    Read-only curation aid — it never promotes a mapping (that equivalence call is
    the reviewer's). Each item carries the ``reviewed_anchors`` already confirmed on
    the same safeguard, so a reviewer can judge a proposed equivalence against
    mappings they already trust and accept/reject fast. Source-backed items carry
    the published crosswalk provenance and exact locator. This is the backlog
    whose review grows the *attestable* coverage number.
    """
    items: list[JsonObject] = []
    for item in mapping_review_items(payload, framework_id=framework_id, risk_domain=risk_domain):
        if item["review_state"] not in PENDING_STATES:
            continue
        if item["mapping_source"] is None:
            del item["mapping_source"]
        items.append(item)
    return items


def member_mapping_source(entry: JsonObject, member: JsonObject) -> JsonObject | None:
    """Return the published citation backing one mapping, if any.

    A member proposed by title theme has no citation of its own and must not
    inherit the safeguard's crosswalk citation, which covers other frameworks'
    members.
    """
    if "mapping_source" in member:
        source = member.get("mapping_source")
    elif member.get("mapping_basis") == "title_theme":
        source = None
    else:
        source = entry.get("mapping_source")
    return source if isinstance(source, dict) else None


def mapping_review_items(
    payload: JsonObject | None = None,
    *,
    framework_id: str | None = None,
    risk_domain: str | None = None,
) -> list[JsonObject]:
    """Every safeguard->requirement mapping with its effective review state.

    ``reviewed_anchors`` lists the other requirements on the same safeguard that
    are already confirmed, so a reviewer can judge a proposed equivalence
    against mappings they already trust.
    """
    data = payload or load_safeguards()
    items: list[JsonObject] = []
    for entry in data["safeguards"]:
        if risk_domain and str(entry.get("risk_domain")) != risk_domain:
            continue
        anchors = [
            str(member.get("control_id"))
            for member in entry.get("satisfies", [])
            if contributes_to_coverage(member) and effective_review_state(member) in ATTESTABLE_STATES
        ]
        for member in entry.get("satisfies", []):
            if framework_id and str(member.get("framework_id")) != framework_id:
                continue
            control_id = str(member.get("control_id"))
            state = effective_review_state(member)
            items.append(
                {
                    "safeguard_id": str(entry["safeguard_id"]),
                    "safeguard_title": entry.get("title"),
                    "risk_domain": entry.get("risk_domain"),
                    "control_id": control_id,
                    "framework_id": str(member.get("framework_id")),
                    "role": member.get("role", "equivalent"),
                    "contributes_to_coverage": contributes_to_coverage(member),
                    "shipped_review_status": member.get("review_status", "proposed"),
                    "review_state": state,
                    "review_label": REVIEW_STATE_LABELS[state],
                    "review_provenance": review_provenance(member),
                    "mapping_basis": member.get("mapping_basis"),
                    "reviewed_anchors": [anchor for anchor in anchors if anchor != control_id],
                    "mapping_source": member_mapping_source(entry, member),
                }
            )
    return items


def mapping_review_report(
    payload: JsonObject | None = None,
    *,
    framework_id: str | None = None,
    risk_domain: str | None = None,
) -> JsonObject:
    """Summarize the review backlog across frameworks and normalized domains."""
    items = mapping_review_queue(payload, framework_id=framework_id, risk_domain=risk_domain)
    sourced = [item for item in items if item.get("mapping_source")]
    unsourced = [item for item in items if not item.get("mapping_source")]

    def count_by(rows: list[JsonObject], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in rows:
            value = str(item[field])
            counts[value] = counts.get(value, 0) + 1
        return dict(sorted(counts.items()))

    return {
        "proposed_mapping_count": len(items),
        "source_backed_mapping_count": len(sourced),
        "unsourced_mapping_count": len(unsourced),
        "by_framework": count_by(items, "framework_id"),
        "by_risk_domain": count_by(items, "risk_domain"),
        "source_backed_by_framework": count_by(sourced, "framework_id"),
        "unsourced_by_framework": count_by(unsourced, "framework_id"),
        "items": items,
    }


def requirement_status(control_id: str, safeguard_results: dict[str, str], payload: JsonObject | None = None) -> str:
    """Derive one framework requirement's status from its safeguards.

    ``unmapped`` when no safeguard claims it — distinct from ``fail``, because
    "we have not modelled this yet" and "we tested it and it failed" are different
    answers to an auditor.
    """
    mapped = safeguards_by_requirement(payload, reviewed_only=True).get(control_id, [])
    if not mapped:
        return "unmapped"
    statuses = {safeguard_results.get(sid, "unknown") for sid in mapped}
    if "fail" in statuses:
        return "fail"
    if statuses == {"pass"}:
        return "pass"
    return "unknown"


def safeguards_for_asset_type(asset_type: str, payload: JsonObject | None = None) -> list[str]:
    """Safeguards that apply to an asset type.

    The catalog already records ``asset_types`` per requirement, and evaluation
    targets resources rather than frameworks — so a safeguard has to carry the
    union of what its requirements apply to, or the operated object cannot be
    pointed at anything.
    """
    data = payload or load_safeguards()
    return sorted(
        str(entry["safeguard_id"]) for entry in data["safeguards"] if asset_type in (entry.get("asset_types") or [])
    )


def _mapping_ledger() -> dict[str, Any]:
    return {
        "safeguard_count": 0,
        "frameworks": set(),
        "control_ids": set(),
        "mapping_count": 0,
        "contextual_mapping_count": 0,
        "states": dict.fromkeys(REVIEW_STATE_LABELS, 0),
    }


def _add_safeguard(ledger: dict[str, Any], entry: JsonObject) -> None:
    ledger["safeguard_count"] += 1
    for member in entry.get("satisfies", []):
        state = effective_review_state(member)
        ledger["mapping_count"] += 1
        if not contributes_to_coverage(member):
            ledger["contextual_mapping_count"] += 1
            continue
        ledger["states"][state] += 1
        if state == "rejected":
            continue
        ledger["control_ids"].add(str(member.get("control_id")))
        framework_id = member.get("framework_id")
        if framework_id:
            ledger["frameworks"].add(str(framework_id))


def _ledger_counts(ledger: dict[str, Any]) -> JsonObject:
    states = ledger["states"]
    reviewed = int(states["maintainer_reviewed"] + states["org_reviewed"])
    proposed = int(states["proposed"] + states["needs_changes"])
    if not reviewed:
        state = "proposed_only"
    elif proposed:
        state = "partially_reviewed"
    else:
        state = "reviewed"
    return {
        "safeguard_count": ledger["safeguard_count"],
        "framework_count": len(ledger["frameworks"]),
        "frameworks": sorted(ledger["frameworks"]),
        "mapped_requirement_count": len(ledger["control_ids"]),
        "mapping_count": ledger["mapping_count"],
        "contextual_mapping_count": ledger["contextual_mapping_count"],
        # reviewed = maintainer + org; the split is reported alongside so
        # the two kinds of confirmation are never blended.
        "reviewed_mapping_count": reviewed,
        "maintainer_reviewed_mapping_count": states["maintainer_reviewed"],
        "org_reviewed_mapping_count": states["org_reviewed"],
        "proposed_mapping_count": proposed,
        "needs_changes_mapping_count": states["needs_changes"],
        "rejected_mapping_count": states["rejected"],
        "state": state,
    }


def coverage_by_family(payload: JsonObject | None = None) -> list[JsonObject]:
    """Report CCF coverage by operated safeguard family.

    A family is the safeguard's ``risk_domain``. This is deliberately separate
    from framework coverage: a family can touch several frameworks, and a
    proposed mapping makes a requirement evaluatable but not attestable. The
    ledger preserves both counts so the console can show breadth without
    overstating assurance.
    """
    data = payload or load_safeguards()
    families = load_ccf_families()
    category_labels = {str(row["category_id"]): str(row["label"]) for row in load_ccf_categories()}
    grouped: dict[str, dict[str, Any]] = {}
    for entry in unambiguous_safeguards(data):
        family_id = str(entry.get("risk_domain") or "uncategorized")
        _add_safeguard(grouped.setdefault(family_id, _mapping_ledger()), entry)

    rows: list[JsonObject] = []
    for family_id, ledger in sorted(grouped.items()):
        definition = families.get(family_id, {})
        category_id = str(definition.get("category") or "")
        rows.append(
            {
                "family_id": family_id,
                "label": definition.get("label", family_id.replace("-", " ").title()),
                "description": definition.get("description", ""),
                "category_id": category_id,
                "category_label": category_labels.get(category_id, ""),
                "nist_800_53_families": list(definition.get("nist_800_53_families", [])),
                "cis_controls": list(definition.get("cis_controls", [])),
                **_ledger_counts(ledger),
            }
        )
    return rows


def coverage_by_category(payload: JsonObject | None = None) -> list[JsonObject]:
    """Roll the family ledger up to CCF categories, in taxonomy order.

    Requirement and framework counts are distinct across the category, not a
    sum over its families, because two families can map the same requirement.
    """
    data = payload or load_safeguards()
    families = load_ccf_families()
    ledgers: dict[str, dict[str, Any]] = {}
    for entry in unambiguous_safeguards(data):
        category_id = str(families.get(str(entry.get("risk_domain")), {}).get("category") or "")
        _add_safeguard(ledgers.setdefault(category_id, _mapping_ledger()), entry)

    rows: list[JsonObject] = []
    for category in load_ccf_categories():
        category_id = str(category["category_id"])
        family_ids = [family_id for family_id, row in families.items() if row.get("category") == category_id]
        rows.append(
            {
                "category_id": category_id,
                "label": category["label"],
                "description": category.get("description", ""),
                "family_ids": family_ids,
                "family_count": len(family_ids),
                **_ledger_counts(ledgers.get(category_id, _mapping_ledger())),
            }
        )
    return rows


def mapping_target_framework(member: JsonObject, catalog: dict[str, Any]) -> str | None:
    """Resolve a mapping within the catalog, rejecting conflicting framework IDs.

    Legacy rows without a framework inherit the catalog identity. Coverage and
    exports must use the same target check before granting mapping credit.
    """
    control_id = member.get("control_id")
    if not isinstance(control_id, str) or control_id not in catalog:
        return None
    framework = str(catalog[control_id].get("framework_id") or "unknown")
    return framework if member.get("framework_id", framework) == framework else None


def is_source_native_mapping(entry: JsonObject, member: JsonObject, framework: str, registry: dict[str, Any]) -> bool:
    """True when a safeguard is a self-map of its only requirement.

    The safeguard maps exactly one requirement, and that mapping cites the same
    pinned source bytes (SHA-256) the framework registry records for the target
    framework. Such a contract is derived from the requirement's own text, so its
    review confirms extraction fidelity, not a cross-framework judgement.
    """
    if len(entry.get("satisfies") or []) != 1:
        return False
    source = member.get("mapping_source")
    if not isinstance(source, dict):
        return False
    pinned = (registry.get(framework) or {}).get("source_sha256")
    return bool(pinned) and source.get("sha256") == pinned


def framework_mapping_coverage(
    payload: JsonObject | None = None,
    *,
    catalog: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> JsonObject:
    """Shared catalog-denominated mapping ledger, separate from operating verdicts.

    Requirement counts are disjoint: ``maintainer_reviewed`` requirements have at
    least one maintainer-reviewed mapping; ``org_reviewed`` requirements are
    attestable only through an org approval; ``proposed`` are evaluatable but not
    attestable. ``*_mappings`` counts are per safeguard->requirement link.
    ``rejected_requirements`` lost all evaluated coverage to org rejections.
    Only catalog targets with a matching framework contribute to this ledger;
    legacy mappings without a framework ID inherit the catalog identity.
    Reviewed requirements are further split into ``source_native_reviewed``
    (reviewed only through self-maps, see :func:`is_source_native_mapping`) and
    ``crosswalk_reviewed`` (at least one reviewed mapping from a reusable or
    cross-framework safeguard); the two always sum to ``reviewed``.
    """
    controls = catalog if catalog is not None else load_control_catalog()
    sources = registry if registry is not None else load_framework_registry()
    data = payload or load_safeguards()
    mapped: set[str] = set()
    states_by_control: dict[str, set[str]] = {}
    mapping_states: dict[str, dict[str, int]] = {}
    contextual_by_framework: dict[str, int] = {}
    provenance_by_control: dict[str, set[str]] = {}
    legacy_by_framework: dict[str, int] = {}
    reviewed_kinds: dict[str, set[str]] = {}
    self_map_mappings: dict[str, int] = {}
    reviewer_counts: Counter[str] = Counter()
    receipt_counts: Counter[str] = Counter()
    reviewer_buckets: Counter[str] = Counter()
    # Requirements with at least one attestable mapping from a safeguard that
    # declares ``required_evidence_types``; the evaluator returns
    # ``not_evaluated`` for every other reviewed mapping (ccf_evaluation).
    contracted_reviewed: set[str] = set()
    safeguards_without_contract = 0
    for entry in unambiguous_safeguards(data):
        has_contract = bool(entry.get("required_evidence_types"))
        if not has_contract:
            safeguards_without_contract += 1
        for member in entry.get("satisfies", []):
            framework = mapping_target_framework(member, controls)
            if framework is None:
                continue
            control_id = str(member["control_id"])
            if not contributes_to_coverage(member):
                contextual_by_framework[framework] = contextual_by_framework.get(framework, 0) + 1
                continue
            state = effective_review_state(member)
            if state != "rejected":
                mapped.add(control_id)
            states_by_control.setdefault(control_id, set()).add(state)
            counts = mapping_states.setdefault(framework, dict.fromkeys(REVIEW_STATE_LABELS, 0))
            counts[state] += 1
            provenance = review_provenance(member)
            if provenance is not None:
                provenance_by_control.setdefault(control_id, set()).add(provenance)
            if provenance == "legacy_unattributed":
                legacy_by_framework[framework] = legacy_by_framework.get(framework, 0) + 1
            if state in ATTESTABLE_STATES:
                if has_contract:
                    contracted_reviewed.add(control_id)
                names: set[str] = set()
                if state == "maintainer_reviewed":
                    name = member.get("reviewed_by")
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())
                    receipt = member.get("maintainer_review_ref")
                    if isinstance(receipt, str) and receipt:
                        receipt_counts[receipt] += 1
                org_review = member.get("org_review") or {}
                if data.get("review_log_verified", True) and org_review.get("decision") == "approve":
                    name = org_review.get("reviewer")
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())
                reviewer_counts.update(names)
                reviewer_buckets[
                    "unattributed" if not names else "single_reviewer" if len(names) == 1 else "multiple_reviewers"
                ] += 1
                native = is_source_native_mapping(entry, member, framework, sources)
                reviewed_kinds.setdefault(control_id, set()).add("source_native" if native else "crosswalk")
                if native:
                    self_map_mappings[framework] = self_map_mappings.get(framework, 0) + 1

    def requirement_bucket(control_id: str) -> str | None:
        states = states_by_control.get(control_id, set())
        if not states:
            return None
        if "maintainer_reviewed" in states:
            return "maintainer_reviewed"
        if "org_reviewed" in states:
            return "org_reviewed"
        if states & PENDING_STATES:
            return "proposed"
        return "rejected"

    per_framework: dict[str, dict[str, int]] = {}
    buckets: dict[str, int] = dict.fromkeys(("maintainer_reviewed", "org_reviewed", "proposed", "rejected"), 0)
    for control_id, control in controls.items():
        framework = str(control.get("framework_id") or "unknown")
        row = per_framework.setdefault(
            framework,
            {
                "controls": 0,
                "covered": 0,
                "maintainer_reviewed": 0,
                "org_reviewed": 0,
                "legacy_only_reviewed": 0,
                "reviewed_without_contract": 0,
                "rejected_requirements": 0,
                "source_native_reviewed": 0,
                "crosswalk_reviewed": 0,
            },
        )
        row["controls"] += 1
        if control_id in mapped:
            row["covered"] += 1
        bucket = requirement_bucket(control_id)
        if bucket is not None:
            buckets[bucket] += 1
        if bucket in {"maintainer_reviewed", "org_reviewed"}:
            row[bucket] += 1
            if provenance_by_control.get(control_id) == {"legacy_unattributed"}:
                row["legacy_only_reviewed"] += 1
            if control_id not in contracted_reviewed:
                row["reviewed_without_contract"] += 1
            native_only = "crosswalk" not in reviewed_kinds.get(control_id, set())
            row["source_native_reviewed" if native_only else "crosswalk_reviewed"] += 1
        elif bucket == "rejected":
            row["rejected_requirements"] += 1
    for framework, row in per_framework.items():
        counts = mapping_states.get(framework, dict.fromkeys(REVIEW_STATE_LABELS, 0))
        for state in REVIEW_STATE_LABELS:
            row[f"{state}_mappings"] = counts[state]
        row["contextual_mappings"] = contextual_by_framework.get(framework, 0)
        row["legacy_unattributed_mappings"] = legacy_by_framework.get(framework, 0)
        row["source_native_reviewed_mappings"] = self_map_mappings.get(framework, 0)
        row["reviewed"] = row["maintainer_reviewed"] + row["org_reviewed"]
        row["proposed"] = row["covered"] - row["reviewed"]
        row["uncovered"] = row["controls"] - row["covered"]

    total = len(controls)
    covered = sum(1 for cid in controls if cid in mapped)
    reviewed = buckets["maintainer_reviewed"] + buckets["org_reviewed"]
    all_states = {state: sum(counts[state] for counts in mapping_states.values()) for state in REVIEW_STATE_LABELS}
    legacy_only = sum(row["legacy_only_reviewed"] for row in per_framework.values())
    return {
        "safeguards": len(data["safeguards"]),
        "contextual_mappings": sum(contextual_by_framework.values()),
        "review_log_verified": bool(data.get("review_log_verified", True)),
        "controls": total,
        "covered": covered,
        # Split so unconfirmed curation is never reported as attested coverage,
        # and org confirmation is never blended into maintainer review.
        "reviewed": reviewed,
        "reviewer_provenance": {
            **{key: reviewer_buckets[key] for key in ("unattributed", "single_reviewer", "multiple_reviewers")},
            "by_reviewer": dict(sorted(reviewer_counts.items())),
            "by_receipt": dict(sorted(receipt_counts.items())),
            "independence": "not_established",
        },
        "maintainer_reviewed": buckets["maintainer_reviewed"],
        "org_reviewed": buckets["org_reviewed"],
        "proposed": covered - reviewed,
        "rejected_requirements": buckets["rejected"],
        # Reviewed requirements whose only attestable mappings predate decision
        # receipts and name no reviewer; still counted, reported so they are
        # never mistaken for receipt-backed review.
        "receipt_reviewed": reviewed - legacy_only,
        "legacy_only_reviewed": legacy_only,
        # Reviewed requirements whose every attestable mapping sits on a
        # safeguard with no evidence contract: reviewed, but not evaluable until
        # a maintainer re-review defines the contract.
        "reviewed_without_contract": sum(row["reviewed_without_contract"] for row in per_framework.values()),
        "safeguards_without_contract": safeguards_without_contract,
        "legacy_unattributed_mappings": sum(legacy_by_framework.values()),
        "source_native_reviewed": sum(row["source_native_reviewed"] for row in per_framework.values()),
        "crosswalk_reviewed": sum(row["crosswalk_reviewed"] for row in per_framework.values()),
        "maintainer_reviewed_mappings": all_states["maintainer_reviewed"],
        "org_reviewed_mappings": all_states["org_reviewed"],
        "needs_changes_mappings": all_states["needs_changes"],
        "rejected_mappings": all_states["rejected"],
        "reviewed_pct": round(100.0 * reviewed / total, 1) if total else 0.0,
        "uncovered": total - covered,
        "coverage_pct": round(100.0 * covered / total, 1) if total else 0.0,
        "frameworks": {
            name: {
                **row,
                "coverage_pct": round(100.0 * row["covered"] / row["controls"], 1) if row["controls"] else 0.0,
                "reviewed_pct": round(100.0 * row["reviewed"] / row["controls"], 1) if row["controls"] else 0.0,
                "crosswalk_reviewed_pct": round(100.0 * row["crosswalk_reviewed"] / row["controls"], 1)
                if row["controls"]
                else 0.0,
            }
            for name, row in sorted(per_framework.items())
        },
    }


def broadest_safeguards(payload: JsonObject | None = None, *, limit: int = 10) -> list[JsonObject]:
    """Safeguards that satisfy the most requirements, with the review depth behind each."""
    data = payload if payload is not None else load_safeguards()
    rows: list[JsonObject] = []
    for entry in data["safeguards"]:
        members = entry.get("satisfies", [])
        contributing = [m for m in members if contributes_to_coverage(m)]
        provenances = [review_provenance(m) for m in contributing]
        reviewed = sum(1 for p in provenances if p is not None)
        rows.append(
            {
                "safeguard_id": str(entry["safeguard_id"]),
                "title": entry.get("title"),
                "requirements": len(members),
                "frameworks": len({str(m.get("framework_id")) for m in members}),
                "reviewed": reviewed,
                "legacy_unattributed": provenances.count("legacy_unattributed"),
                "proposed": len(contributing) - reviewed,
                "contextual": len(members) - len(contributing),
            }
        )
    rows.sort(key=lambda row: (-int(row["requirements"]), str(row["safeguard_id"])))
    return rows[:limit]


def coverage_by_framework(payload: JsonObject | None = None, *, catalog: dict[str, Any] | None = None) -> JsonObject:
    """Framework mapping coverage with the existing family/category summaries."""
    data = payload if payload is not None else load_safeguards()
    return {
        **framework_mapping_coverage(data, catalog=catalog),
        "families": coverage_by_family(data),
        "categories": coverage_by_category(data),
    }
