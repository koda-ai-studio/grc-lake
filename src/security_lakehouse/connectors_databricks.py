"""Databricks evidence-lake collector.

An existing-lake reader, like ``snowflake-evidence-lake``: GRC Lake reads the
same four GRC Lake evidence views (``GRC_LAKE_AUDIT_EVENTS``,
``GRC_LAKE_CONTROL_POSTURE``, ``GRC_LAKE_ASSET_RISK``,
``GRC_LAKE_EVIDENCE_BUNDLES``) from a Unity Catalog schema and never creates,
updates, or deletes workspace objects. ``deploy/databricks/bootstrap_poc.sql``
provisions the views over ``system.access.audit``.

Reads go through the Databricks SQL Statement Execution API
(``/api/2.0/sql/statements``) on a SQL warehouse, so no Databricks SDK or
driver dependency is needed. Authentication is OAuth machine-to-machine: a
service principal's client id and secret mint a one-hour workspace token at
``/oidc/v1/token`` (``grant_type=client_credentials``, ``scope=all-apis``).
Least privilege is ``CAN USE`` on the warehouse plus ``USE CATALOG``,
``USE SCHEMA``, and ``SELECT`` on the evidence views; on SQL warehouses the
view owner's permissions govern the underlying system tables.

Every request goes to the configured workspace host only: the host must be a
Databricks workspace domain, result chunk links must be relative paths or stay
on that host, and catalog/schema/view names are strict identifiers quoted with
backticks.
"""

from __future__ import annotations

import base64
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connectors_snowflake import DEFAULT_VIEWS, collect_snowflake_evidence
from security_lakehouse.http_response import read_json_response
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import IncompleteCollectionError, paginate
from security_lakehouse.io import read_json
from security_lakehouse.lake_mapping import MappingSpec, compile_select, read_fixture_table

CONNECTOR_ID = "databricks-evidence-lake"
SOURCE = "databricks"
WORKSPACE_HOST_SUFFIXES = (".cloud.databricks.com", ".azuredatabricks.net", ".gcp.databricks.com")
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]{1,255}$")
DEFAULT_TIMEOUT = 60
WAIT_TIMEOUT = "30s"
POLL_SECONDS = 2.0
MAX_POLLS = 150
PENDING_STATES = {"PENDING", "RUNNING"}


def validate_workspace_host(host: str) -> str:
    value = str(host or "").strip().lower()
    if not _HOST.fullmatch(value) or not value.endswith(WORKSPACE_HOST_SUFFIXES):
        raise ValueError(
            "host must be a bare Databricks workspace hostname "
            "(*.cloud.databricks.com, *.azuredatabricks.net, or *.gcp.databricks.com)"
        )
    return value


def validate_identifier(name: str) -> str:
    value = str(name or "").strip()
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid Unity Catalog identifier {name!r}: use letters, digits, and underscores only")
    return value


