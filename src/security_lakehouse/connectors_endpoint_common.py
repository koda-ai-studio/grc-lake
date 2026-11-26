"""Bounded read-only transport and evidence primitives for endpoint collectors."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.io import canonical_sha256
from security_lakehouse.models import utc_iso

__all__ = ["EndpointClient", "gap", "identity", "fresh", "event", "fields"]


def gap(collection: str, reason: str) -> CollectionGapError:
    return CollectionGapError("Endpoint collection incomplete", collection=collection, reason=reason, api="endpoint")


def identity(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
        raise ValueError("Invalid endpoint record identifier")
    return value


def fresh(value: Any, now: datetime) -> bool:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
        return stamp is not None and stamp.tzinfo is not None and timedelta(0) <= now - stamp <= timedelta(days=7)
    except ValueError:
        return False


def fields(record: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {
        name: record.get(name)
        for name in names
        if isinstance(record.get(name), (str, bool, int, float)) or record.get(name) is None
    }


class EndpointClient:
    synthetic = False

    def __init__(self, *, token: str, host: str, source: str, auth: str = "Bearer", max_pages: int = 100) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ConnectorConfigError("max_pages must be an integer from 1 to 1000")
        self.host, self.source, self.max_pages = host, source, max_pages
        self._token, self._auth = token, auth

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"https://{self.host}{path}",
            method="GET",
            headers={
                "Authorization": f"{self._auth} {self._token}",
                "Accept": "application/json",
            },
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label=self.source) as response:
                return read_json_response(response)

        try:
            return backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise gap(path.split("?")[0], f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise gap(path.split("?")[0], "unreadable_response") from None


def event(
    client: EndpointClient,
    record_id: str,
    asset_id: str,
    signal: str,
    status: str,
    attributes: dict[str, Any],
    now: datetime,
    tenant_id: str,
    path: str,
) -> dict[str, Any]:
    is_gap = signal == "collection_gap"
    safeguard = "SG-MALWARESCANNING-001" if signal == "protection" else "SG-DETECTION-001"
    key = canonical_sha256([tenant_id, client.host, record_id, signal])[:32]
    return {
        "event_id": f"{client.source}-{key}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": client.source,
        "event_type": f"{client.source}.{signal}",
        "entity": {
            "asset_id": f"{client.source}:{client.host}:{asset_id}",
            "asset_type": "collection_scope" if is_gap else "host",
            "asset_owner": client.host,
            "environment": "prod",
            "org": client.host,
        },
        "severity": "high" if status == "open" else "info",
        "status": status,
        "controls": [] if is_gap else ["NIST-800-53-SI-3" if signal == "protection" else "SOC2-CC7.2"],
        "safeguard_ids": [] if is_gap else [safeguard],
        "evidence": {
            "evidence_id": f"ev-{key}",
            "evidence_ref": f"https://{client.host}{path}",
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": {**attributes, "synthetic": client.synthetic},
    }
