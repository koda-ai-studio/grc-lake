"""Read-only Entra machine-identity metadata, adapted from Agent-Bom.

Filtering and application joins derive from identity/entra_nhi.py at
95bc4a9c8e50d4bfbce59b91db8f68429cfbf9e5 (Apache-2.0).
Copyright 2024-2026 Mohamed Wagdy Saad. See NOTICE.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.ingestion.microsoft_graph import MicrosoftGraphClient
from security_lakehouse.io import canonical_sha256, read_json
from security_lakehouse.models import utc_iso

_FIELDS = "id,appId,displayName,passwordCredentials,keyCredentials"


class EntraClient(MicrosoftGraphClient):
    def __init__(self, tenant_id: str, **kwargs: Any) -> None:
        super().__init__(tenant_id, label="entra-identity", **kwargs)

    def service_principals(self) -> list[dict[str, Any]]:
        return self.collection(
            f"https://graph.microsoft.com/v1.0/servicePrincipals?$top=100&$select={_FIELDS},servicePrincipalType,accountEnabled"
        )

    def applications(self) -> list[dict[str, Any]]:
        return self.collection(
            f"https://graph.microsoft.com/v1.0/applications?$top=100&$select={_FIELDS},createdDateTime"
        )


class EntraFixtureClient:
    def __init__(self, fixture_dir: str | Path, *, tenant_id: str) -> None:
        self.fixture = Path(fixture_dir)
        self.tenant_id = tenant_id

    def service_principals(self) -> list[dict[str, Any]]:
        return read_json(self.fixture / "service_principals.json")

    def applications(self) -> list[dict[str, Any]]:
        return read_json(self.fixture / "applications.json")


def _is_service_principal_nhi(sp: dict[str, Any]) -> bool:
    """A non-human service principal: an application (workload) identity.

    Entra service principals come in several flavours. ``Application`` and
    ``ManagedIdentity`` are machine identities; ``Legacy`` / ``SocialIdp`` and
    human-assigned SSO entries are excluded.
    """
    sp_type = str(sp.get("servicePrincipalType") or "").strip().lower()
    return sp_type in {"application", "managedidentity"}


def _listing(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip() for row in value
    ):
        raise ValueError("Invalid Entra metadata listing")
    if len({row["id"].strip() for row in value}) != len(value):
        raise ValueError("Duplicate Entra metadata identity")
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:512] or None


def _credential_expiry(*identities: dict[str, Any]) -> tuple[str | None, str]:
    """Adapt upstream earliest-expiry projection, preserving malformed/unknown dates."""
    dates: list[datetime] = []
    for identity in identities:
        for key in ("passwordCredentials", "keyCredentials"):
            credentials = identity.get(key)
            if not isinstance(credentials, list):
                return None, "unknown"
            for credential in credentials:
                try:
                    date = datetime.fromisoformat(credential["endDateTime"].replace("Z", "+00:00"))
                    if date.tzinfo is None:
                        return None, "unknown"
                    dates.append(date.astimezone(UTC))
                except (KeyError, TypeError, ValueError, AttributeError):
                    return None, "unknown"
    return (utc_iso(min(dates)) if dates else None), "complete"


def _event(
    scope: str, key: str, now: datetime, tenant_id: str, attributes: dict[str, Any], *, gap: bool = False
) -> dict[str, Any]:
    suffix = canonical_sha256([scope, key])
    endpoint = (
        key
        if gap
        else {"service_principal": "servicePrincipals", "app_registration": "applications"}[attributes["identity_type"]]
    )
    ref = f"https://graph.microsoft.com/v1.0/{endpoint}"
    if not gap:
        ref += f"/{quote(attributes['identity_id'], safe='')}"
    return {
        "event_id": f"entra-{suffix}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": "entra",
        "event_type": "entra.collection_gap" if gap else "entra.identity.metadata",
        "entity": {
            "asset_id": f"entra:{scope}:{key}",
            "asset_type": "identity_population" if gap else "non_human_identity",
            "asset_owner": scope,
            "environment": "prod",
            "org": scope,
        },
        "severity": "info",
        "status": "not_evaluated" if gap else "observed",
        "controls": [],
        "evidence": {"evidence_id": f"ev-entra-{suffix}", "evidence_ref": ref, "evidence_collected_at": utc_iso(now)},
        "attributes": attributes,
    }


def collect_entra_evidence(
    client: EntraClient | EntraFixtureClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    now = collected_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    populations: dict[str, list[dict[str, Any]] | None] = {}
    for endpoint, fetch in (("servicePrincipals", client.service_principals), ("applications", client.applications)):
        try:
            populations[endpoint] = _listing(fetch())
        except Exception:  # noqa: BLE001 - provider exception text cannot enter evidence records
            populations[endpoint] = None
            gap = CollectionGapError(
                "Entra metadata listing unavailable; coverage is incomplete",
                collection=endpoint,
                reason="listing_failed",
                api="Microsoft Graph",
                permission="Application.Read.All",
            )
            rows.append(_event(client.tenant_id, endpoint, now, tenant_id, gap.attributes(), gap=True))
    principals, apps = populations["servicePrincipals"], populations["applications"]
    apps_by_id = {_text(app.get("appId")): app for app in apps or [] if _text(app.get("appId"))}
    matched = {app_id for principal in principals or [] if (app_id := _text(principal.get("appId")))}
    principal_join_complete = principals is not None and all(_text(p.get("appId")) for p in principals)
    app_join_complete = apps is not None and all(_text(app.get("appId")) for app in apps)
    identities: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = []
    for principal in principals or []:
        if _is_service_principal_nhi(principal):
            app_id = _text(principal.get("appId"))
            identities.append(("service_principal", principal, apps_by_id.get(app_id)))
    for app in apps or []:
        if _text(app.get("appId")) not in matched and (app.get("passwordCredentials") or app.get("keyCredentials")):
            identities.append(("app_registration", app, None))
    for kind, identity, backing in identities:
        app_id = _text(identity.get("appId"))
        backing_known = backing is not None or (app_join_complete and bool(app_id))
        expiry, coverage = _credential_expiry(identity, *([backing] if backing is not None else []))
        if kind == "service_principal" and not backing_known:
            expiry, coverage = None, "partial"
        enabled = identity.get("accountEnabled")
        attributes = {
            "identity_id": identity["id"].strip(),
            "identity_type": kind,
            "source_scope": client.tenant_id,
            "app_id": app_id,
            "name": _text(identity.get("displayName")) or identity["id"].strip(),
            "service_principal_type": _text(identity.get("servicePrincipalType")),
            "lifecycle_status": "active" if enabled is True else "inactive" if enabled is False else "unknown",
            "created_at": _text(identity.get("createdDateTime")),
            "credential_expires_at": expiry,
            "credential_metadata_coverage": coverage,
            "has_backing_app": (backing is not None if backing_known else None)
            if kind == "service_principal"
            else None,
            "orphan_app_registration": (True if principal_join_complete and app_id else None)
            if kind == "app_registration"
            else False,
            "last_used_at": None,
            "scopes": [],
            "scope_coverage": "not_collected",
            "owner": None,
            "owner_coverage": "not_collected",
        }
        rows.append(_event(client.tenant_id, f"{kind}:{identity['id'].strip()}", now, tenant_id, attributes))
    return rows
