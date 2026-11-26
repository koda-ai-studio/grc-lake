"""Microsoft Defender inventory, antivirus versions and alerts (read-only Preview)."""

from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connectors_endpoint_common import EndpointClient, event, fields, fresh, gap, identity
from security_lakehouse.ingestion.paginate import object_rows
from security_lakehouse.io import read_json

CONNECTOR_ID = "defender-endpoint"
SOURCE = "defender_endpoint"
TOKEN_ENV = "DEFENDER_ENDPOINT_API_TOKEN"
API_HOST = "api.security.microsoft.com"


class DefenderEndpointClient(EndpointClient):
    def __init__(self, *, token: str, max_pages: int = 100) -> None:
        super().__init__(token=token, host=API_HOST, source=SOURCE, max_pages=max_pages)

    def records(self, path: str) -> list[dict[str, Any]]:
        target = f"{path}?$top=1000&$skip=0"
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        links: set[str] = set()
        for _ in range(self.max_pages):
            if target in links:
                raise gap(path, "repeated_page")
            links.add(target)
            page = self.get(target)
            if not isinstance(page, dict) or page.get("error"):
                raise gap(path, "invalid_page")
            chunk = object_rows(page.get("value"), label=CONNECTOR_ID)
            for row in chunk:
                key = identity(row.get("id"))
                if key in seen:
                    raise gap(path, "duplicate_id")
                seen.add(key)
            rows.extend(chunk)
            link = page.get("@odata.nextLink")
            if link is not None:
                if not isinstance(link, str) or not link or len(link) > 8192:
                    raise gap(path, "invalid_next_link")
                parts = urllib.parse.urlsplit(urllib.parse.urljoin(f"https://{self.host}{path}", link))
                if parts.scheme != "https" or parts.netloc != self.host or parts.path != path or parts.fragment:
                    raise gap(path, "unsafe_next_link")
                target = f"{path}?{parts.query}"
            elif len(chunk) == 1000:
                target = f"{path}?$top=1000&$skip={len(rows)}"
            elif len(chunk) < 1000:
                return rows
            else:
                raise gap(path, "invalid_page_size")
        raise gap(path, "page_budget_exhausted")


class DefenderEndpointFixtureClient(DefenderEndpointClient):
    synthetic = True

    def __init__(self, fixture_dir: str | Path, *, max_pages: int = 100) -> None:
        super().__init__(token="", max_pages=max_pages)
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, path: str) -> Any:
        if path not in self.responses:
            raise gap(path.split("?")[0], "fixture_missing")
        return self.responses[path]


def collect_defender_endpoint_evidence(
    client: DefenderEndpointClient, *, collected_at: datetime | None = None, tenant_id: str = "customer-managed"
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    result: list[dict[str, Any]] = []

    def read(path: str, *, inventory: bool = False) -> list[dict[str, Any]]:
        try:
            rows = client.records(path)
            if inventory and not rows:
                raise gap(path, "empty_inventory")
            return rows
        except (CollectionGapError, ValueError) as exc:
            error = exc if isinstance(exc, CollectionGapError) else gap(path, "invalid_response")
            result.append(
                event(client, path, path, "collection_gap", "not_evaluated", error.attributes(), now, tenant_id, path)
            )
            return []

    machines = read("/api/machines", inventory=True)
    av_rows = read("/api/deviceavinfo", inventory=True)
    av_by_machine: dict[str, list[dict[str, Any]]] = {}
    for av in av_rows:
        machine = av.get("machineId")
        if isinstance(machine, str):
            av_by_machine.setdefault(machine, []).append(av)
    for machine in machines:
        key = machine["id"]
        attrs = fields(machine, ("id", "lastSeen", "healthStatus", "onboardingStatus"))
        matches = av_by_machine.get(key, [])
        av = matches[0] if len(matches) == 1 else {}
        attrs.update(fields(av, ("avPlatformVersion", "avEngineVersion", "avMode", "lastSeenTime")))
        current = fresh(machine.get("lastSeen"), now) and fresh(av.get("lastSeenTime"), now)
        status = (
            "observed"
            if current and machine.get("healthStatus") == "Active" and machine.get("onboardingStatus") == "onboarded"
            else "not_evaluated"
        )
        result.append(event(client, key, key, "protection", status, attrs, now, tenant_id, f"/api/machines/{key}"))
    for alert in read("/api/alerts"):
        try:
            key, host = identity(alert.get("id")), identity(alert.get("machineId"))
        except ValueError:
            result.append(
                event(
                    client,
                    "/api/alerts",
                    "/api/alerts",
                    "collection_gap",
                    "not_evaluated",
                    gap("/api/alerts", "missing_machine_identity").attributes(),
                    now,
                    tenant_id,
                    "/api/alerts",
                )
            )
            continue
        state = alert.get("status")
        status = "open" if state in ("New", "InProgress") else "observed" if state == "Resolved" else "not_evaluated"
        attrs = fields(
            alert, ("id", "machineId", "severity", "status", "alertCreationTime", "lastUpdateTime", "resolvedTime")
        )
        result.append(event(client, key, host, "alert", status, attrs, now, tenant_id, f"/api/alerts/{key}"))
    return result
