"""Safe JSON reads and scoped observations for monitoring and service management."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorConfigError
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.io import canonical_sha256, read_json
from security_lakehouse.models import utc_iso

__all__ = ["ReadClient", "FixtureReads", "gap", "record_id", "event"]
BINDINGS = {
    "log_index": ("SG-LOGGING-001", "SOC2-CC7.2"),
    "audit_trail": ("SG-LOGGING-001", "SOC2-CC7.2"),
    "monitor": ("SG-DETECTION-001", "SOC2-CC7.2"),
    "signal": ("SG-DETECTION-001", "SOC2-CC7.2"),
    "change": ("SG-CHANGEAPPROVAL-001", "SOC2-CC8.1"),
    "incident": ("SG-INCIDENTHANDLING-001", "NIST-CSF-RS.MA-01"),
}


def gap(path: str, reason: str) -> CollectionGapError:
    return CollectionGapError("Collection incomplete", collection=path, reason=reason, api="operations")


def record_id(value: Any) -> str:
    if type(value) not in (str, int) or not str(value).strip() or len(str(value)) > 512:
        raise ValueError("Missing or invalid record identity")
    return str(value)


class ReadClient:
    synthetic = False

    def __init__(self, *, host: str, source: str, headers: dict[str, str], max_pages: int = 100) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ConnectorConfigError("max_pages must be an integer from 1 to 1000")
        self.host, self.source, self.max_pages = host, source, max_pages
        self._headers = headers

    def get(self, path: str, query: dict[str, str]) -> Any:
        request = urllib.request.Request(
            f"https://{self.host}{path}?{urllib.parse.urlencode(query)}",
            method="GET",
            headers={**self._headers, "Accept": "application/json"},
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label=self.source) as response:
                return read_json_response(response)

        try:
            return backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise gap(path, f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise gap(path, "unreadable_response") from None


class FixtureReads:
    synthetic = True
    responses: dict[str, Any]

    def load(self, fixture_dir: str | Path) -> None:
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, path: str, query: dict[str, str]) -> Any:
        paging = {k: v for k, v in query.items() if k in ("page[cursor]", "page", "sysparm_offset") and v != "0"}
        key = path + ("?" + urllib.parse.urlencode(paging) if paging else "")
        if key not in self.responses:
            raise gap(path, "fixture_missing")
        return self.responses[key]


def event(
    client: ReadClient, key: str, signal: str, status: str, attrs: dict[str, Any], now: datetime, tenant: str, path: str
) -> dict[str, Any]:
    digest = canonical_sha256([tenant, client.host, signal, key])[:32]
    binding = BINDINGS.get(signal)
    return {
        "event_id": f"{client.source}-{digest}",
        "tenant_id": tenant,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": client.source,
        "event_type": f"{client.source}.{signal}",
        "entity": {
            "asset_id": f"{client.source}:{client.host}:{signal}:{key}",
            "asset_type": "service" if binding else "collection_scope",
            "asset_owner": client.host,
            "environment": "prod",
            "org": client.host,
        },
        "status": status,
        "severity": "medium" if status == "open" else "info",
        "controls": [binding[1]] if binding else [],
        "safeguard_ids": [binding[0]] if binding else [],
        "evidence": {
            "evidence_id": f"ev-{digest}",
            "evidence_ref": f"https://{client.host}{path}",
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": {**attrs, "synthetic": client.synthetic},
    }
