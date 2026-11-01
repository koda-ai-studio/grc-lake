"""Stable semantic identities for safeguard definitions and review relationships."""

from typing import Any

from security_lakehouse.io import canonical_sha256

DEFINITION_VERSION = 1
REVIEW_BASIS_VERSION = 1
SEMANTIC_FIELDS = (
    "safeguard_id",
    "objective",
    "evidence_requirement",
    "evaluation_rule",
    "asset_types",
    "required_evidence_types",
    "frequency",
    "owner",
    "mapping_source",
)


def definition_digest(entry: dict[str, Any]) -> str:
    """Display titles and unrelated mapping additions do not change the operated rule."""
    definition = {key: entry.get(key) for key in SEMANTIC_FIELDS}
    for field in ("asset_types", "required_evidence_types"):
        definition[field] = sorted(set(definition[field] or []))
    return canonical_sha256({"version": DEFINITION_VERSION, "definition": definition})


def mapping_identity(safeguard_id: str, framework_id: str, control_id: str) -> str:
    return "mapping:" + canonical_sha256([safeguard_id, framework_id, control_id])


def review_basis(entry: dict[str, Any], member: dict[str, Any], control: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            "version": REVIEW_BASIS_VERSION,
            "safeguard": definition_digest(entry),
            "mapping": member,
            "requirement": control,
        }
    )


def evidence_contract_inventory(
    payload: dict[str, Any] | None = None, *, catalog: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Inventory safeguards that declare no ``required_evidence_types``.

    The evaluator returns ``not_evaluated`` for every binding to such a
    safeguard, so each reviewed mapping on it confirms the crosswalk without
    establishing evaluable coverage. This lists what a maintainer re-review has
    to define and which receipts that review would re-bind. It proposes no
    contracts and records no decisions.
    """
    from security_lakehouse.catalog import load_control_catalog
    from security_lakehouse.safeguards import (
        ATTESTABLE_STATES,
        contributes_to_coverage,
        effective_review_state,
        load_safeguards,
        mapping_target_framework,
        unambiguous_safeguards,
    )

    controls = catalog if catalog is not None else load_control_catalog()
    data = payload if payload is not None else load_safeguards()
    entries = unambiguous_safeguards(data)
    contracted: set[str] = set()
    for entry in entries:
        if not entry.get("required_evidence_types"):
            continue
        for member in entry.get("satisfies", []):
            if (
                contributes_to_coverage(member)
                and mapping_target_framework(member, controls) is not None
                and effective_review_state(member) in ATTESTABLE_STATES
            ):
                contracted.add(str(member["control_id"]))
    rows: list[dict[str, Any]] = []
    mapping_total = 0
    without_contract: set[str] = set()
    for entry in sorted(entries, key=lambda item: str(item["safeguard_id"])):
        if entry.get("required_evidence_types"):
            continue
        reviewed: dict[str, list[str]] = {}
        refs: set[str] = set()
        for member in entry.get("satisfies", []):
            framework = mapping_target_framework(member, controls)
            if (
                framework is None
                or not contributes_to_coverage(member)
                or effective_review_state(member) not in ATTESTABLE_STATES
            ):
                continue
            reviewed.setdefault(framework, []).append(str(member["control_id"]))
            ref = member.get("maintainer_review_ref")
            if isinstance(ref, str) and ref:
                refs.add(ref)
        stranded = sorted({cid for ids in reviewed.values() for cid in ids} - contracted)
        without_contract.update(stranded)
        mapping_total += sum(len(ids) for ids in reviewed.values())
        rows.append(
            {
                "safeguard_id": str(entry["safeguard_id"]),
                "title": entry.get("title"),
                "risk_domain": entry.get("risk_domain"),
                "asset_types": list(entry.get("asset_types") or []),
                "evidence_requirement": entry.get("evidence_requirement"),
                "evaluation_rule": entry.get("evaluation_rule"),
                "definition_digest": definition_digest(entry),
                "reviewed_mappings": {key: sorted(ids) for key, ids in sorted(reviewed.items())},
                "reviewed_requirements_without_contract": stranded,
                "maintainer_review_refs": sorted(refs),
            }
        )
    return {
        "schema": "trustops.evidence_contract_inventory.v1",
        "proposes_contracts": False,
        "summary": {
            "safeguards_without_contract": len(rows),
            "reviewed_requirements_without_contract": len(without_contract),
            "reviewed_mappings_without_contract": mapping_total,
        },
        "safeguards": rows,
    }