class DatabricksClient:
    """Read-only client for GRC Lake evidence views on a Databricks SQL warehouse."""

    def __init__(
        self,
        host: str,
        *,
        client_id: str,
        client_secret: str,
        warehouse_id: str,
        catalog: str,
        schema: str,
        views: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = validate_workspace_host(host)
        self.account = self.host
        self._basic = "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self.warehouse_id = validate_identifier(warehouse_id)
        self.catalog = validate_identifier(catalog)
        self.schema = validate_identifier(schema)
        self.views = {key: validate_identifier(name) for key, name in (views or DEFAULT_VIEWS).items()}
        self.timeout = timeout
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires_at = 0.0

    def audit_events(self) -> list[dict[str, Any]]:
        return self._select_view("audit_events")

    def control_posture(self) -> list[dict[str, Any]]:
        return self._select_view("control_posture")

    def asset_risk(self) -> list[dict[str, Any]]:
        return self._select_view("asset_risk")

    def evidence_bundles(self) -> list[dict[str, Any]]:
        return self._select_view("evidence_bundles")

    def fetch_mapping_rows(self, spec: MappingSpec, *, since: str | None, limit: int) -> list[dict[str, Any]]:
        """Read a customer table through a mapping spec with named ``:param`` markers.

        A one-part table name is qualified with the configured catalog and schema.
        """
        query = compile_select(
            spec, "databricks", since=since, limit=limit, default_namespace=(self.catalog, self.schema)
        )
        return self._execute(query.sql, query.databricks_parameters(), collection=spec.name)

    def _select_view(self, key: str) -> list[dict[str, Any]]:
        statement = f"SELECT * FROM `{self.catalog}`.`{self.schema}`.`{self.views[key]}`"  # noqa: S608
        return self._execute(statement, [], collection=key)

    def _execute(self, statement: str, parameters: list[dict[str, str]], *, collection: str) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "statement": statement,
            "warehouse_id": self.warehouse_id,
            "wait_timeout": WAIT_TIMEOUT,
            "on_wait_timeout": "CONTINUE",
            "disposition": "INLINE",
            "format": "JSON_ARRAY",
        }
        if parameters:
            body["parameters"] = parameters
        response = self._await(self._request("POST", "/api/2.0/sql/statements", body))

        def incomplete(detail: str) -> CollectionGapError:
            return CollectionGapError(
                f"Databricks result incomplete: {detail}",
                collection=collection,
                reason="incomplete_result",
                api="sql.statements",
            )

        manifest = response.get("manifest")
        if not isinstance(manifest, dict) or not isinstance(manifest.get("schema"), dict):
            raise incomplete("missing result schema")
        if manifest.get("truncated", False) is not False:
            raise incomplete("result was truncated")
        if manifest.get("format", "JSON_ARRAY") != "JSON_ARRAY":
            raise incomplete("unexpected result format")
        definitions = manifest["schema"].get("columns")
        if not isinstance(definitions, list) or not definitions:
            raise incomplete("missing result columns")
        columns: list[str] = []
        for column in definitions:
            name = column.get("name") if isinstance(column, dict) else None
            if not isinstance(name, str) or not name.strip():
                raise incomplete("invalid result columns")
            columns.append(name)
        if len(set(columns)) != len(columns):
            raise incomplete("duplicate result columns")
        total = manifest.get("total_row_count")
        if "total_row_count" in manifest and (type(total) is not int or total < 0):
            raise incomplete("invalid total row count")
        first = response.get("result")
        if first is None and total == 0:
            first = {"data_array": []}
        if not isinstance(first, dict):
            raise incomplete("missing result data")
        received = 0

        def fetch_page(link: str | None) -> dict[str, Any]:
            return first if link is None else self._request("GET", link)

        def extract_items(page: dict[str, Any]) -> list[dict[str, Any]]:
            nonlocal received
            rows = page.get("data_array")
            if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
                raise incomplete("row data does not match the result schema")
            for key, expected in (("row_count", len(rows)), ("row_offset", received)):
                if key in page and (type(page[key]) is not int or page[key] != expected):
                    raise incomplete("chunk row count or offset does not match the result")
            received += len(rows)
            return [dict(zip(columns, row, strict=True)) for row in rows]

        def next_cursor(page: dict[str, Any]) -> str | None:
            index = page.get("next_chunk_index")
            if index is not None and (type(index) is not int or index < 0):
                raise incomplete("invalid next chunk index")
            link = page.get("next_chunk_internal_link")
            if link is not None:
                if not isinstance(link, str) or not link or any(char.isspace() for char in link) or "\\" in link:
                    raise incomplete("invalid result chunk link")
                try:
                    parsed = urllib.parse.urlparse(link)
                    if (parsed.scheme or parsed.netloc) and (
                        parsed.scheme != "https"
                        or parsed.hostname != self.host
                        or parsed.port not in (None, 443)
                        or parsed.username is not None
                    ):
                        raise ValueError
                    if not parsed.path.startswith("/") or parsed.path.startswith("//") or parsed.fragment:
                        raise ValueError
                except ValueError:
                    raise incomplete("invalid result chunk link") from None
                return parsed.path + (f"?{parsed.query}" if parsed.query else "")
            if index is None:
                return None
            statement_id = response.get("statement_id")
            if not isinstance(statement_id, str) or not statement_id:
                raise incomplete("missing statement identifier for the next chunk")
            identifier = urllib.parse.quote(statement_id, safe="")
            return f"/api/2.0/sql/statements/{identifier}/result/chunks/{index}"

        try:
            rows = list(paginate(fetch_page, extract_items, next_cursor))
        except IncompleteCollectionError:
            raise incomplete("result pagination did not finish") from None
        if total is not None and len(rows) != total:
            raise incomplete("received row count does not match the result total")
        return rows

    def _await(self, response: dict[str, Any]) -> dict[str, Any]:
        statement_id = urllib.parse.quote(str(response.get("statement_id") or ""), safe="")
        for _ in range(MAX_POLLS):
            status = response.get("status") or {}
            state = str(status.get("state") or "")
            if state == "SUCCEEDED":
                return response
            if state not in PENDING_STATES:
                message = str((status.get("error") or {}).get("message") or state or "unknown state")
                raise RuntimeError(f"Databricks statement did not succeed: {message}")
            self._sleep(POLL_SECONDS)
            response = self._request("GET", f"/api/2.0/sql/statements/{statement_id}")
        raise RuntimeError("Databricks statement did not finish within the polling budget")

    def _bearer(self) -> str:
        if self._token is None or time.monotonic() >= self._token_expires_at:
            requested_at = time.monotonic()
            request = urllib.request.Request(
                f"https://{self.host}/oidc/v1/token",
                data=b"grant_type=client_credentials&scope=all-apis",
                method="POST",
                headers={
                    "authorization": self._basic,
                    "content-type": "application/x-www-form-urlencoded",
                    "accept": "application/json",
                    "user-agent": "grc-lake",
                },
            )
            payload = backoff.http_retry(lambda: self._open(request))
            token = str((payload or {}).get("access_token") or "")
            if not token:
                raise RuntimeError("Databricks OAuth token response did not include an access_token")
            lifetime = payload.get("expires_in", 3600)
            if (
                type(lifetime) not in (int, float)
                or lifetime <= 0
                or (isinstance(lifetime, float) and not math.isfinite(lifetime))
            ):
                raise RuntimeError("Databricks OAuth token response has an invalid lifetime")
            lifetime = min(lifetime, 3600)
            self._token_expires_at = requested_at + lifetime - min(30, lifetime / 10)
            self._token = token
        return self._token

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        def send() -> Any:
            request = urllib.request.Request(
                f"https://{self.host}{path}",
                data=json.dumps(body).encode("utf-8") if body is not None else None,
                method=method,
                headers={
                    "authorization": f"Bearer {self._bearer()}",
                    "content-type": "application/json",
                    "accept": "application/json",
                    "user-agent": "grc-lake",
                },
            )
            return self._open(request)

        try:
            payload = backoff.http_retry(send)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
            self._token = None
            payload = backoff.http_retry(send)
        if not isinstance(payload, dict):
            raise ValueError("Databricks returned non-object JSON")
        return payload

    def _open(self, request: urllib.request.Request) -> Any:
        with netguard.open_public(request, timeout=self.timeout, label="databricks workspace") as resp:
            return read_json_response(resp)


