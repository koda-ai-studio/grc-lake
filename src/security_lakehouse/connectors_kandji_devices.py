"""Read-only Kandji/Iru device snapshots using the documented US and EU hosts."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.connectors_jamf import SIGNAL_CONTROLS
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows
from security_lakehouse.io import canonical_sha256, read_json
from security_lakehouse.models import utc_iso

CONNECTOR_ID = "kandji-devices"
TOKEN_ENV = "KANDJI_API_TOKEN"
HOST_SUFFIXES = {"us": "api.kandji.io", "eu": "api.eu.kandji.io"}
STALE_AFTER = timedelta(days=30)


def _gap(collection: str, reason: str) -> CollectionGapError:
    return CollectionGapError("Kandji collection incomplete", collection=collection, reason=reason, api="Kandji")


def _id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
        raise ValueError("Invalid Kandji identifier")
    return value


class KandjiDevicesClient:
    def __init__(self, *, token: str, subdomain: str, region: str = "us", max_pages: int = 100) -> None:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", subdomain) or region not in HOST_SUFFIXES:
            raise ConnectorConfigError("Kandji requires a tenant subdomain and region us or eu")
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ConnectorConfigError("Kandji max_pages must be an integer from 1 to 1000")
        self.host, self.max_pages, self._token = f"{subdomain}.{HOST_SUFFIXES[region]}", max_pages, token

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"https://{self.host}{path}",
            method="GET",
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label=CONNECTOR_ID) as response:
                return read_json_response(response)

        try:
            return backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise _gap(path, f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise _gap(path, "unreadable_response") from None


class KandjiDevicesFixtureClient(KandjiDevicesClient):
    def __init__(self, fixture_dir: str | Path, *, subdomain: str, region: str = "us", max_pages: int = 100) -> None:
        super().__init__(token="", subdomain=subdomain, region=region, max_pages=max_pages)
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, path: str) -> Any:
        if path not in self.responses:
            raise _gap(path, "fixture_missing")
        return self.responses[path]


def _list(client: KandjiDevicesClient, path: str, *, prism: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursors: set[str] = set()
    cursor: str | None = None
    for page in range(client.max_pages):
        query = {"limit": "300", "cursor" if cursor else "offset": cursor or str(page * 300)}
        payload = client.get(f"{path}?{urllib.parse.urlencode(query)}")
        if prism and not isinstance(payload, dict):
            raise _gap(path, "invalid_prism_page")
        chunk = object_rows(payload.get("data") if prism else payload, label="Kandji")
        if len(chunk) > 300:
            raise _gap(path, "invalid_page_size")
        for row in chunk:
            identity = _id(row.get("device_id"))
            if identity in seen:
                raise _gap(path, "duplicate_device_id")
            seen.add(identity)
        rows.extend(chunk)
        if prism:
            cursor = payload.get("cursor")
            if cursor is not None:
                if not isinstance(cursor, str) or not cursor or cursor in cursors or len(cursor) > 4096:
                    raise _gap(path, "invalid_cursor")
                cursors.add(cursor)
                continue
            total = payload.get("total")
            if total is not None and (type(total) is not int or total != len(rows)):
                raise _gap(path, "population_count_mismatch")
            if len(chunk) < 300 or total == len(rows):
                return rows
        elif len(chunk) < 300:
            return rows
    raise _gap(path, "page_budget_exhausted")


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
        return parsed if parsed is not None and parsed.tzinfo is not None else None
    except ValueError:
        return None


def _fresh(value: Any, now: datetime) -> bool:
    timestamp = _time(value)
    return timestamp is not None and timedelta(0) <= now - timestamp <= STALE_AFTER


def collect_kandji_devices_evidence(
    client: KandjiDevicesClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    screen_lock_parameter_id: str = "",
    os_patch_parameter_id: str = "",
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    parameters = {"screen_lock": screen_lock_parameter_id, "os_patch": os_patch_parameter_id}
    try:
        for parameter_id in parameters.values():
            if parameter_id:
                _id(parameter_id)
    except ValueError:
        raise ConnectorConfigError("Kandji policy parameter IDs must be lowercase UUIDs") from None
    rows: list[dict[str, Any]] = []

    def gap(collection: str, exc: Exception) -> None:
        error = exc if isinstance(exc, CollectionGapError) else _gap(collection, "invalid_response")
        rows.append(_event(client, collection, "collection_gap", "not_evaluated", error.attributes(), now, tenant_id))

    try:
        devices = _list(client, "/api/v1/devices")
        if not devices:
            raise _gap("devices", "empty_scope")
    except (CollectionGapError, ValueError) as exc:
        gap("devices", exc)
        return rows
    try:
        firewalls = {r["device_id"]: r for r in _list(client, "/api/v1/prism/application_firewall", prism=True)}
    except (CollectionGapError, ValueError) as exc:
        gap("application_firewall", exc)
        firewalls = {}
    for device in devices:
        identity = device["device_id"]
        base = {
            "device_id": identity,
            "device_type": device.get("platform"),
            "os_version": device.get("os_version"),
            "last_contact": device.get("last_check_in"),
            "managed": device.get("mdm_enabled"),
        }
        details: dict[str, Any] = {}
        policy: dict[str, str] = {}
        if device.get("platform") == "Mac":
            try:
                details = client.get(f"/api/v1/devices/{identity}/details")
                if (
                    not isinstance(details, dict)
                    or not isinstance(details.get("general"), dict)
                    or details["general"].get("device_id") != identity
                ):
                    raise _gap(identity, "mismatched_device_details")
            except (CollectionGapError, ValueError) as exc:
                gap(f"details:{identity}", exc)
                details = {}
            if any(parameters.values()):
                try:
                    payload = client.get(f"/api/v1/devices/{identity}/parameters")
                    if not isinstance(payload, dict) or payload.get("device_id") != identity:
                        raise _gap(identity, "mismatched_device_parameters")
                    for item in object_rows(payload.get("parameters"), label="Kandji"):
                        key = _id(item.get("item_id"))
                        if key in policy or not isinstance(item.get("status"), str):
                            raise _gap(identity, "invalid_parameters")
                        policy[key] = item["status"]
                except (CollectionGapError, ValueError) as exc:
                    gap(f"parameters:{identity}", exc)
                    policy = {}
        filevault = details.get("filevault")
        encryption = filevault.get("filevault_enabled") if isinstance(filevault, dict) else None
        firewall = firewalls.get(identity, {})
        values = {"management": device.get("mdm_enabled"), "encryption": encryption, "firewall": firewall.get("status")}
        for signal, parameter in parameters.items():
            state = policy.get(parameter)
            values[signal] = True if state == "PASS" else False if state == "ERROR" else None
        for signal, value in values.items():
            status = "pass" if value is True else "open" if value is False else "not_evaluated"
            reason = "configuration_not_reported" if status == "not_evaluated" else None
            if device.get("platform") != "Mac":
                status, reason = "not_evaluated", "unsupported_platform"
            elif not _fresh(device.get("last_check_in"), now):
                status, reason = "not_evaluated", "stale_or_unknown_check_in"
            elif signal == "firewall" and not _fresh(firewall.get("last_collected_at"), now):
                status, reason = "not_evaluated", "stale_or_unknown_firewall_inventory"
            attrs = {**base, "finding_reason": reason, "reported_value": value if type(value) is bool else None}
            if signal in parameters:
                attrs.update(parameter_id=parameters[signal] or None, parameter_status=policy.get(parameters[signal]))
            if status == "not_evaluated":
                attrs.update(_gap(f"{identity}:{signal}", reason or "unknown").attributes())
            rows.append(_event(client, identity, signal, status, attrs, now, tenant_id))
    return rows


def _event(
    client: KandjiDevicesClient,
    identity: str,
    signal: str,
    status: str,
    attrs: dict[str, Any],
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    key = canonical_sha256([client.host, identity, signal])[:32]
    is_gap = signal == "collection_gap"
    return {
        "event_id": f"kandji-{key}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": "kandji",
        "event_type": f"kandji.device.{signal}",
        "entity": {
            "asset_id": f"kandji:{client.host}:{identity}",
            "asset_type": "collection_scope" if is_gap else "managed_device",
            "asset_owner": client.host,
            "environment": "prod",
            "org": client.host,
        },
        "severity": "medium" if status == "open" else "info",
        "status": status,
        "controls": list(SIGNAL_CONTROLS[signal]) if not is_gap else [],
        "safeguard_ids": ["SG-ENDPOINTENCRYPTION-001"] if signal == "encryption" else [],
        "evidence": {
            "evidence_id": f"ev-{key}",
            "evidence_ref": f"https://{client.host}/api/v1/devices" + ("" if is_gap else f"/{identity}"),
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": attrs,
    }
