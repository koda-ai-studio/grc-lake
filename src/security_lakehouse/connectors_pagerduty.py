"""Read-only PagerDuty incident and on-call evidence; see docs/CONNECTORS.md."""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
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
from security_lakehouse.timeutil import parse_iso

BASE = "https://api.pagerduty.com/"


def _gap(collection: str, reason: str) -> CollectionGapError:
    return CollectionGapError(
        "PagerDuty collection incomplete", collection=collection, reason=reason, api="PagerDuty REST v2"
    )


def _id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{7,32}", value):
        raise ValueError("PagerDuty record has an invalid identifier")
    return value


class PagerDutyClient:
    def __init__(self, *, token: str, account: str, max_pages: int = 100) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", account):
            raise ConnectorConfigError("PagerDuty account must be a short lowercase account label")
        if type(max_pages) is not int or not 1 <= max_pages <= 100:
            raise ConnectorConfigError("PagerDuty max_pages must be an integer from 1 to 100")
        self.account, self.max_pages, self._token = account, max_pages, token

    def get(self, path: str, params: dict[str, str]) -> Any:
        request = urllib.request.Request(
            BASE + path + "?" + urllib.parse.urlencode(params),
            method="GET",
            headers={
                "Authorization": f"Token token={self._token}",
                "Accept": "application/vnd.pagerduty+json;version=2",
            },
        )

        def read() -> Any:
            with netguard.open_public(request, timeout=30, label="pagerduty") as response:
                return read_json_response(response)

        try:
            return backoff.http_retry(read)
        except urllib.error.HTTPError as exc:
            raise _gap(path, f"http_{exc.code}") from None
        except (OSError, ValueError):
            raise _gap(path, "unreadable_response") from None


class PagerDutyFixtureClient(PagerDutyClient):
    def __init__(self, fixture_dir: str | Path, *, account: str, max_pages: int = 100) -> None:
        super().__init__(token="", account=account, max_pages=max_pages)
        self.responses = read_json(Path(fixture_dir) / "responses.json")

    def get(self, path: str, params: dict[str, str]) -> Any:
        key = f"{path}:{params['offset']}"
        if key not in self.responses:
            raise _gap(path, "fixture_missing")
        return self.responses[key]


