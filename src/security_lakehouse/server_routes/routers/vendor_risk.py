"""Vendor risk routes, registered before generic dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from security_lakehouse import api_v1, remediation_guidance
from security_lakehouse.auth.dependencies import get_session, require_scope
from security_lakehouse.auth.rbac import Identity
from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.graph_admission import BuildToken, GraphBuildAborted, GraphBuildSlots
from security_lakehouse.server_routes.deps import parse_dt as _parse_dt
from security_lakehouse.server_routes.payloads import _page_meta, _pagination, _params, _redact_payload
from security_lakehouse.server_routes.schemas.workflows import (
    CreateVendorAssessmentRequest,
    UpdateVendorAssessmentRequest,
)
from security_lakehouse.services import NotFound, ValidationError
from security_lakehouse.services import vendor_risk as vendor_risk_services

_require_control_manage = require_scope("control_manage")
_require_read = require_scope("read")


async def _cancel_on_disconnect(request: Request, token: BuildToken) -> None:
    # A GET has no body left to read, so the next receive blocks until the
    # client disconnects (or the response completes and this task is cancelled).
    while (await request.receive())["type"] != "http.disconnect":
        pass
    token.cancel()


def _unavailable(code: str, detail: str, *, retry_after: int) -> JSONResponse:
    return JSONResponse(
        api_v1.error_envelope(code, detail),
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers={"Retry-After": str(retry_after)},
    )


def build_vendor_risk_router(
    *,
    lake_for: Callable[[Identity], Path],
    graph_slots: GraphBuildSlots,
    graph_timeout: float | None,
) -> APIRouter:
    """Build the authenticated workflow routes."""
    router = APIRouter()

    @router.get("/api/v1/graph/investigation")
    async def read_investigation(
        request: Request, identity: Identity = Depends(_require_read), session: Session = Depends(get_session)
    ) -> JSONResponse:
        from security_lakehouse import investigation_graph as graph

        params = request.query_params
        try:
            bounds: dict[str, Any] = {
                "root": params.get("root"),
                "view": params.get("view", "controls"),
                "depth": int(params.get("depth", "2")),
                "limit": int(params.get("limit", "150")),
                "search": params.get("search", "")[:200],
                "root_offset": int(params.get("root_offset", "0")),
                "framework": params.get("framework", ""),
                "control_offset": int(params.get("control_offset", "0")),
                "layers": set(params["layers"].split(",")) if params.get("layers") else None,
                "expected_version": params.get("version"),
            }
            graph.validate_bounds(**bounds)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        rejection = graph_slots.try_acquire(identity.tenant_id)
        if rejection is not None:
            return _unavailable(rejection, "graph read concurrency limit reached; retry shortly", retry_after=1)
        token = BuildToken(graph_timeout)

        def build() -> dict[str, Any]:
            vendors = vendor_risk_services.list_assessments(session, identity.tenant_id)
            data = graph.investigation_graph(lake_for(identity), vendors=vendors, checkpoint=token.check, **bounds)
            return api_v1.envelope("graph.investigation", _redact_payload(data, identity))

        watcher = asyncio.create_task(_cancel_on_disconnect(request, token))
        try:
            # The default worker-thread call defers cancellation until the build
            # returns, so the slot is released only once the thread has stopped.
            payload = await run_in_threadpool(build)
        except GraphBuildAborted as exc:
            if exc.reason == "deadline":
                return _unavailable("graph_build_timeout", "graph build exceeded its time budget", retry_after=5)
            return _unavailable("graph_build_cancelled", "graph build cancelled after client disconnect", retry_after=1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            watcher.cancel()
            graph_slots.release(identity.tenant_id)
        return JSONResponse(payload)

    @router.get("/api/v1/vendor-questionnaires")
    def list_vendor_questionnaires(identity: Identity = Depends(_require_read)) -> JSONResponse:
        data = vendor_risk_services.list_templates()
        return JSONResponse(
            api_v1.envelope("vendor-questionnaires", _redact_payload(data, identity), meta={"count": len(data)})
        )

    @router.get("/api/v1/vendor-questionnaires/{template_id}")
    def get_vendor_questionnaire(template_id: str, identity: Identity = Depends(_require_read)) -> JSONResponse:
        try:
            data = vendor_risk_services.get_template(template_id)
        except NotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return JSONResponse(api_v1.envelope("vendor-questionnaires", _redact_payload(data, identity)))

    @router.get("/api/v1/vendor-assessments")
    def list_vendor_assessments(
        request: Request, identity: Identity = Depends(_require_read), session: Session = Depends(get_session)
    ) -> JSONResponse:
        params = _params(request)
        limit, offset = _pagination(params)
        data = vendor_risk_services.list_assessments(
            session,
            identity.tenant_id,
            status=api_v1.first_param(params, "status"),
            limit=limit,
            offset=offset,
        )
        return JSONResponse(
            api_v1.envelope(
                "vendor-assessments", _redact_payload(data, identity), meta=_page_meta(limit, offset, len(data))
            )
        )

    @router.post("/api/v1/vendor-assessments", status_code=status.HTTP_201_CREATED)
    def create_vendor_assessment(
        body: CreateVendorAssessmentRequest,
        identity: Identity = Depends(_require_control_manage),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        try:
            assessment = vendor_risk_services.create_assessment(
                session,
                identity.tenant_id,
                vendor_name=body.vendor_name,
                template_id=body.template_id,
                owner=body.owner,
                control_id=body.control_id,
                due_at=_parse_dt(body.due_at),
                created_by=identity.email,
            )
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return JSONResponse(api_v1.envelope("vendor-assessments", assessment), status_code=status.HTTP_201_CREATED)

    @router.get("/api/v1/vendor-assessments/{assessment_id}")
    def get_vendor_assessment(
        assessment_id: str, identity: Identity = Depends(_require_read), session: Session = Depends(get_session)
    ) -> JSONResponse:
        try:
            data = vendor_risk_services.get_assessment(session, identity.tenant_id, assessment_id)
        except NotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return JSONResponse(api_v1.envelope("vendor-assessments", _redact_payload(data, identity)))

    @router.patch("/api/v1/vendor-assessments/{assessment_id}")
    def update_vendor_assessment(
        assessment_id: str,
        body: UpdateVendorAssessmentRequest,
        identity: Identity = Depends(_require_control_manage),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        changes = body.model_dump(exclude_unset=True)
        if "due_at" in changes:
            changes["due_at"] = _parse_dt(changes["due_at"])
        try:
            assessment = vendor_risk_services.update_assessment(
                session, identity.tenant_id, assessment_id, changes=changes
            )
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except NotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return JSONResponse(api_v1.envelope("vendor-assessments", assessment))

    @router.post("/api/v1/vendor-assessments/{assessment_id}/submit")
    def submit_vendor_assessment(
        assessment_id: str,
        identity: Identity = Depends(_require_control_manage),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        try:
            assessment = vendor_risk_services.submit_assessment(session, identity.tenant_id, assessment_id)
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except NotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return JSONResponse(api_v1.envelope("vendor-assessments", assessment))

    # --- remediation guidance ---
    @router.get("/api/v1/controls/{control_id}/remediation")
    def control_remediation(
        control_id: str, identity: Identity = Depends(_require_read), session: Session = Depends(get_session)
    ) -> JSONResponse:
        control = load_control_catalog().get(control_id)
        if control is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="control not found")
        data = remediation_guidance.guidance_for_control(control)
        return JSONResponse(api_v1.envelope("controls.remediation", data))

    return router
