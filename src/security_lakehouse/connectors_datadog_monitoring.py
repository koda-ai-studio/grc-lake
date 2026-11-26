"""Datadog monitoring observations on a fixed regional host allowlist (Preview)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.connectors_operations_common import FixtureReads, ReadClient, event, gap, record_id
from security_lakehouse.ingestion.paginate import object_rows
from security_lakehouse.models import utc_iso

CONNECTOR_ID = "datadog-monitoring"
SOURCE = "datadog_monitoring"
TOKEN_ENV = "DATADOG_API_KEY"
SITES = (
    "datadoghq.com",
    "datadoghq.eu",
    "us3.datadoghq.com",
    "us5.datadoghq.com",
    "ap1.datadoghq.com",
    "ap2.datadoghq.com",
    "uk1.datadoghq.com",
    "ddog-gov.com",
    "us2.ddog-gov.com",
)
PATHS = {
    "log_index": "/api/v1/logs/config/indexes",
    "monitor": "/api/v1/monitor",
    "signal": "/api/v2/security_monitoring/signals",
    "audit_trail": "/api/v2/audit/events",
}


class DatadogMonitoringClient(ReadClient):
    def __init__(
        self, *, api_key: str, application_key: str, site: str = "datadoghq.com", max_pages: int = 100
    ) -> None:
        if site not in SITES:
            raise ConnectorConfigError("Datadog site must be a documented region in the fixed allowlist")
        super().__init__(
            host=f"api.{site}",
            source=SOURCE,
            headers={"DD-API-KEY": api_key, "DD-APPLICATION-KEY": application_key},
            max_pages=max_pages,
        )

    def records(self, signal: str, now: datetime) -> list[dict[str, Any]]:
        path = PATHS[signal]
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursors: set[str] = set()
        cursor = None
        for page in range(self.max_pages):
            query: dict[str, str] = {}
            if signal == "monitor":
                query = {"page": str(page), "page_size": "100", "with_downtimes": "true"}
            elif signal in ("signal", "audit_trail"):
                query = {
                    "page[limit]": "100",
                    "filter[from]": utc_iso(now - timedelta(days=1)),
                    "filter[to]": utc_iso(now),
                    "sort": "timestamp",
                }
                if cursor:
                    query["page[cursor]"] = cursor
            payload = self.get(path, query)
            if signal == "monitor":
                chunk = object_rows(payload, label=CONNECTOR_ID)
            else:
                if not isinstance(payload, dict) or payload.get("errors"):
                    raise gap(path, "invalid_page")
                chunk = object_rows(payload.get("indexes" if signal == "log_index" else "data"), label=CONNECTOR_ID)
            for row in chunk:
                key = record_id(row.get("name" if signal == "log_index" else "id"))
                if key in seen:
                    raise gap(path, "duplicate_record")
                seen.add(key)
            rows.extend(chunk)
            if signal == "log_index":
                return rows
            if signal == "monitor":
                if len(chunk) < 100:
                    return rows
                if len(chunk) > 100:
                    raise gap(path, "invalid_page_size")
                continue
            meta = payload.get("meta")
            if not isinstance(meta, dict) or meta.get("status") != "done":
                raise gap(path, "incomplete_query")
            paging = meta.get("page", {})
            if not isinstance(paging, dict):
                raise gap(path, "invalid_pagination")
            cursor = paging.get("after")
            if cursor is None:
                return rows
            if not isinstance(cursor, str) or not cursor or len(cursor) > 8192 or cursor in cursors:
                raise gap(path, "invalid_cursor")
            # Only the opaque cursor is used. Provider UI links never receive credentials.
            cursors.add(cursor)
        raise gap(path, "page_budget_exhausted")


class DatadogMonitoringFixtureClient(FixtureReads, DatadogMonitoringClient):
    def __init__(self, fixture_dir: str | Path, *, site: str = "datadoghq.com", max_pages: int = 100) -> None:
        super().__init__(api_key="", application_key="", site=site, max_pages=max_pages)
        self.load(fixture_dir)


def collect_datadog_monitoring_evidence(
    client: DatadogMonitoringClient, *, collected_at: datetime | None = None, tenant_id: str = "customer-managed"
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    result = []
    for signal, path in PATHS.items():
        try:
            rows = client.records(signal, now)
            if signal in ("monitor", "log_index") and not rows:
                raise gap(path, "empty_scope")
            pending = []
            for row in rows:
                key = record_id(row.get("name" if signal == "log_index" else "id"))
                attrs: dict[str, Any] = {"record_id": key}
                status = "not_evaluated"
                if signal == "log_index":
                    retention = row.get("num_retention_days")
                    attrs.update(
                        retention_days=retention if type(retention) is int else None,
                        rate_limited=row.get("is_rate_limited") if type(row.get("is_rate_limited")) is bool else None,
                    )
                    if type(retention) is int and retention >= 0:
                        status = "open" if row.get("is_rate_limited") is True else "observed"
                elif signal == "monitor":
                    options = row.get("options")
                    message = row.get("message")
                    silenced = options.get("silenced") if isinstance(options, dict) else None
                    downtimes = row.get("matching_downtimes")
                    targets = (
                        len(set(re.findall(r"(?<!\w)@[A-Za-z0-9_.+\-]+(?:@[A-Za-z0-9.\-]+)?", message)))
                        if isinstance(message, str)
                        else None
                    )
                    muted = bool(downtimes) if isinstance(downtimes, list) else None
                    if isinstance(silenced, dict) and any(
                        v is None or (type(v) in (int, float) and v > now.timestamp()) for v in silenced.values()
                    ):
                        muted = True
                    state = row.get("overall_state")
                    attrs.update(
                        state=state if isinstance(state, str) else None,
                        muted=muted,
                        notification_target_count=targets,
                        draft=row.get("draft_status") == "draft",
                    )
                    if (
                        muted is True
                        or targets == 0
                        or row.get("draft_status") == "draft"
                        or state in ("Alert", "Warn")
                    ):
                        status = "open"
                    elif muted is False and targets and state == "OK":
                        status = "observed"
                elif signal == "signal":
                    attributes = row.get("attributes")
                    if not isinstance(attributes, dict):
                        raise gap(path, "invalid_signal")
                    attrs["timestamp"] = (
                        attributes.get("timestamp") if isinstance(attributes.get("timestamp"), str) else None
                    )
                    status = "observed"
                else:
                    continue
                pending.append(event(client, key, signal, status, attrs, now, tenant_id, path))
            if signal == "audit_trail":
                pending.append(
                    event(
                        client,
                        "visible-scope",
                        signal,
                        "not_evaluated",
                        {
                            "enabled": None,
                            "visible_event_count": len(rows),
                            "window_hours": 24,
                            "reason": "event_availability_does_not_establish_current_enablement",
                        },
                        now,
                        tenant_id,
                        path,
                    )
                )
            if signal == "signal" and not rows:
                pending.append(
                    event(
                        client,
                        "visible-scope",
                        signal,
                        "not_evaluated",
                        {"visible_event_count": 0, "window_hours": 24, "reason": "empty_signal_window_is_not_a_pass"},
                        now,
                        tenant_id,
                        path,
                    )
                )
            result.extend(pending)
        except (CollectionGapError, ValueError) as exc:
            error = exc if isinstance(exc, CollectionGapError) else gap(path, "invalid_response")
            result.append(
                event(client, path, "collection_gap", "not_evaluated", error.attributes(), now, tenant_id, path)
            )
    return result