def _list(client: PagerDutyClient, path: str, field: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    for _ in range(client.max_pages):
        payload = client.get(path, {**(params or {}), "limit": "100", "offset": str(offset)})
        if not isinstance(payload, dict) or type(payload.get("more")) is not bool:
            raise _gap(path, "invalid_pagination")
        chunk = object_rows(payload.get(field), label="PagerDuty")
        if len(chunk) > 100 or ("offset" in payload and payload["offset"] != offset):
            raise _gap(path, "invalid_pagination")
        for row in chunk:
            key = _id(row.get("id")) if field != "oncalls" else canonical_sha256(row)
            if key in seen:
                raise _gap(path, "duplicate_record")
            seen.add(key)
        rows.extend(chunk)
        if payload["more"] is False:
            return rows
        if not chunk:
            raise _gap(path, "empty_intermediate_page")
        offset += len(chunk)
    raise _gap(path, "page_budget_exhausted")


def collect_pagerduty_evidence(
    client: PagerDutyClient,
    *,
    collected_at: datetime | None = None,
    tenant_id: str = "customer-managed",
    max_resolution_hours: int = 24,
) -> list[dict[str, Any]]:
    if type(max_resolution_hours) is not int or not 1 <= max_resolution_hours <= 8760:
        raise ConnectorConfigError("PagerDuty max_resolution_hours must be an integer from 1 to 8760")
    now = collected_at or datetime.now(UTC)
    rows: list[dict[str, Any]] = []

    def read_scope(path: str, field: str, params: dict[str, str] | None = None) -> list[dict[str, Any]] | None:
        try:
            return _list(client, path, field, params)
        except (CollectionGapError, ValueError) as exc:
            gap = exc if isinstance(exc, CollectionGapError) else _gap(path, "invalid_response")
            rows.append(
                _event(
                    client,
                    path,
                    "collection_gap",
                    "collection_scope",
                    "not_evaluated",
                    gap.attributes(),
                    now,
                    tenant_id,
                )
            )
            return None

    # All retained incidents include unresolved incidents older than a recent window.
    incidents = read_scope("incidents", "incidents", {"date_range": "all"})
    services = read_scope("services", "services")
    oncalls = read_scope("oncalls", "oncalls", {"since": utc_iso(now), "until": utc_iso(now)})
    if not services and not incidents:
        rows.append(
            _event(
                client,
                "scope",
                "collection_gap",
                "collection_scope",
                "not_evaluated",
                _gap("scope", "empty_scope").attributes(),
                now,
                tenant_id,
            )
        )
    for incident in incidents or []:
        iid = incident["id"]
        logs = read_scope(f"incidents/{iid}/log_entries", "log_entries")
        created = parse_iso(incident.get("created_at"), lenient=True)
        status = incident.get("status")
        attrs: dict[str, Any] = {
            "incident_id": iid,
            "incident_status": status,
            "urgency": incident.get("urgency"),
            "created_at": utc_iso(created) if created else None,
            "max_resolution_hours": max_resolution_hours,
            "time_to_acknowledge_seconds": None,
            "time_to_resolve_seconds": None,
            "acknowledged_at": None,
            "resolved_at": None,
        }
        verdict = "observed"
        if created is None or created > now or status not in ("triggered", "acknowledged", "resolved"):
            verdict = "not_evaluated"
            attrs.update(_gap(f"incident:{iid}", "unknown_incident_state").attributes())
        elif status in ("triggered", "acknowledged") and (now - created).total_seconds() > max_resolution_hours * 3600:
            verdict = "open"
        if logs is None:
            attrs.update(_gap(f"incident:{iid}", "incident_log_unavailable").attributes())
            if verdict != "open":
                verdict = "not_evaluated"
        elif created is not None:
            for kind, label in [("acknowledge_log_entry", "acknowledge"), ("resolve_log_entry", "resolve")]:
                entries = [parse_iso(log.get("created_at"), lenient=True) for log in logs if log.get("type") == kind]
                valid = [t for t in entries if t is not None and created <= t <= now]
                if len(valid) != len(entries):
                    attrs.update(_gap(f"incident:{iid}", "invalid_log_timestamp").attributes())
                    if verdict != "open":
                        verdict = "not_evaluated"
                elif valid:
                    moment = min(valid) if label == "acknowledge" else max(valid)
                    attrs[f"time_to_{label}_seconds"] = (moment - created).total_seconds()
                    attrs["acknowledged_at" if label == "acknowledge" else "resolved_at"] = utc_iso(moment)
            if status == "resolved" and attrs["resolved_at"] is None:
                attrs.update(_gap(f"incident:{iid}", "resolution_time_missing").attributes())
                verdict = "not_evaluated"
        rows.append(_event(client, iid, "incident", "audit_log", verdict, attrs, now, tenant_id))
    for service in services or []:
        sid = service["id"]
        policy = service.get("escalation_policy")
        policy_id = policy.get("id") if isinstance(policy, dict) else None
        attrs = {
            "service_id": sid,
            "service_status": service.get("status"),
            "escalation_policy_id": policy_id,
            "oncall_covered": None,
            "schedule_ids": [],
        }
        verdict = "observed"
        if not isinstance(policy_id, str) or not policy_id:
            verdict = "not_evaluated"
            attrs.update(_gap(f"service:{sid}", "missing_escalation_policy").attributes())
        elif oncalls is None:
            verdict = "not_evaluated"
            attrs.update(_gap(f"service:{sid}", "oncall_collection_unavailable").attributes())
        else:
            covered, schedules, unknown = _coverage(oncalls, policy_id, now)
            attrs.update(oncall_covered=covered, schedule_ids=schedules)
            if unknown:
                verdict = "not_evaluated"
                attrs.update(_gap(f"service:{sid}", "unknown_oncall_interval").attributes())
            elif not covered:
                verdict = "not_evaluated"
                attrs.update(_gap(f"service:{sid}", "no_current_oncall").attributes())
        rows.append(_event(client, sid, "service.coverage", "service", verdict, attrs, now, tenant_id))
    return rows


def _coverage(oncalls: list[dict[str, Any]], policy_id: str, now: datetime) -> tuple[bool, list[str], bool]:
    covered, unknown = False, False
    schedules: set[str] = set()
    for row in oncalls:
        policy = row.get("escalation_policy")
        if not isinstance(policy, dict):
            unknown = True
            continue
        if policy.get("id") != policy_id:
            continue
        user = row.get("user")
        start, end = parse_iso(row.get("start"), lenient=True), parse_iso(row.get("end"), lenient=True)
        permanent = row.get("start") is None and row.get("end") is None and row.get("schedule") is None
        if (
            not isinstance(user, dict)
            or not user.get("id")
            or (not permanent and (start is None or end is None or end <= start))
        ):
            unknown = True
            continue
        if permanent or (start is not None and end is not None and start <= now < end):
            covered = True
            schedule = row.get("schedule")
            if isinstance(schedule, dict) and isinstance(schedule.get("id"), str):
                schedules.add(schedule["id"])
    return covered, sorted(schedules), unknown


def _event(
    client: PagerDutyClient,
    identity: str,
    signal: str,
    asset_type: str,
    status: str,
    attrs: dict[str, Any],
    now: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    key = canonical_sha256([client.account, identity, signal])[:32]
    bound = signal != "collection_gap"
    row: dict[str, Any] = {
        "event_id": f"pagerduty-{key}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(now),
        "source": "pagerduty",
        "event_type": f"pagerduty.{signal}",
        "entity": {
            "asset_id": f"pagerduty:{client.account}:{asset_type}:{identity}",
            "asset_type": asset_type,
            "asset_owner": client.account,
            "environment": "prod",
            "org": client.account,
        },
        "severity": "medium" if status == "open" else "info",
        "status": status,
        "controls": ["NIST-CSF-RS.MA-01"] if bound else [],
        "evidence": {
            "evidence_id": f"ev-pagerduty-{key}",
            "evidence_ref": BASE
            + (f"incidents/{identity}" if signal == "incident" else f"services/{identity}" if bound else "incidents"),
            "evidence_collected_at": utc_iso(now),
        },
        "attributes": {"account": client.account, **attrs},
    }
    if bound:
        row["safeguard_ids"] = ["SG-INCIDENTHANDLING-001"]
    return row


__all__ = ["PagerDutyClient", "PagerDutyFixtureClient", "collect_pagerduty_evidence"]
