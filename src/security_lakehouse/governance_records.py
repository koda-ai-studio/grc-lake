"""Versioned tenant scope and risk decisions, separate from assessment truth."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from security_lakehouse.ccf_contracts import definition_digest
from security_lakehouse.control_assurance import timestamp, verified_generation
from security_lakehouse.controls import load_control_map
from security_lakehouse.db.models import GovernanceDecision, GovernanceReview, SafeguardImplementation
from security_lakehouse.domain_identity import source_asset_key
from security_lakehouse.evidence_eligibility import evidence_available
from security_lakehouse.generations import generation_reader
from security_lakehouse.io import canonical_sha256, iter_jsonl, read_json
from security_lakehouse.programs import with_program_requirements
from security_lakehouse.safeguards import load_safeguards
from security_lakehouse.server_routes.schemas.base import StrictModel

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Narrative = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ScopedAsset(StrictModel):
    source_account_id: Identifier
    asset_id: Identifier


class Scope(StrictModel):
    safeguard_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    control_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    assets: list[ScopedAsset] = Field(default_factory=list, max_length=100)


class ImplementationRequest(StrictModel):
    safeguard_id: Identifier
    owner: Identifier
    system: Identifier
    cadence_days: int = Field(ge=1, le=366)
    scope: Scope
    evidence_event_ids: list[Identifier] = Field(min_length=1, max_length=100)
    supersedes_id: Identifier | None = None


class DecisionRequest(StrictModel):
    kind: Literal["risk_acceptance", "by_design", "not_applicable", "inherited", "compensating"]
    rationale: Narrative
    residual_risk: Narrative
    scope: Scope
    evidence_event_ids: list[Identifier] = Field(min_length=1, max_length=100)
    expires_at: Identifier
    risk_id: Identifier | None = None
    supersedes_id: Identifier | None = None


class ReviewRequest(StrictModel):
    decision: Literal["approve", "reject", "revoke"]
    rationale: Narrative
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RecordNotFound(ValueError):
    pass


def get_record(session: Session, model, tenant_id: str, record_id: str):
    row = session.scalar(select(model).where(model.tenant_id == tenant_id, model.id == record_id))
    if row is None:
        raise RecordNotFound("record not found")
    return row


def content(row) -> dict:
    result = json.loads(row.content_json)
    if (
        canonical_sha256(result) != row.content_sha256
        or result["platform_tenant_id"] != row.tenant_id
        or result["created_by_id"] != row.created_by_id
        or result["supersedes_id"] != row.supersedes_id
    ):
        raise ValueError("governance record integrity check failed")
    return result


@generation_reader
def scope_basis(lake: Path, tenant_id: str, scope: Scope, event_ids: list[str]) -> dict:
    generation = verified_generation(lake, tenant_id)
    controls = {r["control_id"]: r for r in read_json(lake / "catalog/control_map.json")["controls"]}
    safeguards = {r["safeguard_id"]: r for r in read_json(lake / "catalog/safeguards.json")["safeguards"]}
    if not (scope.control_ids or scope.safeguard_ids):
        raise ValueError("scope requires a control or safeguard")
    for ids, known in [(scope.control_ids, controls), (scope.safeguard_ids, safeguards)]:
        if len(ids) != len(set(ids)) or not set(ids) <= set(known):
            raise ValueError("scope has duplicate or unknown identifiers")
    assets = {(a.source_account_id, a.asset_id) for a in scope.assets}
    if len(assets) != len(scope.assets) or len(set(event_ids)) != len(event_ids):
        raise ValueError("duplicate asset or evidence reference")
    remaining = set(event_ids)
    observed = set()
    evidence = []
    for row in iter_jsonl(lake / "silver/normalized_events.jsonl"):
        key = source_asset_key(row)
        if key in assets:
            observed.add(key)
        if row["event_id"] not in remaining:
            continue
        if not evidence_available(row) or (assets and key not in assets):
            raise ValueError("evidence is unavailable or outside the declared scope")
        if not (
            set(row["control_ids"]) & set(scope.control_ids) or set(row["safeguard_ids"]) & set(scope.safeguard_ids)
        ):
            raise ValueError("evidence is not bound to the declared control or safeguard")
        evidence.append({key: row[key] for key in ("event_id", "tenant_id", "asset_id", "raw_sha256", "evidence_ref")})
        remaining.remove(row["event_id"])
    if remaining or assets - observed:
        raise ValueError("scope references unknown evidence or source-account assets")
    return {
        "generation": generation,
        "evidence": sorted(evidence, key=lambda r: r["event_id"]),
        "definitions": {sid: definition_digest(safeguards[sid]) for sid in sorted(scope.safeguard_ids)},
        "requirements": {cid: canonical_sha256(controls[cid]) for cid in sorted(scope.control_ids)},
    }


def current_basis() -> dict:
    return {
        "definitions": {s["safeguard_id"]: definition_digest(s) for s in load_safeguards()["safeguards"]},
        "requirements": {
            c["control_id"]: canonical_sha256(c) for c in with_program_requirements(load_control_map()).values()
        },
    }


def basis_verified(payload: dict, current: dict | None = None) -> bool:
    current = current if current is not None else current_basis()
    basis = payload["basis"]
    for field, scope_field in (("definitions", "safeguard_ids"), ("requirements", "control_ids")):
        saved = basis.get(field)
        if not isinstance(saved, dict) or set(saved) != set(payload["scope"][scope_field]):
            return False
        if any(current[field].get(key) != digest for key, digest in saved.items()):
            return False
    return True


def create_implementation(session, lake, identity, request: ImplementationRequest):
    if request.safeguard_id not in request.scope.safeguard_ids:
        raise ValueError("implementation safeguard must be included in its scope")
    basis = scope_basis(lake, identity.tenant_id, request.scope, request.evidence_event_ids)
    if request.supersedes_id:
        prior = get_record(session, SafeguardImplementation, identity.tenant_id, request.supersedes_id)
        if prior.safeguard_id != request.safeguard_id:
            raise ValueError("a revision must retain the implementation safeguard")
        content(prior)
    payload = {
        "schema_version": "grc-lake.safeguard_implementation.v1",
        **request.model_dump(),
        "platform_tenant_id": identity.tenant_id,
        "created_by_id": identity.user_id,
        "basis": basis,
        "effect": "scope_and_ownership_only_no_verdict_change",
    }
    row = SafeguardImplementation(
        tenant_id=identity.tenant_id,
        safeguard_id=request.safeguard_id,
        definition_sha256=basis["definitions"][request.safeguard_id],
        supersedes_id=request.supersedes_id,
        content_json=json.dumps(payload, sort_keys=True),
        content_sha256=canonical_sha256(payload),
        created_by_id=identity.user_id,
    )
    session.add(row)
    session.flush()
    return row


def create_decision(session, lake, identity, request: DecisionRequest):
    expires = timestamp(request.expires_at)
    if expires <= datetime.now(UTC):
        raise ValueError("decision expiry must be in the future")
    basis = scope_basis(lake, identity.tenant_id, request.scope, request.evidence_event_ids)
    if request.risk_id:
        from security_lakehouse.db.models import Risk

        get_record(session, Risk, identity.tenant_id, request.risk_id)
    if request.supersedes_id:
        prior = get_record(session, GovernanceDecision, identity.tenant_id, request.supersedes_id)
        previous = content(prior)
        if (
            previous["scope"] != request.scope.model_dump()
            or previous["kind"] != request.kind
            or previous["risk_id"] != request.risk_id
        ):
            raise ValueError("extensions must retain the decision kind, risk and exact scope")
        if expires <= timestamp(previous["expires_at"]):
            raise ValueError("an extension must extend the prior expiry")
    payload = {
        "schema_version": "grc-lake.governance_decision.v1",
        **request.model_dump(),
        "platform_tenant_id": identity.tenant_id,
        "created_by_id": identity.user_id,
        "basis": basis,
        "effect": "disposition_only_no_verdict_change",
    }
    row = GovernanceDecision(
        tenant_id=identity.tenant_id,
        supersedes_id=request.supersedes_id,
        content_json=json.dumps(payload, sort_keys=True),
        content_sha256=canonical_sha256(payload),
        created_by_id=identity.user_id,
        expires_at=expires,
    )
    session.add(row)
    session.flush()
    return row


def decision_state(session, row, current=None) -> dict:
    payload = content(row)
    verified = basis_verified(payload, current)
    reviews = list(
        session.scalars(
            select(GovernanceReview)
            .where(GovernanceReview.tenant_id == row.tenant_id, GovernanceReview.decision_id == row.id)
            .order_by(GovernanceReview.created_at, GovernanceReview.id)
        )
    )
    replacement = session.scalar(
        select(GovernanceReview.id).where(
            GovernanceReview.tenant_id == row.tenant_id, GovernanceReview.replaces_id == row.id
        )
    )
    approved = any(r.action == "approve" and r.content_sha256 == row.content_sha256 for r in reviews)
    revoked = any(r.action == "revoke" for r in reviews)
    expires = timestamp(payload["expires_at"])
    return {
        "active": verified and approved and not revoked and not replacement and expires > datetime.now(UTC),
        "basis_verified": verified,
        "approved": approved,
        "revoked": revoked,
        "superseded": bool(replacement),
        "reviews": [
            {
                "id": r.id,
                "decision": r.action,
                "rationale": r.rationale,
                "reviewer_id": r.reviewer_id,
                "auth_method": r.auth_method,
                "content_sha256": r.content_sha256,
                "created_at": r.created_at.isoformat(),
            }
            for r in reviews
        ],
    }


def review_decision(session, identity, decision_id, request: ReviewRequest):
    row = get_record(session, GovernanceDecision, identity.tenant_id, decision_id)
    # A no-op write takes a row lock on PostgreSQL and a writer lock on SQLite.
    # Serialize reviews with predecessor revocation before inspecting authority.
    for record_id in sorted({row.id, row.supersedes_id} - {None}):
        session.execute(
            update(GovernanceDecision)
            .where(
                GovernanceDecision.tenant_id == identity.tenant_id,
                GovernanceDecision.id == record_id,
            )
            .values(content_sha256=GovernanceDecision.content_sha256)
        )
    session.refresh(row)
    content(row)
    if row.content_sha256 != request.content_sha256:
        raise ValueError("review must bind the exact proposal content")
    state = decision_state(session, row)
    if request.decision == "revoke":
        if not state["approved"] or state["revoked"] or state["superseded"]:
            raise ValueError("only an approved, unsuperseded decision can be revoked")
    else:
        if row.created_by_id == identity.user_id:
            raise ValueError("an independent reviewer is required")
        if timestamp(content(row)["expires_at"]) <= datetime.now(UTC):
            raise ValueError("expired decisions cannot be approved or rejected")
        if request.decision == "approve" and not state["basis_verified"]:
            raise ValueError("changed definitions require a new proposal and review")
        if request.decision == "approve" and row.supersedes_id:
            prior = get_record(session, GovernanceDecision, identity.tenant_id, row.supersedes_id)
            prior_state = decision_state(session, prior)
            if not prior_state["approved"] or prior_state["revoked"] or prior_state["superseded"]:
                raise ValueError("extension requires an approved, unrevoked, unsuperseded predecessor")
    review = GovernanceReview(
        tenant_id=identity.tenant_id,
        decision_id=row.id,
        replaces_id=row.supersedes_id if request.decision == "approve" else None,
        slot="revocation" if request.decision == "revoke" else "decision",
        action=request.decision,
        rationale=request.rationale,
        content_sha256=row.content_sha256,
        reviewer_id=identity.user_id,
        auth_method=identity.auth_method,
    )
    session.add(review)
    session.flush()
    return row


def serialize(session, row, current=None) -> dict:
    payload = content(row)
    result = {
        "id": row.id,
        "platform_tenant_id": row.tenant_id,
        "supersedes_id": row.supersedes_id,
        "content": payload,
        "content_sha256": row.content_sha256,
        "created_by_id": row.created_by_id,
        "created_at": row.created_at.isoformat(),
    }
    if isinstance(row, GovernanceDecision):
        result.update(decision_state(session, row, current))
    else:
        result.update(
            definition_sha256=row.definition_sha256,
            basis_verified=basis_verified(payload, current),
            superseded=bool(
                session.scalar(
                    select(SafeguardImplementation.id).where(
                        SafeguardImplementation.tenant_id == row.tenant_id,
                        SafeguardImplementation.supersedes_id == row.id,
                    )
                )
            ),
        )
    return result
