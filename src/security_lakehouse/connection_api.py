"""Named connection routes share the existing connector credential boundary."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

from security_lakehouse.api_contract import envelope, error_envelope
from security_lakehouse.connections import connection_context, create_connection, list_connections, sync_connection
from security_lakehouse.connector_runner import ConnectorSyncError
from security_lakehouse.jsontypes import JsonObject

__all__ = ["connection_get", "connection_post", "connection_action"]


def connection_action(path: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"/api/v1/connections/([^/]+)/(configure|probe|discover|sync|runs)", path)
    return (match[1], match[2]) if match else None


def connection_get(
    path: str,
    params: Mapping[str, list[str]],
    lake: Path,
    *,
    handle_get: Callable[..., Any],
    collection_response: Callable[..., Any],
) -> tuple[HTTPStatus, JsonObject]:
    try:
        if path == "/api/v1/connections":
            return HTTPStatus.OK, collection_response("connections", list_connections(lake), params)
        action = connection_action(path)
        if action and action[1] == "runs":
            child, info = connection_context(lake, action[0])
            return handle_get(f"/api/v1/connectors/{info['connector_id']}/runs", params, child)
    except FileNotFoundError:
        return HTTPStatus.NOT_FOUND, error_envelope("not_found", "connection not found")
    except ValueError:
        return HTTPStatus.BAD_REQUEST, error_envelope("bad_request", "invalid connection request")
    return HTTPStatus.NOT_FOUND, error_envelope("not_found", "connection route not found")


def connection_post(
    path: str, payload: dict[str, Any], lake: Path, *, handle_post: Callable[..., Any]
) -> tuple[HTTPStatus, JsonObject]:
    try:
        if path == "/api/v1/connections":
            allowed = {"connection_id", "connector_id", "source_account_id", "name"}
            if set(payload) - {"actor"} != allowed:
                raise ValueError("provide connection_id, connector_id, source_account_id and name")
            return HTTPStatus.CREATED, envelope(
                "connections", create_connection(lake, **{key: payload[key] for key in allowed})
            )
        action = connection_action(path)
        if action:
            connection_id, operation = action
            child, info = connection_context(lake, connection_id)
            if operation == "sync":
                if set(payload) - {"actor", "materialize", "idempotency_key"} or not isinstance(
                    payload.get("materialize", True), bool
                ):
                    raise ValueError("invalid sync payload")
                result = sync_connection(
                    lake,
                    connection_id,
                    actor=str(payload.get("actor") or "console"),
                    materialize=payload.get("materialize", True),
                )
                return HTTPStatus.CREATED, envelope("connection.sync", result)
            if operation in {"configure", "probe", "discover"}:
                return handle_post(f"/api/v1/connectors/{info['connector_id']}/{operation}", payload, child)
    except FileNotFoundError:
        return HTTPStatus.NOT_FOUND, error_envelope("not_found", "connection not found")
    except ConnectorSyncError:
        return HTTPStatus.BAD_GATEWAY, error_envelope(
            "sync_failed", "collection failed; inspect this connection's run history"
        )
    except (ValueError, TypeError):
        return HTTPStatus.BAD_REQUEST, error_envelope(
            "bad_request", "invalid connection request or duplicate account binding"
        )
    return HTTPStatus.NOT_FOUND, error_envelope("not_found", "connection route not found")
