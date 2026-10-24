"""Lambda Cloud GPU instance exposure and access evidence collector (read-only).

Verified 2026-10-24 against the Lambda Cloud API OpenAPI document (version
1.10.0, ``https://cloud.lambda.ai/api/v1/openapi.json``) and the access and
security guide at docs.lambda.ai/public-cloud/access-security:

* Auth: ``Authorization: Bearer <api key>``. Lambda API keys carry full access
  to the API; this collector only ever issues ``GET``.
* ``GET /account`` scopes every asset to the account id.
* ``GET /instances`` pages when ``page_size`` (1-100) is sent and returns
  ``page_token`` (``null`` on the last page).
* ``GET /firewall-rulesets`` and ``GET /firewall-rulesets/global`` are unpaged.
  Rules carry ``protocol`` (``tcp``/``udp``/``icmp``/``all``), an optional
  inclusive ``port_range`` and an IPv4 ``source_network``. The API reference
  states that firewall rules do not apply in ``us-south-1``.
* ``GET /ssh-keys`` is unpaged; ``GET /api-keys`` pages like instances and needs
  the API-key read permission, so a refusal is a coverage gap.
* Responses use a ``{"data": ...}`` envelope; requests are limited to about one
  per second, so the client paces itself and retries 429 honoring
  ``Retry-After``.

Evidence:

* ``lambda_cloud.instance.network_exposure`` (``SG-NETWORK-001``): the global
  ruleset plus the instance's rulesets. Internet-open (``/0``) access to all
  protocols, all ports, SSH or RDP is open/high; another internet-open TCP/UDP
  port is open/medium; otherwise pass. ``us-south-1``, no public address, or
  rules that could not be read are ``not_evaluated``.
* ``lambda_cloud.instance.ssh_access`` (``SG-IDENTITY-001``): DSA keys and RSA
  keys under 2048 bits are open; strong keys stay ``observed`` because key
  strength alone does not establish logical access control.
* ``lambda_cloud.identity.api_key`` (``SG-IDENTITY-001``): a key without an
  expiry (open/medium) or unused for 90 days (open/low) is evidence against the
  identity that owns it; anything else stays ``observed``.

Every request goes to the fixed API host through the public-address egress
guard; a page token is only ever sent as a query value. Jupyter tokens, IP
addresses, host names, tags, rule descriptions, public key material, and
person names are dropped at the client.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import json
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from security_lakehouse import netguard
from security_lakehouse.connector_errors import CollectionGapError, ConnectorAccessError
from security_lakehouse.connector_ids import stable_id_slug
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows, paginate
from security_lakehouse.io import read_json
from security_lakehouse.models import utc_iso
from security_lakehouse.timeutil import parse_iso

SOURCE = "lambda_cloud"
API_BASE = "https://cloud.lambda.ai/api/v1"
DEFAULT_TIMEOUT = 30
MIN_REQUEST_INTERVAL = 1.0
PAGE_SIZE = 100
MAX_PAGES = 100

ACCOUNT_PATH = "/account"
INSTANCES_PATH = "/instances"
RULESETS_PATH = "/firewall-rulesets"
GLOBAL_RULESET_PATH = "/firewall-rulesets/global"
SSH_KEYS_PATH = "/ssh-keys"
API_KEYS_PATH = "/api-keys"

FIREWALL_UNSUPPORTED_REGIONS = frozenset({"us-south-1"})
ADMIN_PORTS = (22, 3389)
NOT_RUNNING = frozenset({"terminated", "terminating", "preempted"})
MIN_RSA_BITS = 2048
API_KEY_UNUSED_AFTER = timedelta(days=90)

NETWORK_SAFEGUARD = "SG-NETWORK-001"
ACCESS_SAFEGUARD = "SG-IDENTITY-001"
# Tags stay inside the bound safeguard's crosswalk; the CCF assessment reads
# the binding, never these hints.
NETWORK_CONTROLS = ["FEDRAMP-SC-7", "NIST-800-53-SC-7", "CMMC-3.13.6", "NIST-CSF-PR.IR-01"]
SSH_CONTROLS = ["NIST-800-53-IA-5.2", "FEDRAMP-IA-5.2", "NIST-800-53-IA-5"]
API_KEY_CONTROLS = ["NIST-800-53-IA-5", "FEDRAMP-IA-5", "SOC2-CC6.1"]

# Permission named in a coverage gap when a read is refused.
PERMISSIONS = {
    "firewall_rulesets": "read firewall rulesets",
    "global_firewall_ruleset": "read the global firewall ruleset",
    "ssh_keys": "read SSH keys",
    "api_keys": "read API keys (user and service identities)",
    "instances": "read instances",
    "account": "read the account",
}


def _rows(value: Any, collection: str) -> list[dict[str, Any]]:
    return object_rows(value, label=f"Lambda Cloud {collection}")


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _project_instance(item: dict[str, Any]) -> dict[str, Any]:
    region = _object(item.get("region"))
    itype = _object(item.get("instance_type"))
    image = _object(item.get("image"))
    rulesets = [str(r.get("id")) for r in item.get("firewall_rulesets") or [] if isinstance(r, dict) and r.get("id")]
    return {
        "id": str(item.get("id") or ""),
        "name": item.get("name"),
        "status": str(item.get("status") or "unknown"),
        "region": region.get("name"),
        "instance_type": itype.get("name"),
        "gpu_description": itype.get("gpu_description"),
        "image_family": image.get("family"),
        "ssh_key_names": [str(name) for name in item.get("ssh_key_names") or []],
        "firewall_ruleset_ids": rulesets,
        "has_public_ip": bool(item.get("ip")),
        "jupyter_url_present": bool(item.get("jupyter_url")),
    }


def _project_rule(rule: dict[str, Any]) -> dict[str, Any]:
    ports = rule.get("port_range")
    return {
        "protocol": str(rule.get("protocol") or ""),
        "port_range": list(ports) if isinstance(ports, list) and len(ports) == 2 else None,
        "source_network": str(rule.get("source_network") or ""),
    }


def _project_ruleset(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "rules": [_project_rule(rule) for rule in _rows(item.get("rules") or [], "firewall rules")],
        "instance_ids": [str(i) for i in item.get("instance_ids") or []],
    }


def ssh_key_strength(public_key: str) -> tuple[str, int | None, bool | None]:
    """``(algorithm, rsa_bits, weak)`` from an OpenSSH public key line; ``weak`` is None when unknown."""
    parts = str(public_key or "").split()
    if len(parts) < 2:
        return "unknown", None, None
    declared = parts[0]
    try:
        blob = base64.b64decode(parts[1], validate=True)
        fields = _ssh_fields(blob)
    except (binascii.Error, ValueError):
        return "unknown", None, None
    if not fields or fields[0].decode("ascii", "replace") != declared:
        return "unknown", None, None
    if declared == "ssh-dss":
        return declared, None, True
    if declared == "ssh-rsa":
        if len(fields) < 3:
            return "unknown", None, None
        bits = int.from_bytes(fields[2], "big").bit_length()
        return declared, bits, bits < MIN_RSA_BITS
    return declared, None, False


def _ssh_fields(blob: bytes) -> list[bytes]:
    fields: list[bytes] = []
    offset = 0
    while offset < len(blob):
        if offset + 4 > len(blob):
            raise ValueError("truncated SSH key")
        (length,) = struct.unpack(">I", blob[offset : offset + 4])
        offset += 4
        if offset + length > len(blob):
            raise ValueError("truncated SSH key")
        fields.append(blob[offset : offset + length])
        offset += length
    return fields


def _project_ssh_key(item: dict[str, Any]) -> dict[str, Any]:
    algorithm, bits, weak = ssh_key_strength(str(item.get("public_key") or ""))
    return {"name": str(item.get("name") or ""), "algorithm": algorithm, "bits": bits, "weak": weak}


def _project_key_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        field: item.get(field)
        for field in (
            "id",
            "name",
            "identity_id",
            "identity_type",
            "created_at",
            "expires_at",
            "last_used_at",
            "status",
        )
    }


def _data(payload: Any, collection: str) -> Any:
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError(f"Lambda Cloud {collection} collection incomplete: expected a data envelope")
    return payload["data"]


class LambdaCloudClient:
    """Authenticated, GET-only Lambda Cloud API client."""

    def __init__(
        self,
        *,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT,
        min_interval: float = MIN_REQUEST_INTERVAL,
        sleep: Callable[[float], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self.timeout = timeout
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def account(self) -> dict[str, Any]:
        data = _data(self._get(ACCOUNT_PATH, "account"), "account")
        if not isinstance(data, dict):
            raise ValueError("Lambda Cloud account collection incomplete: expected an object")
        return data

    def instances(self) -> list[dict[str, Any]]:
        return [_project_instance(item) for item in self._paged(INSTANCES_PATH, "instances")]

    def firewall_rulesets(self) -> list[dict[str, Any]]:
        data = _data(self._get(RULESETS_PATH, "firewall_rulesets"), "firewall_rulesets")
        return [_project_ruleset(item) for item in _rows(data, "firewall_rulesets")]

    def global_firewall_ruleset(self) -> dict[str, Any]:
        data = _data(self._get(GLOBAL_RULESET_PATH, "global_firewall_ruleset"), "global_firewall_ruleset")
        if not isinstance(data, dict):
            raise ValueError("Lambda Cloud global_firewall_ruleset collection incomplete: expected an object")
        return _project_ruleset(data)

    def ssh_keys(self) -> list[dict[str, Any]]:
        data = _data(self._get(SSH_KEYS_PATH, "ssh_keys"), "ssh_keys")
        return [_project_ssh_key(item) for item in _rows(data, "ssh_keys")]

    def key_records(self) -> list[dict[str, Any]]:
        return [_project_key_record(item) for item in self._paged(API_KEYS_PATH, "api_keys")]

    def _paged(self, path: str, collection: str) -> list[dict[str, Any]]:
        def fetch(token: str | None) -> Any:
            query: dict[str, Any] = {"page_size": PAGE_SIZE}
            if token:
                query["page_token"] = token
            return self._get(path, collection, query=query)

        def next_token(page: Any) -> str | None:
            token = page.get("page_token") if isinstance(page, dict) else None
            if token is not None and not isinstance(token, str):
                raise ValueError(f"Lambda Cloud {collection} collection incomplete: invalid page token")
            return token or None

        return list(
            paginate(fetch, lambda page: _rows(_data(page, collection), collection), next_token, max_pages=MAX_PAGES)
        )

    def _get(self, path: str, collection: str, *, query: dict[str, Any] | None = None) -> Any:
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "accept": "application/json",
                "authorization": f"Bearer {self._api_key}",
                "user-agent": "grc-lake",
            },
        )
        try:
            return backoff.retry(
                lambda: self._open(request),
                is_retryable=backoff.is_retryable_http,
                retry_after=backoff.http_retry_after,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise ConnectorAccessError("Lambda Cloud rejected the API key (HTTP 401)") from None
            if exc.code == 403:
                raise CollectionGapError(
                    f"Lambda Cloud {collection} were not collected (permission denied)",
                    collection=collection,
                    reason="permission_denied",
                    permission=PERMISSIONS.get(collection),
                ) from None
            raise ConnectorAccessError(f"Lambda Cloud {collection} read failed (HTTP {exc.code})") from None
        except urllib.error.URLError:
            raise ConnectorAccessError(f"Lambda Cloud {collection} read failed (network error)") from None

    def _open(self, request: urllib.request.Request) -> Any:
        self._pace()
        with netguard.open_public(request, timeout=self.timeout, label="lambda cloud") as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _pace(self) -> None:
        if self._last is not None and self._min_interval > 0:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                (self._sleep or time.sleep)(wait)
        self._last = self._clock()


class LambdaCloudFixtureClient:
    """Offline client over saved API responses (``{"data": ...}`` documents).

    ``account.json`` and ``instances.json`` are required. A missing optional file
    is a coverage gap, never an empty collection.
    """

    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture = Path(fixture_dir)

    def account(self) -> dict[str, Any]:
        data = _data(self._read("account", required=True), "account")
        if not isinstance(data, dict):
            raise ValueError("Lambda Cloud account collection incomplete: expected an object")
        return data

    def instances(self) -> list[dict[str, Any]]:
        data = _data(self._read("instances", required=True), "instances")
        return [_project_instance(item) for item in _rows(data, "instances")]

    def firewall_rulesets(self) -> list[dict[str, Any]]:
        data = _data(self._read("firewall_rulesets"), "firewall_rulesets")
        return [_project_ruleset(item) for item in _rows(data, "firewall_rulesets")]

    def global_firewall_ruleset(self) -> dict[str, Any]:
        data = _data(self._read("global_firewall_ruleset"), "global_firewall_ruleset")
        if not isinstance(data, dict):
            raise ValueError("Lambda Cloud global_firewall_ruleset collection incomplete: expected an object")
        return _project_ruleset(data)

    def ssh_keys(self) -> list[dict[str, Any]]:
        return [_project_ssh_key(item) for item in _rows(_data(self._read("ssh_keys"), "ssh_keys"), "ssh_keys")]

    def key_records(self) -> list[dict[str, Any]]:
        return [_project_key_record(item) for item in _rows(_data(self._read("api_keys"), "api_keys"), "api_keys")]

    def _read(self, collection: str, *, required: bool = False) -> Any:
        path = self.fixture / f"{collection}.json"
        if path.exists():
            return read_json(path)
        if required:
            raise ValueError(f"Lambda Cloud fixture is missing {collection}")
        raise CollectionGapError(
            f"Lambda Cloud {collection} were not collected (no fixture)",
            collection=collection,
            reason="not_collected",
            permission=PERMISSIONS.get(collection),
        )


def collect_lambda_cloud_evidence(
    client: LambdaCloudClient | LambdaCloudFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    """Two events per instance (network exposure, SSH access) plus one per API key."""
    now = collected_at or datetime.now(UTC)
    account_id = str(client.account().get("id") or "").strip()
    if not account_id:
        raise ValueError("Lambda Cloud account collection incomplete: missing account id")
    instances = client.instances()
    gaps: list[CollectionGapError] = []

    def optional(read: Callable[[], Any]) -> Any:
        try:
            return read()
        except CollectionGapError as gap:
            gaps.append(gap)
            return None

    rulesets = optional(client.firewall_rulesets)
    global_ruleset = optional(client.global_firewall_ruleset)
    ssh_keys = optional(client.ssh_keys)
    key_records = optional(client.key_records)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for instance in instances:
        instance_id = instance["id"]
        if not instance_id or instance_id in seen:
            continue
        seen.add(instance_id)
        rows.append(_exposure_event(account_id, instance, rulesets, global_ruleset, now, tenant_id))
        rows.append(_ssh_event(account_id, instance, ssh_keys, now, tenant_id))
    for record in key_records or []:
        if record.get("id") and record.get("identity_id"):
            rows.append(_key_record_event(account_id, record, now, tenant_id))
    rows.extend(_gap_event(account_id, gap, now, tenant_id) for gap in gaps)
    return rows


# --- Network exposure -------------------------------------------------------------


def _is_internet(source: str) -> bool:
    try:
        return ipaddress.ip_network(source, strict=False).prefixlen == 0
    except ValueError:
        # An unparseable source cannot be shown to restrict anything.
        return True


def _covers_admin(rule: dict[str, Any]) -> bool:
    if rule["protocol"] == "all":
        return True
    ports = rule["port_range"]
    if ports is None:
        return True
    low, high = ports
    return any(low <= port <= high for port in ADMIN_PORTS)


def _exposure_event(
    account_id: str,
    instance: dict[str, Any],
    rulesets: list[dict[str, Any]] | None,
    global_ruleset: dict[str, Any] | None,
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    open_rules: list[dict[str, Any]] = []
    rule_count = 0
    admin = False
    if instance["status"] in NOT_RUNNING:
        status, severity, reason = "observed", "info", "instance_not_running"
    elif instance["region"] in FIREWALL_UNSUPPORTED_REGIONS:
        status, severity, reason = "not_evaluated", "info", "firewall_not_applied_in_region"
    elif not instance["has_public_ip"]:
        status, severity, reason = "not_evaluated", "info", "no_public_ip_reported"
    elif rulesets is None or global_ruleset is None:
        status, severity, reason = "not_evaluated", "info", "firewall_rules_not_collected"
    else:
        attached = [
            rs
            for rs in rulesets
            if rs["id"] in instance["firewall_ruleset_ids"] or instance["id"] in rs["instance_ids"]
        ]
        for ruleset in [global_ruleset, *attached]:
            for rule in ruleset["rules"]:
                rule_count += 1
                if rule["protocol"] == "icmp" or not _is_internet(rule["source_network"]):
                    continue
                admin = admin or _covers_admin(rule)
                open_rules.append(
                    {"ruleset": ruleset["id"], "protocol": rule["protocol"], "port_range": rule["port_range"]}
                )
        if admin:
            status, severity, reason = "open", "high", "administrative_access_open_to_internet"
        elif open_rules:
            status, severity, reason = "open", "medium", "service_port_open_to_internet"
        else:
            status, severity, reason = "pass", "info", "inbound_restricted"
    return _event(
        account_id=account_id,
        key=instance["id"],
        entity=_instance_entity(account_id, instance["id"]),
        signal="instance.network_exposure",
        controls=NETWORK_CONTROLS,
        status=status,
        severity=severity,
        attributes={
            **_instance_attributes(account_id, instance),
            "effective_rule_count": rule_count,
            "internet_open_rules": open_rules,
            "finding_reason": reason,
        },
        evidence_ref=f"{API_BASE}{INSTANCES_PATH}/{urllib.parse.quote(instance['id'])}",
        safeguard_id=NETWORK_SAFEGUARD,
        now=now,
        tenant_id=tenant_id,
    )


# --- Access ----------------------------------------------------------------------


def _ssh_event(
    account_id: str,
    instance: dict[str, Any],
    ssh_keys: list[dict[str, Any]] | None,
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    catalog = {key["name"]: key for key in ssh_keys or []}
    keys = [
        catalog.get(name, {"name": name, "algorithm": "unknown", "bits": None, "weak": None})
        for name in instance["ssh_key_names"]
    ]
    if instance["status"] in NOT_RUNNING:
        status, severity, reason = "observed", "info", "instance_not_running"
    elif any(key["weak"] for key in keys):
        status, severity, reason = "open", "medium", "weak_ssh_key"
    elif ssh_keys is None:
        status, severity, reason = "not_evaluated", "info", "ssh_keys_not_collected"
    elif any(key["weak"] is None for key in keys):
        status, severity, reason = "not_evaluated", "info", "ssh_key_not_listed"
    else:
        status, severity, reason = "observed", "info", None
    return _event(
        account_id=account_id,
        key=instance["id"],
        entity=_instance_entity(account_id, instance["id"]),
        signal="instance.ssh_access",
        controls=SSH_CONTROLS,
        status=status,
        severity=severity,
        attributes={**_instance_attributes(account_id, instance), "ssh_keys": keys, "finding_reason": reason},
        evidence_ref=f"{API_BASE}{SSH_KEYS_PATH}",
        safeguard_id=ACCESS_SAFEGUARD,
        now=now,
        tenant_id=tenant_id,
    )


def _key_record_event(account_id: str, record: dict[str, Any], now: datetime, tenant_id: str) -> dict[str, Any]:
    expires = parse_iso(record.get("expires_at"), lenient=True)
    last_used = parse_iso(record.get("last_used_at"), lenient=True)
    created = parse_iso(record.get("created_at"), lenient=True)
    reference = last_used or created
    if str(record.get("status") or "").lower() == "expired" or (expires is not None and expires <= now):
        status, severity, reason = "observed", "info", "api_key_expired"
    elif record.get("expires_at") is None:
        status, severity, reason = "open", "medium", "api_key_without_expiration"
    elif reference is not None and now - reference > API_KEY_UNUSED_AFTER:
        status, severity, reason = "open", "low", "api_key_unused"
    else:
        status, severity, reason = "observed", "info", None
    identity_id = str(record["identity_id"])
    return _event(
        account_id=account_id,
        key=str(record["id"]),
        entity={
            "asset_id": f"{SOURCE}:{account_id}:identity:{identity_id}",
            "asset_type": "identity_account",
            "asset_owner": account_id,
            "environment": "prod",
            "org": account_id,
        },
        signal="identity.api_key",
        controls=API_KEY_CONTROLS,
        status=status,
        severity=severity,
        attributes={
            "account_id": account_id,
            "key_id": record.get("id"),
            "key_name": record.get("name"),
            "identity_id": identity_id,
            "identity_type": record.get("identity_type"),
            "created_at": record.get("created_at"),
            "expires_at": record.get("expires_at"),
            "last_used_at": record.get("last_used_at"),
            "key_status": record.get("status"),
            "unused_after_days": API_KEY_UNUSED_AFTER.days,
            "finding_reason": reason,
        },
        evidence_ref=f"{API_BASE}{API_KEYS_PATH}",
        safeguard_id=ACCESS_SAFEGUARD,
        now=now,
        tenant_id=tenant_id,
    )


# --- Event shape -------------------------------------------------------------------


def _instance_entity(account_id: str, instance_id: str) -> dict[str, Any]:
    return {
        "asset_id": f"{SOURCE}:{account_id}:instance:{instance_id}",
        "asset_type": "cloud_resource",
        "asset_owner": account_id,
        "environment": "prod",
        "org": account_id,
    }


def _instance_attributes(account_id: str, instance: dict[str, Any]) -> dict[str, Any]:
    return {
        "account_id": account_id,
        "instance_id": instance["id"],
        "instance_name": instance["name"],
        "instance_status": instance["status"],
        "region": instance["region"],
        "instance_type": instance["instance_type"],
        "gpu_description": instance["gpu_description"],
        "image_family": instance["image_family"],
        "ssh_key_names": instance["ssh_key_names"],
        "firewall_ruleset_ids": instance["firewall_ruleset_ids"],
        "has_public_ip": instance["has_public_ip"],
        "jupyter_url_present": instance["jupyter_url_present"],
    }


def _gap_event(account_id: str, gap: CollectionGapError, now: datetime, tenant_id: str) -> dict[str, Any]:
    """A coverage-gap row: an actionable open item that neither passes nor fails a control."""
    return _event(
        account_id=account_id,
        key=gap.collection,
        entity={
            "asset_id": f"{SOURCE}:{account_id}:collection:{gap.collection}",
            "asset_type": "collection_scope",
            "asset_owner": account_id,
            "environment": "prod",
            "org": account_id,
        },
        signal="collection_gap",
        controls=[],
        status="open",
        severity="low",
        attributes={"account_id": account_id, **gap.attributes()},
        evidence_ref=f"{SOURCE}:{account_id}:collection-gap:{gap.collection}",
        safeguard_id=None,
        now=now,
        tenant_id=tenant_id,
    )


def _event(
    *,
    account_id: str,
    key: str,
    entity: dict[str, Any],
    signal: str,
    controls: list[str],
    status: str,
    severity: str,
    attributes: dict[str, Any],
    evidence_ref: str,
    safeguard_id: str | None,
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    stable = stable_id_slug(f"{account_id}:{signal}:{key}", fallback=SOURCE)
    row: dict[str, Any] = {
        "event_id": f"{SOURCE}-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": SOURCE,
        "event_type": f"{SOURCE}.{signal}",
        "entity": entity,
        "severity": severity,
        "status": status,
        "controls": list(controls),
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": attributes,
    }
    if safeguard_id:
        row["safeguard_ids"] = [safeguard_id]
    return row


__all__ = [
    "API_BASE",
    "LambdaCloudClient",
    "LambdaCloudFixtureClient",
    "collect_lambda_cloud_evidence",
    "ssh_key_strength",
]
