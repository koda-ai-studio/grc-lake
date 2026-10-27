"""Microsoft Intune device-posture evidence collector.

Collects read-only managed-device posture — disk encryption, compliance state,
and jailbreak/root detection — from Microsoft Graph
``GET /deviceManagement/managedDevices`` and emits it in the lake's raw
evidence shape.

Two clients sit behind one interface, mirroring ``connectors_azure``:

* :class:`IntuneClient` — bearer-authenticated ``urllib`` reads against
  Microsoft Graph v1.0. The token comes from the tenant's own app registration
  when one is configured (see :func:`security_lakehouse.delegation.azure_credential`;
  required in hosted server mode), and otherwise locally from
  ``DefaultAzureCredential``, scoped to Graph. Requires the application
  permission ``DeviceManagementManagedDevices.Read.All``.
* :class:`IntuneFixtureClient` — reads ``managed_devices.json`` from a fixture
  directory.

Data minimization: the list request uses ``$select`` for posture fields only,
so hardware identifiers (IMEI, serial, MAC), phone numbers, display names, and
admin notes are never fetched. ``userPrincipalName`` is kept as the join key to
identity-provider users.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse.connector_ids import stable_id_slug
from security_lakehouse.ingestion.microsoft_graph import GRAPH_HOST, MicrosoftGraphClient
from security_lakehouse.ingestion.microsoft_graph import GRAPH_SCOPE as GRAPH_SCOPE
from security_lakehouse.io import read_json
from security_lakehouse.models import utc_iso

SELECT_FIELDS = (
    "id",
    "deviceName",
    "userPrincipalName",
    "operatingSystem",
    "osVersion",
    "isEncrypted",
    "complianceState",
    "jailBroken",
    "lastSyncDateTime",
    "enrolledDateTime",
    "managedDeviceOwnerType",
    "managementAgent",
    "azureADDeviceId",
    "isSupervised",
)
GRAPH_MANAGED_DEVICES_URL = (
    f"https://{GRAPH_HOST}/v1.0/deviceManagement/managedDevices?$select={','.join(SELECT_FIELDS)}"
)

# Controls verified to exist in controls/catalog.json.
ENCRYPTION_CONTROLS = ["NIST-800-53-SC-28.1"]
COMPLIANCE_CONTROLS = ["FEDRAMP-AC-19", "CMMC-3.1.18", "SOC2-CC6.8", "ISO27001-A.8.1"]

# Graph complianceState values that are a policy failure, not merely unknown.
FAILED_COMPLIANCE_STATES = {"noncompliant", "conflict", "error"}


class IntuneClient(MicrosoftGraphClient):
    """Read Intune posture through the shared tenant-bound Graph transport."""

    def __init__(self, tenant_id: str, **kwargs: Any) -> None:
        super().__init__(tenant_id, label="intune-devices", **kwargs)

    def managed_devices(self) -> list[dict[str, Any]]:
        return self.collection(GRAPH_MANAGED_DEVICES_URL)


class IntuneFixtureClient:
    """Offline Intune client backed by a fixture directory."""

    def __init__(self, fixture_dir: str | Path, *, tenant_id: str) -> None:
        self.fixture = Path(fixture_dir)
        self.tenant_id = tenant_id

    def managed_devices(self) -> list[dict[str, Any]]:
        path = self.fixture / "managed_devices.json"
        payload = read_json(path) if path.exists() else []
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def collect_intune_evidence(
    client: IntuneClient | IntuneFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    """Emit one encryption event and one compliance event per managed device."""
    now = collected_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for device in client.managed_devices():
        device_id = str(device.get("id") or "").strip()
        if not device_id:
            continue
        attributes = _device_attributes(device_id, device)
        rows.append(_encryption_event(client.tenant_id, device_id, attributes, now, tenant_id))
        rows.append(_compliance_event(client.tenant_id, device_id, attributes, now, tenant_id))
    return rows


def _device_attributes(device_id: str, device: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "device_name": device.get("deviceName"),
        "user_principal_name": device.get("userPrincipalName"),
        "operating_system": device.get("operatingSystem"),
        "os_version": device.get("osVersion"),
        "owner_type": device.get("managedDeviceOwnerType"),
        "management_agent": device.get("managementAgent"),
        "azure_ad_device_id": device.get("azureADDeviceId"),
        "is_supervised": device.get("isSupervised"),
        "last_sync": device.get("lastSyncDateTime"),
        "enrolled": device.get("enrolledDateTime"),
        "is_encrypted": device.get("isEncrypted") if isinstance(device.get("isEncrypted"), bool) else None,
        "compliance_state": str(device.get("complianceState") or "unknown"),
        "jailbroken": str(device.get("jailBroken") or "").lower() == "true",
    }


def _encryption_event(
    graph_tenant: str, device_id: str, attributes: dict[str, Any], collected_at: datetime, tenant_id: str
) -> dict[str, Any]:
    encrypted = attributes["is_encrypted"]
    status = "pass" if encrypted is True else "open" if encrypted is False else "not_evaluated"
    return _event(
        graph_tenant=graph_tenant,
        device_id=device_id,
        signal="encryption",
        controls=ENCRYPTION_CONTROLS,
        status=status,
        severity="high" if encrypted is False else "info",
        attributes={
            **attributes,
            "finding_reason": None
            if encrypted is True
            else "not_encrypted"
            if encrypted is False
            else "encryption_not_reported",
        },
        collected_at=collected_at,
        tenant_id=tenant_id,
    )


def _compliance_event(
    graph_tenant: str, device_id: str, attributes: dict[str, Any], collected_at: datetime, tenant_id: str
) -> dict[str, Any]:
    state = attributes["compliance_state"]
    if attributes["jailbroken"]:
        status, severity, reason = "open", "high", "jailbroken"
    elif state in FAILED_COMPLIANCE_STATES:
        status, severity, reason = "open", "high", state
    elif state == "inGracePeriod":
        status, severity, reason = "open", "low", "in_grace_period"
    elif state == "compliant":
        status, severity, reason = "pass", "info", None
    else:
        # unknown / configManager: Intune has no compliance verdict to rely on.
        status, severity, reason = "open", "medium", "compliance_not_reported"
    return _event(
        graph_tenant=graph_tenant,
        device_id=device_id,
        signal="compliance",
        controls=COMPLIANCE_CONTROLS,
        status=status,
        severity=severity,
        attributes={**attributes, "finding_reason": reason},
        collected_at=collected_at,
        tenant_id=tenant_id,
    )


def _event(
    *,
    graph_tenant: str,
    device_id: str,
    signal: str,
    controls: list[str],
    status: str,
    severity: str,
    attributes: dict[str, Any],
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    stable = stable_id_slug(f"{graph_tenant}:{signal}:{device_id}", fallback="intune")
    return {
        "event_id": f"intune-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": "intune",
        "event_type": f"intune.device.{signal}",
        "entity": {
            "asset_id": f"intune:device:{device_id}",
            "asset_type": "managed_device",
            "asset_owner": graph_tenant,
            "environment": "prod",
            "org": graph_tenant,
        },
        "severity": severity,
        "status": status,
        "controls": controls,
        "safeguard_ids": ["SG-ENDPOINTENCRYPTION-001"] if signal == "encryption" else [],
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": f"https://{GRAPH_HOST}/v1.0/deviceManagement/managedDevices/{device_id}",
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": attributes,
    }
