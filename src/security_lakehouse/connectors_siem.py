"""SIEM alert export collector.

Read-only HTTP export against a customer's SIEM alert index. Emits detection
and incident-signal rows in the lake raw evidence shape for append-mode sync
with watermark cursors.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.ingestion.http_export import CursorExportClient
from security_lakehouse.io import read_json
from security_lakehouse.models import parse_event_time, utc_iso
from security_lakehouse.runtime_environment import runtime_env
from security_lakehouse.secret_refs import resolve_ref_or_default

CONNECTOR_ID = "siem-alerts"
SOURCE = "siem-alerts"
DEFAULT_CONTROLS = ["SOC2-CC7.2", "ISO27001-A.8.16"]
DEFAULT_TIMEOUT = 30
# Runaway guard on the cursor loop.
MAX_PAGES = 10_000
ITEM_KEYS = ("alerts", "items", "data")
OPEN_ALERT_STATES = frozenset({"new", "open", "in_progress", "triggered"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")


class SiemClient(CursorExportClient):
    """Read-only SIEM alert export client."""

    item_keys = ITEM_KEYS
    item_label = "siem"
    error_label = "SIEM"
    url_label = "siem export url"
    max_pages = MAX_PAGES

    def __init__(
        self,
        host: str,
        *,
        token: str,
        index: str = "alerts",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(host, token=token, timeout=timeout)
        self.index = _safe_scope(index)

    def alerts(self, *, since: str | None = None) -> list[dict[str, Any]]:
        base = f"{self.base_url}/api/v1/indexes/{self.index}/alerts"
        params = {"since": since} if since else {}
        return self._json_list_paginated(base, params)

    def list_indexes(self) -> list[str]:
        rows = self._json_list(f"{self.base_url}/api/v1/indexes")
        indexes: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                name = str(row.get("name") or row.get("index") or "").strip()
                if name:
                    indexes.append(name)
            elif isinstance(row, str) and row.strip():
                indexes.append(row.strip())
        return indexes

    def probe(self) -> dict[str, Any]:
        try:
            rows = self.alerts()
            return {
                "ok": True,
                "index": self.index,
                "alert_count": len(rows),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - probe surfaces sanitized errors
            return {
                "ok": False,
                "index": self.index,
                "alert_count": None,
                "error": exc.__class__.__name__,
            }

    def discover_scope(self) -> dict[str, Any]:
        indexes = self.list_indexes()
        selected = self.index or (indexes[0] if indexes else "alerts")
        selectors = [
            *[
                {
                    "kind": "index",
                    "name": name,
                    "required": False,
                    "selected": name == selected,
                }
                for name in indexes
            ],
        ]
        if selected and not any(item["name"] == selected for item in selectors):
            selectors.append(
                {"kind": "index", "name": selected, "required": True, "selected": True},
            )
        return {
            "ok": True,
            "selection_mode": "visible_indexes",
            "selectors": selectors,
            "recommended_options": {"index": selected},
        }


class SiemFixtureClient:
    """Offline client backed by JSON fixtures."""

    def __init__(self, fixture_dir: str | Path, *, index: str = "alerts") -> None:
        self.fixture = Path(fixture_dir)
        self.index = index

    def alerts(self, *, since: str | None = None) -> list[dict[str, Any]]:
        rows = self._read_alerts()
        if not since:
            return rows
        return [row for row in rows if str(row.get("event_time") or "") > since]

    def list_indexes(self) -> list[str]:
        return ["alerts", "detections"]

    def probe(self) -> dict[str, Any]:
        rows = self.alerts()
        return {
            "ok": True,
            "index": self.index,
            "alert_count": len(rows),
            "error": None,
        }

    def discover_scope(self) -> dict[str, Any]:
        indexes = self.list_indexes()
        selected = self.index or indexes[0]
        return {
            "ok": True,
            "selection_mode": "visible_indexes",
            "selectors": [
                {
                    "kind": "index",
                    "name": name,
                    "required": name == selected,
                    "selected": name == selected,
                }
                for name in indexes
            ],
            "recommended_options": {"index": selected},
        }

    def _read_alerts(self) -> list[dict[str, Any]]:
        path = self.fixture / "alerts.json"
        if not path.is_file():
            return []
        payload = read_json(path)
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []


def collect_siem_evidence(
    client: SiemClient | SiemFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Collect raw evidence rows from a SIEM alert export."""
    moment = collected_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for alert in client.alerts(since=since):
        event = _raw_from_alert(alert, collected_at=moment, tenant_id=tenant_id)
        if event is not None:
            rows.append(event)
    return rows


