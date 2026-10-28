"""Recorded alias assertions attach only to exact evidence in the selected generation."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from security_lakehouse.entity_history import graph_binding_snapshot
from security_lakehouse.entity_registry import build_entity_registry
from security_lakehouse.evidence_freshness import STALE_STATUSES


def add_entity_bindings(
    lake: Path,
    tenant: str,
    nodes: dict[str, dict[str, Any]],
    node: Callable[..., str],
    edge: Callable[..., None],
    check: Callable[[], None],
) -> None:
    revision = graph_binding_snapshot(lake, tenant, check)
    if revision is None:
        return
    registry = build_entity_registry(revision["evidence"], platform_tenant_id=tenant, bindings=revision["bindings"])
    entities = {item["id"]: item for item in registry["canonical_entities"]}
    for alias in registry["aliases"]:
        check()
        assertion = alias["assertion"]
        entity = entities[alias["canonical_entity_id"]]
        evidence_id = "evidence:" + assertion["evidence_sha256"]
        present = evidence_id in nodes
        # Unknown freshness is not current evidence, so it cannot anchor an identity link.
        stale = present and nodes[evidence_id].get("freshness_status") in STALE_STATUSES
        linked = present and not stale
        aid = node(
            "entity_alias",
            alias["id"],
            ("Alias for " if linked else "Missing evidence for " if not present else "Stale evidence for ")
            + entity["key"],
            source_account_id=assertion["source_account_id"],
            provider=assertion["source"],
            subtitle=assertion["asset_type"] + ": " + assertion["asset_id"],
            status="caller_asserted" if linked else "evidence_stale" if stale else "evidence_missing",
            basis="Caller-asserted alias; not authenticated approval or a compliance verdict",
            asserted_by=assertion["asserted_by"],
            asserted_at=assertion["asserted_at"],
            assertion_reason=assertion["reason"],
            evidence_sha256=assertion["evidence_sha256"],
            binding_revision=revision["revision"],
            binding_record_hash=revision["record_hash"],
            next_action="Review the recorded identity assertion and its exact source evidence",
        )
        if linked:
            cid = node(
                "canonical_entity",
                entity["id"],
                entity["key"],
                subtitle=entity["entity_type"],
                basis="Caller-asserted canonical identity; source records remain separate",
                status="caller_asserted",
            )
            edge(cid, aid, "has_alias_assertion", review_state="caller_asserted")
            edge(aid, evidence_id, "assertion_references_evidence", review_state="caller_asserted")