class DatabricksFixtureClient:
    """Offline client reading the four evidence views from JSON fixtures."""

    def __init__(self, fixture_dir: str | Path, *, host: str) -> None:
        self.fixture = Path(fixture_dir)
        self.account = validate_workspace_host(host)

    def audit_events(self) -> list[dict[str, Any]]:
        return self._read("audit_events.json")

    def control_posture(self) -> list[dict[str, Any]]:
        return self._read("control_posture.json")

    def asset_risk(self) -> list[dict[str, Any]]:
        return self._read("asset_risk.json")

    def evidence_bundles(self) -> list[dict[str, Any]]:
        return self._read("evidence_bundles.json")

    def fetch_mapping_rows(self, spec: MappingSpec, *, since: str | None, limit: int) -> list[dict[str, Any]]:
        _ = since, limit  # fixtures return the whole table; map_rows applies the same bound
        return read_fixture_table(self.fixture, spec.source_table)

    def _read(self, name: str) -> list[dict[str, Any]]:
        path = self.fixture / name
        payload = read_json(path) if path.exists() else []
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def collect_databricks_evidence(
    client: DatabricksClient | DatabricksFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    return collect_snowflake_evidence(
        client, account=client.account, collected_at=collected_at, tenant_id=tenant_id, source=SOURCE
    )
