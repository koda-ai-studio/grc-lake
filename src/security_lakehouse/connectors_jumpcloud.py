"""Read-only JumpCloud identity snapshots; official v1/v2 contracts checked 2026-11-24."""

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

HOSTS = {"us": "console.jumpcloud.com", "eu": "console.eu.jumpcloud.com", "in": "console.in.jumpcloud.com"}
ENROLLMENT_STATES = {
    "NOT_ENROLLED",
    "DISABLED",
    "PENDING_ACTIVATION",
    "ENROLLMENT_EXPIRED",
    "IN_ENROLLMENT",
    "PRE_ENROLLMENT",
    "ENROLLED",
}


def _gap(collection: str, reason: str) -> CollectionGapError:
    return CollectionGapError(
        "JumpCloud identity collection incomplete", collection=collection, reason=reason, api="JumpCloud"
    )


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{24}", value):
        raise ValueError("JumpCloud collection contains an invalid identifier")
    return value


class JumpCloudClient:
    def __init__(self, *, token: str, organization: str, region: str = "us", max_pages: int = 100) -> None:
        if region not in HOSTS:
            raise ConnectorConfigError("JumpCloud region must be us, eu or in")
        try:
            self.organization = _identifier(organization)
        except ValueError:
            raise ConnectorConfigError(
                "JumpCloud organization_id must contain 24 lowercase hexadecimal characters"
            ) from None
        if type(max_pages) is not int or not 1 <= max_pages <= 1000:
            raise ConnectorConfigError("JumpCloud max_pages must be an integer from 1 to 1000")
        self.host, self.max_pages, self._token = HOSTS[region], max_pages, token

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"https://{self.host}/api/{path}",
            method="GET",
            headers={"x-api-key": self._token, "x-org-id": self.organization, "Accept": "application/json"},
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label="jumpcloud") as response:
                return read_json_response(response)

        try:
            return backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise _gap(path, f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise _gap(path, "unreadable_response") from None


class JumpCloudFixtureClient(JumpCloudClient):
    def __init__(self, fixture_dir: str | Path, *, organization: str, region: str = "us", max_pages: int = 100) -> None:
        super().__init__(token="", organization=organization, region=region, max_pages=max_pages)
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, path: str) -> Any:
        if path not in self.responses:
            raise _gap(path, "fixture_missing")
        return self.responses[path]


