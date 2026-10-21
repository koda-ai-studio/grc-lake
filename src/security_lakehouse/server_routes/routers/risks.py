"""Risks routes, registered before generic dispatch."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from security_lakehouse import api_v1
from security_lakehouse.auth.dependencies import get_session, require_scope
from security_lakehouse.auth.rbac import Identity
from security_lakehouse.db.base import MAX_PAGE_LIMIT
from security_lakehouse.server_routes.deps import parse_dt as _parse_dt
from security_lakehouse.server_routes.payloads import _applied_filters, _page_window, _params, _redact_payload
from security_lakehouse.server_routes.schemas.workflows import CreateRiskRequest, UpdateRiskRequest
from security_lakehouse.services import grc as grc_services

_require_read = require_scope("read")
_require_write = require_scope("write")


def build_risks_router() -> APIRouter:
    """Build the authenticated workflow routes."""
    router = APIRouter()

    @router.get("/api/v1/risks")
    def list_risks(
        request: Request, identity: Identity = Depends(_require_read), session: Session = Depends(get_session)
    ) -> JSONResponse:
        params = _params(request)
        limit, offset = _page_window(params, maximum=MAX_PAGE_LIMIT)
        filters = {name: api_v1.first_param(params, name) for name in ("status", "severity", "owner")}
        data = grc_services.list_risks(session, identity.tenant_id, **filters, limit=limit, offset=offset)
        total = grc_services.count_risks(session, identity.tenant_id, **filters)
        return JSONResponse(
            api_v1.collection_page_response(
                "risks",
                _redact_payload(data, identity),  # type: ignore[arg-type]
                count=total,
                limit=limit,
                offset=offset,
                sort=None,
                filters=_applied_filters(**filters),
            )
        )

    @router.post("/api/v1/risks", status_code=status.HTTP_201_CREATED)
    def create_risk(
        body: CreateRiskRequest,
        identity: Identity = Depends(_require_write),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        risk = grc_services.create_risk(
            session,
            identity.tenant_id,
            **body.model_dump(exclude={"due_at"}),
            due_at=_parse_dt(body.due_at),
        )
        return JSONResponse(api_v1.envelope("risks", risk), status_code=status.HTTP_201_CREATED)

    @router.patch("/api/v1/risks/{risk_id}")
    def update_risk(
        risk_id: str,
        body: UpdateRiskRequest,
        identity: Identity = Depends(_require_write),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        changes = body.model_dump(exclude_unset=True)
        if "due_at" in changes:
            changes["due_at"] = _parse_dt(changes["due_at"])
        risk = grc_services.update_risk(session, identity.tenant_id, risk_id, changes=changes)
        return JSONResponse(api_v1.envelope("risks", risk))

    @router.delete("/api/v1/risks/{risk_id}")
    def delete_risk(
        risk_id: str,
        identity: Identity = Depends(_require_write),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        result = grc_services.delete_risk(session, identity.tenant_id, risk_id)
        return JSONResponse(api_v1.envelope("risks", result))

    return router
