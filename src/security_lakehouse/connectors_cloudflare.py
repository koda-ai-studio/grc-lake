"""Read-only Cloudflare zone configuration; API references in docs/CONNECTORS.md."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows
from security_lakehouse.io import canonical_sha256, read_json
from security_lakehouse.models import utc_iso

BASE = "https://api.cloudflare.com/client/v4/"
SETTINGS = ("min_tls_version", "always_use_https", "security_header", "dnssec", "managed_waf")
PATHS = {"dnssec": "dnssec", "managed_waf": "rulesets/phases/http_request_firewall_managed/entrypoint"}
BINDINGS = {
    "min_tls_version": ("SG-DATAPROTECTION-001", "SOC2-CC6.7"),
    "always_use_https": ("SG-DATAPROTECTION-001", "SOC2-CC6.7"),
    "security_header": ("SG-DATAPROTECTION-001", "SOC2-CC6.7"),
    "dnssec": ("SG-NETWORK-001", "PCI-DSS-1"),
    "managed_waf": ("SG-NETWORK-001", "PCI-DSS-1"),
}


def _gap(collection: str, reason: str) -> CollectionGapError:
    return CollectionGapError(
        "Cloudflare configuration collection incomplete", collection=collection, reason=reason, api="Cloudflare v4"
    )


class CloudflareClient:
    def __init__(self, *, token: str, max_pages: int = 100) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ConnectorConfigError("Cloudflare max_pages must be an integer from 1 to 1000")
        self._token = token
        self.max_pages = max_pages

    def get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            BASE + path, method="GET", headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label="cloudflare") as response:
                return read_json_response(response)

        try:
            payload = backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise _gap(path, f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise _gap(path, "unreadable_response") from None
        return _payload(payload, path)


class CloudflareFixtureClient:
    def __init__(self, fixture_dir: str | Path, *, max_pages: int = 100) -> None:
        self.responses = read_json(Path(fixture_dir) / "responses.json")
        self.max_pages = max_pages

    def get(self, path: str) -> dict[str, Any]:
        return _payload(self.responses.get(path), path)


def _payload(payload: Any, path: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("success") is not True or "result" not in payload:
        raise _gap(path, "invalid_response")
    return payload


def _zones(client: CloudflareClient | CloudflareFixtureClient) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for page in range(1, client.max_pages + 1):
        payload = client.get(f"zones?page={page}&per_page=50")
        rows = object_rows(payload["result"], label="Cloudflare zones")
        info = payload.get("result_info")
        if not isinstance(info, dict) or info.get("page") != page or type(info.get("total_pages")) is not int:
            raise _gap("zones", "invalid_pagination")
        total = info["total_pages"]
        if total < page and not (page == 1 and total == 0 and not rows):
            raise _gap("zones", "invalid_pagination")
        for row in rows:
            zone_id = row.get("id")
            if not isinstance(zone_id, str) or not re.fullmatch(r"[a-f0-9]{32}", zone_id):
                raise _gap("zones", "invalid_zone_id")
            if zone_id in result:
                raise _gap("zones", "duplicate_zone")
            result[zone_id] = row
        if page >= total:
            return list(result.values())
        if not rows:
            raise _gap("zones", "empty_intermediate_page")
    raise _gap("zones", "page_budget_exhausted")


def collect_cloudflare_evidence(
    client: CloudflareClient | CloudflareFixtureClient, *, tenant_id: str = "customer-managed"
) -> list[dict[str, Any]]:
    now = utc_iso(datetime.now(UTC))
    rows: list[dict[str, Any]] = []
    try:
        zones = _zones(client)
        if not zones:
            raise _gap("zones", "empty_scope")
    except (CollectionGapError, ValueError) as exc:
        gap = exc if isinstance(exc, CollectionGapError) else _gap("zones", "invalid_response")
        return [_event("scope", "collection_gap", "not_evaluated", gap.attributes(), now, tenant_id)]
    for zone in zones:
        zone_id = zone["id"]
        for setting in SETTINGS:
            path = f"zones/{zone_id}/{PATHS.get(setting, 'settings/' + setting)}"
            try:
                data = client.get(path)["result"]
                if not isinstance(data, dict):
                    raise _gap(path, "invalid_response")
                status, attrs = _evaluate(setting, data)
                if status == "not_evaluated":
                    attrs.update(_gap(path, "missing_or_unknown_configuration").attributes())
                # Paused and inactive zones do not establish deployed enforcement.
                if status == "pass" and (zone.get("status") != "active" or zone.get("paused") is not False):
                    status = "not_evaluated"
                    attrs.update(_gap(path, "zone_not_confirmed_active").attributes())
                rows.append(
                    _event(
                        zone_id,
                        setting,
                        status,
                        {**attrs, "zone_status": zone.get("status"), "paused": zone.get("paused")},
                        now,
                        tenant_id,
                    )
                )
            except (CollectionGapError, ValueError) as exc:
                gap = exc if isinstance(exc, CollectionGapError) else _gap(path, "invalid_response")
                rows.append(_event(zone_id, setting, "not_evaluated", gap.attributes(), now, tenant_id))
    return rows


def _evaluate(setting: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    value = data.get("value")
    if setting == "min_tls_version":
        return (
            {"1.0": "open", "1.1": "open", "1.2": "pass", "1.3": "pass"}.get(str(value), "not_evaluated"),
            {"minimum_tls_version": value},
        )
    if setting == "always_use_https":
        return ({"on": "pass", "off": "open"}.get(str(value), "not_evaluated"), {"always_use_https": value})
    if setting == "security_header":
        hsts = value.get("strict_transport_security") if isinstance(value, dict) else None
        hsts = hsts if isinstance(hsts, dict) else {}
        enabled, age = hsts.get("enabled"), hsts.get("max_age")
        status = "not_evaluated"
        if enabled is False or (enabled is True and type(age) is int and age == 0):
            status = "open"
        elif enabled is True and type(age) is int and age > 0:
            status = "pass"
        return status, {"hsts_enabled": enabled, "hsts_max_age": age}
    if setting == "dnssec":
        value = data.get("status")
        return (
            {"active": "pass", "disabled": "open", "pending": "not_evaluated", "pending-disabled": "not_evaluated"}.get(
                str(value), "not_evaluated"
            ),
            {"dnssec_status": value},
        )
    rules = object_rows(data.get("rules"), label="Cloudflare WAF")
    if any(not isinstance(r.get("action"), str) or type(r.get("enabled")) is not bool for r in rules):
        return "not_evaluated", {"rule_count": len(rules)}
    enabled = [r for r in rules if r.get("action") == "execute" and r.get("enabled") is True]
    # Deployment is an observation: expression scope, overrides and account rules
    # can change effective protection, which this bounded slice does not evaluate.
    return ("observed" if enabled else "open"), {
        "enabled_managed_ruleset_count": len(enabled),
        "rule_count": len(rules),
    }


def _event(zone_id: str, signal: str, status: str, attrs: dict[str, Any], now: str, tenant_id: str) -> dict[str, Any]:
    key = canonical_sha256([zone_id, signal])[:32]
    binding = BINDINGS.get(signal)
    row: dict[str, Any] = {
        "event_id": f"cloudflare-{key}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": now,
        "source": "cloudflare",
        "event_type": f"cloudflare.{signal}",
        "entity": {
            "asset_id": f"cloudflare:zone:{zone_id}",
            "asset_type": "network" if binding else "collection_scope",
            "asset_owner": "cloudflare",
            "environment": "prod",
        },
        "severity": "medium" if status == "open" else "info",
        "status": status,
        "controls": [binding[1]] if binding else [],
        "evidence": {
            "evidence_id": f"ev-cloudflare-{key}",
            "evidence_ref": BASE
            + (f"zones/{zone_id}/{PATHS.get(signal, 'settings/' + signal)}" if binding else "zones"),
            "evidence_collected_at": now,
        },
        "attributes": {"zone_id": zone_id, **attrs},
    }
    if binding:
        row["safeguard_ids"] = [binding[0]]
    return row


__all__ = ["CloudflareClient", "CloudflareFixtureClient", "collect_cloudflare_evidence"]
