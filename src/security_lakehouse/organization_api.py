"""Organization scope routes use the authenticated tenant's lake."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

from security_lakehouse import organization_scopes as scopes
from security_lakehouse.api_contract import envelope, error_envelope
from security_lakehouse.jsontypes import JsonObject

__all__ = ["organization_get", "organization_post", "organization_action"]


def organization_action(path: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"/api/v1/organizations/([^/]+)/(ingest|evaluate|discover|runs)", path)
    return (match[1], match[2]) if match else None


def organization_get(
    path: str,
    params: Mapping[str, list[str]],
    lake: Path,
    *,
    handle_get: Callable[..., Any],
    collection_response: Callable[..., Any],
) -> tuple[HTTPStatus, JsonObject]:
    try:
        if path == "/api/v1/organizations":
            return HTTPStatus.OK, collection_response("organizations", scopes.list_organizations(lake), params)
        action = organization_action(path)
        if action and action[1] == "runs":
            return HTTPStatus.OK, collection_response(
                "organization.runs", scopes.organization_runs(lake, action[0]), params
            )
        match = re.fullmatch(r"/api/v1/organizations/([^/]+)/evaluations/([^/]+)/assessment", path)
        if match:
            run = scopes.verify_organization_evaluation(lake, match[1], match[2])
            return handle_get("/api/v1/ccf/assessment", params, run)
    except FileNotFoundError:
        return HTTPStatus.NOT_FOUND, error_envelope("not_found", "organization or assessment not found")
    except ValueError:
        return HTTPStatus.BAD_REQUEST, error_envelope("bad_request", "invalid organization request")
    return HTTPStatus.NOT_FOUND, error_envelope("not_found", "organization route not found")


def organization_post(path: str, payload: dict[str, Any], lake: Path) -> tuple[HTTPStatus, JsonObject]:
    from security_lakehouse.organization_discovery import discover_organization

    try:
        if path == "/api/v1/organizations":
            allowed = {"organization_id", "name", "connection_ids", "expected_revision", "actor"}
            if set(payload) - allowed or not {"organization_id", "name", "connection_ids"} <= set(payload):
                raise ValueError("invalid scope payload")
            result = scopes.save_organization(lake, **payload)
        else:
            action = organization_action(path)
            if not action or action[1] == "runs":
                return HTTPStatus.NOT_FOUND, error_envelope("not_found", "organization route not found")
            organization_id, operation = action
            allowed = (
                {"actor", "expected_revision", "connection_id"}
                if operation == "discover"
                else {"actor", "expected_revision"}
            )
            if set(payload) - allowed:
                raise ValueError("invalid operation payload")
            actor = str(payload.get("actor") or "console")
            if operation == "discover":
                result = discover_organization(
                    lake,
                    organization_id,
                    str(payload.get("connection_id") or ""),
                    actor=actor,
                    expected_revision=payload.get("expected_revision"),
                )
            elif operation == "ingest":
                result = scopes.ingest_organization(
                    lake, organization_id, actor=actor, expected_revision=payload.get("expected_revision")
                )
            else:
                result = scopes.evaluate_organization(
                    lake, organization_id, actor=actor, expected_revision=payload.get("expected_revision")
                )
        return HTTPStatus.CREATED, envelope("organization", result)
    except FileNotFoundError:
        return HTTPStatus.NOT_FOUND, error_envelope("not_found", "organization or connection not found")
    except (ValueError, TypeError):
        return HTTPStatus.BAD_REQUEST, error_envelope(
            "bad_request", "invalid organization scope; reload and check selected connections"
        )
