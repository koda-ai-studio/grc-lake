"""Tenant-bound scope revisions and independently reviewed risk decisions."""

from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from security_lakehouse import api_v1
from security_lakehouse import governance_records as records
from security_lakehouse.auth.dependencies import get_session, require_human, require_scope
from security_lakehouse.auth.rbac import Identity
from security_lakehouse.db.models import GovernanceDecision, SafeguardImplementation
from security_lakehouse.server_routes.payloads import _redact_payload

_read = require_scope("read")
_manage = require_scope("control_manage")


def build_governance_router(*, lake_for: Callable[[Identity], Path]) -> APIRouter:
    router = APIRouter(tags=["governance"])

    def save(session, identity, operation):
        try:
            row = operation()
            result = records.serialize(session, row)
            session.commit()
            return _redact_payload(result, identity)
        except records.RecordNotFound as exc:
            session.rollback()
            raise HTTPException(404, "record not found") from exc
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "record already reviewed or superseded; refresh before retrying") from exc
        except (ValueError, OSError) as exc:
            session.rollback()
            raise HTTPException(400, "invalid scope, evidence basis, expiry or review authority") from exc

    @router.post("/api/v1/ccf/implementations", status_code=201)
    def implementation(
        body: records.ImplementationRequest,
        identity: Identity = Depends(_manage),
        session: Session = Depends(get_session),
    ):
        require_human(identity)
        return api_v1.envelope(
            "ccf.implementations",
            save(session, identity, lambda: records.create_implementation(session, lake_for(identity), identity, body)),
        )

    @router.get("/api/v1/ccf/implementations")
    def implementations(
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        identity: Identity = Depends(_read),
        session: Session = Depends(get_session),
    ):
        return listing(session, identity, SafeguardImplementation, "ccf.implementations", limit, offset)

    @router.post("/api/v1/governance/decisions", status_code=201)
    def propose(
        body: records.DecisionRequest, identity: Identity = Depends(_manage), session: Session = Depends(get_session)
    ):
        return api_v1.envelope(
            "governance.decisions",
            save(session, identity, lambda: records.create_decision(session, lake_for(identity), identity, body)),
        )

    @router.get("/api/v1/governance/decisions")
    def decisions(
        limit: int = Query(25, ge=1, le=100),
        offset: int = Query(0, ge=0),
        identity: Identity = Depends(_read),
        session: Session = Depends(get_session),
    ):
        return listing(session, identity, GovernanceDecision, "governance.decisions", limit, offset)

    @router.post("/api/v1/governance/decisions/{decision_id}/reviews")
    def review(
        decision_id: str,
        body: records.ReviewRequest,
        identity: Identity = Depends(_manage),
        session: Session = Depends(get_session),
    ):
        require_human(identity)
        return api_v1.envelope(
            "governance.decisions",
            save(session, identity, lambda: records.review_decision(session, identity, decision_id, body)),
        )

    def listing(session, identity, model, resource, limit, offset):
        rows = session.scalars(
            select(model)
            .where(model.tenant_id == identity.tenant_id)
            .order_by(model.created_at.desc(), model.id)
            .limit(limit + 1)
            .offset(offset)
        ).all()
        try:
            current = records.current_basis()
            data = [records.serialize(session, row, current) for row in rows[:limit]]
        except ValueError as exc:
            raise HTTPException(409, "governance record integrity check failed") from exc
        return api_v1.envelope(
            resource,
            _redact_payload(data, identity),
            meta={"has_more": len(rows) > limit, "limit": limit, "offset": offset},
        )

    return router
