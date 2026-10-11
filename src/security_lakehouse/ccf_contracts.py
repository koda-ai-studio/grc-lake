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
