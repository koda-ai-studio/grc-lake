"""Shared Microsoft Graph reads extracted from the Intune connector."""

from __future__ import annotations

import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import ConnectorConfigError
from security_lakehouse.execution_mode import in_server_mode
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows, paginate

GRAPH_HOST = "graph.microsoft.com"
GRAPH_SCOPE = f"https://{GRAPH_HOST}/.default"
DEFAULT_TIMEOUT = 20


class MicrosoftGraphClient:
    """Tenant-bound, GET-only Microsoft Graph collection transport."""

    def __init__(
        self,
        tenant_id: str,
        *,
        token_provider: Callable[[], str] | None = None,
        credential: Any = None,
        timeout: int = DEFAULT_TIMEOUT,
        label: str = "microsoft-graph",
    ) -> None:
        self.tenant_id = tenant_id
        self.timeout = timeout
        if token_provider is None and credential is not None:
            token_provider = _credential_token(credential)
        self._token_provider = token_provider or _default_credential_token(tenant_id, label)

    def collection(self, first_url: str) -> list[dict[str, Any]]:
        def fetch_page(url: str | None) -> dict[str, Any]:
            page_url = url or first_url
            parsed = urllib.parse.urlsplit(page_url)
            if parsed.scheme != "https" or parsed.netloc != GRAPH_HOST:
                raise ValueError("refusing URL outside https://graph.microsoft.com")
            payload = backoff.http_retry(lambda: self._get_json(page_url))
            if not isinstance(payload, dict):
                raise ValueError("Microsoft Graph returned non-object collection JSON")
            return payload

        def extract_items(page: dict[str, Any]) -> list[dict[str, Any]]:
            return object_rows(page.get("value"), label="Microsoft Graph")

        def next_cursor(page: dict[str, Any]) -> str | None:
            next_link = page.get("@odata.nextLink")
            if next_link is not None and not isinstance(next_link, str):
                raise ValueError("invalid Microsoft Graph pagination cursor")
            if not next_link:
                return None
            # fetch_page checks the origin before requesting any nextLink.
            return next_link

        return list(paginate(fetch_page, extract_items, next_cursor))

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "authorization": f"Bearer {self._token_provider()}",
                "user-agent": "grc-lake",
            },
        )
        with netguard.open_public(request, timeout=self.timeout, label="microsoft graph") as resp:
            return read_json_response(resp)


def _credential_token(credential: Any) -> Callable[[], str]:
    # A delegated credential is bound to its own Entra tenant.
    return lambda: str(credential.get_token(GRAPH_SCOPE).token)


def _default_credential_token(tenant_id: str, label: str) -> Callable[[], str]:
    if in_server_mode():
        raise ConnectorConfigError(
            f"{label} in hosted mode requires the tenant's app registration credentials; "
            "the server never collects with its own Azure identity"
        )
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:  # pragma: no cover - exercised only with live Graph
        raise RuntimeError(
            f"{label} live collection requires azure-identity; install the cloud extra or use --fixture-dir"
        ) from exc
    credential = DefaultAzureCredential()
    return lambda: str(credential.get_token(GRAPH_SCOPE, tenant_id=tenant_id).token)
