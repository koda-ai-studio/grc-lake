"""Read-only ServiceNow Table API snapshots for changes and incidents (Preview)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.connectors_operations_common import FixtureReads, ReadClient, event, gap
from security_lakehouse.ingestion.paginate import object_rows

CONNECTOR_ID = "servicenow-operations"
SOURCE = "servicenow_operations"
TOKEN_ENV = "SERVICENOW_API_TOKEN"
FIELDS = {
    "change_request": (
        "sys_id",
        "approval",
        "approval_set",
        "risk",
        "state",
        "work_start",
        "work_end",
        "review_date",
        "sys_updated_on",
    ),
    "incident": ("sys_id", "priority", "state", "active", "opened_at", "resolved_at", "due_date", "sys_updated_on"),
}


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


class ServicenowOperationsClient(ReadClient):
    def __init__(self, *, token: str, subdomain: str, max_pages: int = 100) -> None:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", subdomain):
            raise ConnectorConfigError("ServiceNow requires an instance subdomain on service-now.com")
        super().__init__(
            host=f"{subdomain}.service-now.com",
            source=SOURCE,
            headers={"Authorization": f"Bearer {token}"},
            max_pages=max_pages,
        )

    def records(self, table: str) -> list[dict[str, Any]]:
        path = f"/api/now/table/{table}"
        rows = []
        seen: set[str] = set()
        for page in range(self.max_pages):
            payload = self.get(
                path,
                {
                    "sysparm_fields": ",".join(FIELDS[table]),
                    "sysparm_limit": "100",
                    "sysparm_offset": str(page * 100),
                    "sysparm_query": "ORDERBYsys_id",
                    "sysparm_display_value": "false",
                    "sysparm_exclude_reference_link": "true",
                },
            )
            if not isinstance(payload, dict) or payload.get("error"):
                raise gap(path, "invalid_page")
            chunk = object_rows(payload.get("result"), label=CONNECTOR_ID)
            if len(chunk) > 100:
                raise gap(path, "invalid_page_size")
            for row in chunk:
                key = row.get("sys_id")
                if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{32}", key):
                    raise gap(path, "invalid_id")
                if key in seen:
                    raise gap(path, "duplicate_record")
                seen.add(key)
            rows.extend(chunk)
            if len(chunk) < 100:
                return rows
        raise gap(path, "page_budget_exhausted")


class ServicenowOperationsFixtureClient(FixtureReads, ServicenowOperationsClient):
    def get(self, *args: Any, **kwargs: Any) -> Any:
        return FixtureReads.get(self, *args, **kwargs)

    def __init__(self, fixture_dir: str | Path, *, subdomain: str, max_pages: int = 100) -> None:
        super().__init__(token="", subdomain=subdomain, max_pages=max_pages)
        self.load(fixture_dir)


def collect_servicenow_operations_evidence(
    client: ServicenowOperationsClient, *, collected_at: datetime | None = None, tenant_id: str = "customer-managed"
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    result = []
    for table in FIELDS:
        path = f"/api/now/table/{table}"
        try:
            rows = client.records(table)
            if not rows:
                raise gap(path, "empty_scope")
            for row in rows:
                attrs = {k: row.get(k) if isinstance(row.get(k), (str, bool)) else None for k in FIELDS[table]}
                status = "not_evaluated"
                if table == "change_request":
                    signal = "change"
                    started, approved = _time(row.get("work_start")), _time(row.get("approval_set"))
                    if started is not None and started <= now:
                        status = (
                            "observed"
                            if row.get("approval") == "approved" and approved is not None and approved <= started
                            else "open"
                        )
                    elif row.get("work_start") == "":
                        status = "observed"
                else:
                    signal = "incident"
                    opened, resolved, due = (
                        _time(row.get("opened_at")),
                        _time(row.get("resolved_at")),
                        _time(row.get("due_date")),
                    )
                    if opened is not None and opened <= now:
                        if resolved is not None and opened <= resolved <= now:
                            status = "observed"
                        elif (
                            row.get("resolved_at") == ""
                            and due is not None
                            and due < now
                            and row.get("active") in ("true", True)
                        ):
                            status = "open"
                result.append(
                    event(client, row["sys_id"], signal, status, attrs, now, tenant_id, path + "/" + row["sys_id"])
                )
        except (CollectionGapError, ValueError) as exc:
            error = exc if isinstance(exc, CollectionGapError) else gap(path, "invalid_response")
            result.append(
                event(client, path, "collection_gap", "not_evaluated", error.attributes(), now, tenant_id, path)
            )
    return result