def _list(client: JumpCloudClient, path: str, *, users: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    expected: int | None = None
    seen: set[str] = set()
    for page in range(client.max_pages):
        payload = client.get(f"{path}?limit=100&skip={page * 100}")
        if users:
            if not isinstance(payload, dict) or type(payload.get("totalCount")) is not int or payload["totalCount"] < 0:
                raise _gap(path, "invalid_user_count")
            if expected is not None and payload["totalCount"] != expected:
                raise _gap(path, "population_changed")
            expected = payload["totalCount"]
            payload = payload.get("results")
        chunk = object_rows(payload, label="JumpCloud")
        if len(chunk) > 100:
            raise _gap(path, "invalid_page_size")
        for row in chunk:
            key = canonical_sha256(row)
            if key in seen:
                raise _gap(path, "duplicate_page_record")
            seen.add(key)
        rows.extend(chunk)
        if len(chunk) < 100:
            if expected is not None and len(rows) != expected:
                raise _gap(path, "population_count_mismatch")
            return rows
    raise _gap(path, "page_budget_exhausted")


def collect_jumpcloud_evidence(client: JumpCloudClient, *, tenant_id: str = "customer-managed") -> list[dict[str, Any]]:
    now = utc_iso(datetime.now(UTC))
    rows: list[dict[str, Any]] = []

    def gap_event(collection: str, exc: Exception) -> None:
        gap = exc if isinstance(exc, CollectionGapError) else _gap(collection, "invalid_response")
        rows.append(
            _event(
                client,
                collection,
                "collection_gap",
                "collection_scope",
                "not_evaluated",
                gap.attributes(),
                now,
                tenant_id,
            )
        )

    try:
        users = _list(client, "systemusers", users=True)
        if not users:
            raise _gap("systemusers", "empty_scope")
        identities = [_identifier(u.get("_id")) for u in users]
        if len(set(identities)) != len(identities):
            raise _gap("systemusers", "duplicate_user_id")
    except (CollectionGapError, ValueError) as exc:
        gap_event("systemusers", exc)
        users = []
    for user in users:
        uid = user["_id"]
        active = _active(user)
        enrollment = user.get("mfaEnrollment")
        enrollment = enrollment if isinstance(enrollment, dict) else {}
        totp, webauthn = enrollment.get("totpStatus"), enrollment.get("webAuthnStatus")
        status = "not_evaluated"
        if active is False:
            status = "observed"
        elif active is True:
            if totp == "ENROLLED" or webauthn == "ENROLLED" or user.get("totp_enabled") is True:
                status = "pass"
            elif (
                isinstance(totp, str)
                and isinstance(webauthn, str)
                and totp in ENROLLMENT_STATES
                and webauthn in ENROLLMENT_STATES
                and user.get("totp_enabled") is False
            ):
                status = "open"
        attrs: dict[str, Any] = {
            "user_id": uid,
            "active": active,
            "account_state": user.get("state"),
            "totp_enrollment": totp,
            "webauthn_enrollment": webauthn,
        }
        if status == "not_evaluated":
            attrs.update(_gap(f"user:{uid}", "unknown_identity_configuration").attributes())
        rows.append(_event(client, uid, "identity.mfa_enrollment", "identity_user", status, attrs, now, tenant_id))
        admin = user.get("admin")
        roles = admin.get("roleNames") if isinstance(admin, dict) else [] if admin is None else None
        if roles is None and isinstance(admin, dict):
            roles = [admin["roleName"]] if isinstance(admin.get("roleName"), str) else None
        valid_roles = isinstance(roles, list) and all(isinstance(r, str) for r in roles)
        access_attrs: dict[str, Any] = {"user_id": uid, "active": active, "admin_roles": roles if valid_roles else None}
        if "admin" not in user or not valid_roles:
            access_attrs.update(_gap(f"admin:{uid}", "unknown_admin_roles").attributes())
        rows.append(
            _event(
                client,
                uid,
                "identity.user_access",
                "identity_user",
                "observed" if "admin" in user and valid_roles else "not_evaluated",
                access_attrs,
                now,
                tenant_id,
            )
        )
    try:
        groups = _list(client, "v2/usergroups")
        ids = [_identifier(g.get("id")) for g in groups]
        if len(set(ids)) != len(ids):
            raise _gap("usergroups", "duplicate_group_id")
    except (CollectionGapError, ValueError) as exc:
        gap_event("usergroups", exc)
        groups = []
    for group in groups:
        gid = group["id"]
        path = f"v2/usergroups/{gid}/members"
        try:
            members = _list(client, path)
            member_ids = []
            for member in members:
                target = member.get("to")
                if not isinstance(target, dict) or target.get("type") != "user":
                    raise _gap(path, "unknown_group_member")
                member_ids.append(_identifier(target.get("id")))
            rows.append(
                _event(
                    client,
                    gid,
                    "identity.group_membership",
                    "identity_group",
                    "observed",
                    {"group_id": gid, "member_ids": sorted(set(member_ids)), "member_count": len(set(member_ids))},
                    now,
                    tenant_id,
                )
            )
        except (CollectionGapError, ValueError) as exc:
            gap_event(path, exc)
    return rows


def _active(user: dict[str, Any]) -> bool | None:
    state, suspended, activated = user.get("state"), user.get("suspended"), user.get("activated")
    if state == "ACTIVATED" and suspended is False and activated is True:
        return True
    if state == "SUSPENDED" and suspended is True:
        return False
    if state == "STAGED" and suspended is False and activated is False:
        return False
    return None


def _event(
    client: JumpCloudClient,
    identity: str,
    signal: str,
    asset_type: str,
    status: str,
    attrs: dict[str, Any],
    now: str,
    tenant_id: str,
) -> dict[str, Any]:
    key = canonical_sha256([client.host, client.organization, identity, signal])[:32]
    bound = signal != "collection_gap"
    mfa = signal == "identity.mfa_enrollment"
    row: dict[str, Any] = {
        "event_id": f"jumpcloud-{key}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": now,
        "source": "jumpcloud",
        "event_type": f"jumpcloud.{signal}",
        "entity": {
            "asset_id": f"jumpcloud:{client.host}:{client.organization}:{asset_type}:{identity}",
            "asset_type": asset_type,
            "asset_owner": client.organization,
            "environment": "prod",
            "org": client.organization,
        },
        "severity": "medium" if status == "open" else "info",
        "status": status,
        "controls": ["SOC2-CC6.1" if mfa else "SOC2-CC6.2"] if bound else [],
        "evidence": {
            "evidence_id": f"ev-jumpcloud-{key}",
            "evidence_ref": f"https://{client.host}/api/"
            + (
                f"v2/usergroups/{identity}/members"
                if asset_type == "identity_group"
                else f"systemusers/{identity}"
                if bound
                else "systemusers"
            ),
            "evidence_collected_at": now,
        },
        "attributes": {"organization_id": client.organization, **attrs},
    }
    if bound:
        row["safeguard_ids"] = ["SG-IDENTITY-001" if mfa else "SG-IDENTITY-002"]
    return row


__all__ = ["JumpCloudClient", "JumpCloudFixtureClient", "collect_jumpcloud_evidence"]