def probe_siem_access(
    *,
    credentials: dict[str, Any],
    options: dict[str, Any],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = runtime_env(env)
    host, token, index = _connection_params(credentials, options, env=env)
    if not host:
        raise ValueError("siem-alerts probe requires host")
    return SiemClient(host, token=token, index=index).probe()


def discover_siem_scope(
    *,
    credentials: dict[str, Any],
    options: dict[str, Any],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = runtime_env(env)
    host, token, index = _connection_params(credentials, options, env=env)
    if not host:
        return {"ok": False, "error": "host is required", "selectors": []}
    try:
        return SiemClient(host, token=token, index=index).discover_scope()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": exc.__class__.__name__, "selectors": []}


def _connection_params(
    credentials: dict[str, Any],
    options: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    env = runtime_env(env)
    environment = env or {}
    host = str(credentials.get("host") or environment.get("SIEM_EXPORT_URL") or "").strip()
    token = str(
        credentials.get("token")
        or resolve_ref_or_default(
            credentials.get("credential_ref"),
            "GRC_LAKE_SIEM_TOKEN",
            environment,
            field="credential_ref",
            file_first=False,
        )
        or ""
    ).strip()
    index = str(options.get("index") or "alerts").strip() or "alerts"
    return host, token, index


def _raw_from_alert(
    alert: dict[str, Any],
    *,
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any] | None:
    alert_id = str(alert.get("alert_id") or alert.get("id") or alert.get("event_id") or "").strip()
    event_time = _event_time_iso(alert.get("event_time") or alert.get("timestamp"))
    if not alert_id or not event_time:
        return None
    entity = alert.get("entity")
    if not isinstance(entity, dict):
        entity = {}
    asset_id = str(entity.get("asset_id") or alert.get("asset_id") or f"siem:alert:{alert_id}")
    controls = [str(item) for item in alert.get("controls") or DEFAULT_CONTROLS]
    alert_state = str(alert.get("alert_state") or alert.get("state") or "").lower()
    status = str(alert.get("status") or ("open" if alert_state in OPEN_ALERT_STATES else "observed"))
    severity = str(alert.get("severity") or "medium")
    return {
        "event_id": f"siem-{alert_id}",
        "tenant_id": str(alert.get("tenant_id") or tenant_id),
        "workspace_id": "default",
        "event_time": event_time,
        "source": SOURCE,
        "event_type": "detection.alert",
        "entity": {
            "asset_id": asset_id,
            "asset_type": str(entity.get("asset_type") or "security_asset"),
            "asset_owner": str(entity.get("owner") or entity.get("asset_owner") or "security-platform"),
            "environment": str(entity.get("environment") or "prod"),
            "org": SOURCE,
        },
        "severity": severity,
        "status": status,
        "controls": controls or list(DEFAULT_CONTROLS),
        "evidence": {
            "evidence_id": str(alert.get("evidence_id") or f"ev-siem-{alert_id}"),
            "evidence_ref": str(alert.get("evidence_ref") or f"siem://{alert_id}"),
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": {
            "rule": alert.get("rule"),
            "alert_state": alert_state or None,
            "linked_event": alert.get("linked_event"),
            "index": alert.get("index"),
        },
    }


def _event_time_iso(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return utc_iso(parse_event_time(text))
    except ValueError:
        return text.replace(" ", "T") + ("Z" if not text.endswith("Z") and "+" not in text else "")


def _safe_scope(value: str) -> str:
    text = str(value or "").strip()
    if not text or not IDENTIFIER.fullmatch(text):
        raise ValueError(f"unsafe SIEM index name {value!r}")
    return text
