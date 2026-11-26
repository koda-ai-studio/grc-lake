"""SentinelOne agent policies and threat observations (read-only Preview)."""

from __future__ import annotations

import re
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.connectors_endpoint_common import EndpointClient, event, fields, fresh, gap, identity
from security_lakehouse.ingestion.paginate import object_rows
from security_lakehouse.io import read_json

CONNECTOR_ID = "sentinelone-endpoint"
SOURCE = "sentinelone_endpoint"
TOKEN_ENV = "SENTINELONE_ENDPOINT_API_TOKEN"


class SentineloneEndpointClient(EndpointClient):
    def __init__(self, *, token: str, subdomain: str, max_pages: int = 100) -> None:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", subdomain):
            raise ConnectorConfigError("SentinelOne requires a console subdomain on sentinelone.net")
        super().__init__(
            token=token, host=f"{subdomain}.sentinelone.net", source=SOURCE, auth="ApiToken", max_pages=max_pages
        )

    def records(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursors: set[str] = set()
        cursor = None
        for _ in range(self.max_pages):
            query = {"limit": "1000"}
            if cursor:
                query["cursor"] = cursor
            page = self.get(f"{path}?{urllib.parse.urlencode(query)}")
            if not isinstance(page, dict) or page.get("errors") or not isinstance(page.get("pagination"), dict):
                raise gap(path, "invalid_page")
            chunk = object_rows(page.get("data"), label=CONNECTOR_ID)
            if len(chunk) > 1000:
                raise gap(path, "invalid_page_size")
            for row in chunk:
                key = identity(row.get("id"))
                if key in seen:
                    raise gap(path, "duplicate_id")
                seen.add(key)
            rows.extend(chunk)
            pagination = page["pagination"]
            if "nextCursor" not in pagination:
                raise gap(path, "missing_pagination")
            cursor = pagination["nextCursor"]
            if cursor is None:
                total = pagination.get("totalItems")
                if type(total) is not int or total != len(rows):
                    raise gap(path, "population_count_mismatch")
                return rows
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in cursors:
                raise gap(path, "invalid_cursor")
            cursors.add(cursor)
        raise gap(path, "page_budget_exhausted")


class SentineloneEndpointFixtureClient(SentineloneEndpointClient):
    synthetic = True

    def __init__(self, fixture_dir: str | Path, *, subdomain: str, max_pages: int = 100) -> None:
        super().__init__(token="", subdomain=subdomain, max_pages=max_pages)
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, path: str) -> Any:
        if path not in self.responses:
            raise gap(path.split("?")[0], "fixture_missing")
        return self.responses[path]


def collect_sentinelone_endpoint_evidence(
    client: SentineloneEndpointClient, *, collected_at: datetime | None = None, tenant_id: str = "customer-managed"
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    result: list[dict[str, Any]] = []
    for collection in ("agents", "threats"):
        path = f"/web/api/v2.1/{collection}"
        try:
            rows = client.records(path)
            if collection == "agents" and not rows:
                raise gap(path, "empty_inventory")
            pending = []
            for row in rows:
                key = identity(row.get("id"))
                if collection == "agents":
                    host, signal = key, "protection"
                    attrs = fields(
                        row,
                        (
                            "id",
                            "agentVersion",
                            "isActive",
                            "isDecommissioned",
                            "lastActiveDate",
                            "mitigationMode",
                            "mitigationModeSuspicious",
                            "infected",
                        ),
                    )
                    active = (
                        row.get("isActive") is True
                        and row.get("isDecommissioned") is False
                        and fresh(row.get("lastActiveDate"), now)
                    )
                    modes = (row.get("mitigationMode"), row.get("mitigationModeSuspicious"))
                    status = "not_evaluated"
                    if active and all(mode in ("detect", "protect") for mode in modes):
                        status = "open" if "detect" in modes else "observed"
                else:
                    info, agent = row.get("threatInfo"), row.get("agentRealtimeInfo")
                    if not isinstance(info, dict) or not isinstance(agent, dict):
                        raise gap(path, "invalid_threat")
                    host, signal = identity(agent.get("agentId")), "alert"
                    attrs = fields(
                        info, ("mitigationStatus", "incidentStatus", "classification", "createdAt", "updatedAt")
                    )
                    attrs["id"] = key
                    mitigation, incident = info.get("mitigationStatus"), info.get("incidentStatus")
                    status = "not_evaluated"
                    if mitigation in ("not_mitigated", "mitigated", "marked_as_benign") and incident in (
                        "unresolved",
                        "in_progress",
                        "resolved",
                    ):
                        status = "observed" if incident == "resolved" and mitigation != "not_mitigated" else "open"
                pending.append(event(client, key, host, signal, status, attrs, now, tenant_id, path))
            result.extend(pending)
        except (CollectionGapError, ValueError) as exc:
            error = exc if isinstance(exc, CollectionGapError) else gap(path, "invalid_response")
            result.append(
                event(client, path, path, "collection_gap", "not_evaluated", error.attributes(), now, tenant_id, path)
            )
    return result
