"""Transport-agnostic legacy ``/api/*`` surface (UI-compatible, unversioned).

These compatibility routes preserve their unversioned response shapes across
the stdlib and authenticated FastAPI servers. Shared mutations delegate to
:mod:`security_lakehouse.api_v1`; collection reads keep the historical
unpaginated contract.

Handlers return ``(HTTPStatus, body)``. Transports apply read redaction and
authenticate callers; this module centralizes route dispatch and mutation
scope requirements so local mode and server mode cannot drift.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path
from typing import Any

from security_lakehouse import api_v1
from security_lakehouse.assessment import SnapshotWrittenHook, build_current_posture, write_assessment_snapshot
from security_lakehouse.asset_names import load_asset_names, with_asset_names
from security_lakehouse.audit_log import build_audit_log
from security_lakehouse.connector_state import (
    append_config_event,
    build_catalog_view,
    configure_payload_error,
    enablement_probe_error,
    list_runs,
    resolve_configure_payload,
    run_discovery,
    run_probe,
)
from security_lakehouse.framework_detail import build_framework_detail
from security_lakehouse.framework_provenance import build_framework_view
from security_lakehouse.generations import generation_reader
from security_lakehouse.graph import build_compliance_graph, build_framework_crosswalk, build_repository_graph
from security_lakehouse.io import read_jsonl, resolve_path
from security_lakehouse.mappings import (
    build_framework_equivalence,
    build_reviewed_crosswalk,
    load_control_article_mappings,
)
from security_lakehouse.readiness import build_readiness_view
from security_lakehouse.scheduler import tick as scheduler_tick
from security_lakehouse.tracking import latest_state, list_events
from security_lakehouse.trust_share import list_shares
from security_lakehouse.workflows import (
    action_catalog,
    get_workflow,
    get_workflow_run,
    list_workflows,
)
from security_lakehouse.workflows import (
    list_runs as list_workflow_runs,
)

AUDITOR_ROLE = "auditor"

Query = dict[str, list[str]]
Body = dict[str, Any]


def _first(query: Query, key: str) -> str | None:
    return api_v1.first_param(query, key)


def _suffix_match(path: str, prefix: str, suffix: str) -> str | None:
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    rest = path[len(prefix) : -len(suffix)]
    return rest or None


def _workflow_get_match(path: str) -> str | None:
    if not path.startswith("/api/workflows/"):
        return None
    rest = path[len("/api/workflows/") :]
    if rest in {"", "actions"} or rest.startswith("actions/") or "/" in rest:
        return None
    return rest


def _workflow_run_id_match(path: str) -> str | None:
    prefix = "/api/workflows/runs/"
    if not path.startswith(prefix):
        return None
    rest = path[len(prefix) :].strip("/")
    if not rest or "/" in rest:
        return None
    return rest


def required_post_scope(path: str) -> str:
    """Return the RBAC scope required to mutate a legacy console route.

    Every legacy mutation has a v1 twin, so the v1 table is the single source
    of truth; ``/api/<rest>`` is scoped exactly like ``/api/v1/<rest>``.
    """
    prefix = "/api/"
    if not path.startswith(prefix) or path.startswith("/api/v1/"):
        return api_v1._UNMAPPED_POST_SCOPE
    return api_v1.required_post_scope("/api/v1/" + path[len(prefix) :])


@generation_reader
def handle_get(
    path: str, query: Query, lake_dir: str | Path, *, share_lakes: tuple[Path, ...] = ()
) -> tuple[HTTPStatus, Body]:
    """Resolve a legacy GET into ``(status, body)``. Auditor redaction is applied by the transport."""
    lake = resolve_path(lake_dir)
    if path == "/api/posture/current":
        return HTTPStatus.OK, build_current_posture(lake)
    if path == "/api/violations":
        posture = build_current_posture(lake, inline_violation_cap=None)
        framework = _first(query, "framework")
        control_id = _first(query, "control_id")
        violations = posture["violations"]
        if framework:
            control_frameworks = {
                row["control_id"]: row["framework"]
                for row in read_jsonl(lake / "gold" / "control_posture.jsonl", base_dir=lake)
            }
            violations = [row for row in violations if control_frameworks.get(row["control_id"]) == framework]
        if control_id:
            violations = [row for row in violations if row["control_id"] == control_id]
        return HTTPStatus.OK, {"count": len(violations), "violations": violations}
    if path == "/api/controls":
        control_id = _first(query, "control_id")
        controls = read_jsonl(lake / "gold" / "control_posture.jsonl", base_dir=lake)
        if control_id:
            controls = [row for row in controls if row["control_id"] == control_id]
        return HTTPStatus.OK, {"controls": controls}
    if path == "/api/control-tests":
        result = _first(query, "result")
        control_id = _first(query, "control_id")
        rows = read_jsonl(lake / "gold" / "control_tests.jsonl", base_dir=lake)
        if result:
            rows = [row for row in rows if row["result"] == result]
        if control_id:
            rows = [row for row in rows if row["control_id"] == control_id]
        return HTTPStatus.OK, {"count": len(rows), "control_tests": rows}
    if path == "/api/evidence":
        control_id = _first(query, "control_id")
        rows = read_jsonl(lake / "silver" / "normalized_events.jsonl", base_dir=lake)
        if control_id:
            rows = [row for row in rows if control_id in row["control_ids"]]
        rows = with_asset_names(rows, load_asset_names(lake))
        return HTTPStatus.OK, {"count": len(rows), "evidence": rows}
    if path == "/api/assets":
        return HTTPStatus.OK, {"assets": read_jsonl(lake / "gold" / "asset_risk.jsonl", base_dir=lake)}
    framework_detail = _suffix_match(path, "/api/frameworks/", "/detail")
    if framework_detail is not None:
        detail = build_framework_detail(framework_detail, lake)
        if detail is None:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        return HTTPStatus.OK, detail
    reads: dict[str, tuple[str | None, bool, Callable[[Path], Any]]] = {
        "/api/snapshots": ("snapshots", True, api_v1.list_snapshots),
        "/api/connectors": ("connectors", True, build_catalog_view),
        "/api/frameworks": ("frameworks", True, lambda _lake: build_framework_view()),
        "/api/graph": (None, False, build_compliance_graph),
        "/api/repo-graph": (None, False, build_repository_graph),
        "/api/crosswalk": (None, False, lambda _lake: build_framework_crosswalk()),
        "/api/crosswalk/reviewed": (None, False, lambda _lake: build_reviewed_crosswalk()),
        "/api/mappings/equivalence": (None, False, lambda _lake: build_framework_equivalence()),
        "/api/mappings": ("mappings", True, lambda _lake: list(load_control_article_mappings().values())),
        "/api/readiness": ("frameworks", True, lambda _lake: build_readiness_view()),
        "/api/workflows": ("workflows", True, list_workflows),
        "/api/workflows/actions": ("actions", False, lambda _lake: action_catalog()),
    }
    simple = reads.get(path)
    if simple is not None:
        key, counted, loader = simple
        data = loader(lake)
        response = {key: data} if key else data
        if counted:
            response["count"] = len(data)
        return HTTPStatus.OK, response
    workflow_run_id = _workflow_run_id_match(path)
    if workflow_run_id is not None:
        run = get_workflow_run(lake, workflow_run_id)
        if run is None:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        return HTTPStatus.OK, {"run": run}
    workflow_get = _workflow_get_match(path)
    if workflow_get is not None:
        workflow = get_workflow(lake, workflow_get)
        if workflow is None:
            return HTTPStatus.NOT_FOUND, {"error": "not_found"}
        return HTTPStatus.OK, workflow
    workflow_runs = _suffix_match(path, "/api/workflows/", "/runs")
    if workflow_runs is not None and workflow_runs != "actions":
        return HTTPStatus.OK, {"workflow_id": workflow_runs, "runs": list_workflow_runs(lake, workflow_runs)}
    if path == "/api/trust-shares":
        include_revoked = (_first(query, "include_revoked") or "false").lower() in {"1", "true", "yes"}
        shares = list_shares(lake, include_revoked=include_revoked, additional_lakes=share_lakes)
        return HTTPStatus.OK, {"count": len(shares), "shares": shares}
    if path == "/api/audit-log":
        limit = int(_first(query, "limit") or "200")
        include_requests = (_first(query, "include_requests") or "false").lower() in {"1", "true", "yes"}
        entries = build_audit_log(
            lake,
            category=_first(query, "category"),
            actor=_first(query, "actor"),
            limit=max(1, min(limit, 1000)),
            include_requests=include_requests,
        )
        return HTTPStatus.OK, {"count": len(entries), "entries": entries}
    connector_runs = _suffix_match(path, "/api/connectors/", "/runs")
    if connector_runs is not None:
        return HTTPStatus.OK, {"connector_id": connector_runs, "runs": list_runs(lake, connector_runs)}
    tracking = _suffix_match(path, "/api/violations/", "/tracking")
    if tracking is not None:
        current = latest_state(lake, violation_id=tracking)
        return HTTPStatus.OK, {
            "violation_id": tracking,
            "current_state": (current or {}).get("state", "open"),
            "events": list_events(lake, violation_id=tracking),
        }
    return HTTPStatus.NOT_FOUND, {"error": "not_found"}


def handle_post(
    path: str,
    body: Body,
    lake_dir: str | Path,
    *,
    role: str = "",
    on_snapshot_written: SnapshotWrittenHook | None = None,
    share_lakes: tuple[Path, ...] = (),
) -> tuple[HTTPStatus, Body]:
    """Resolve a legacy POST into ``(status, body)``.

    ``on_snapshot_written`` mirrors ``api_v1.handle_post``'s parameter of the
    same name: forwarded to :func:`write_assessment_snapshot` for the
    ``/api/snapshots`` route so server mode's legacy (unversioned) surface
    dispatches webhook events too, not only ``/api/v1/snapshots``.
    """
    lake = resolve_path(lake_dir)
    if role == AUDITOR_ROLE:
        return HTTPStatus.FORBIDDEN, {"error": "forbidden", "reason": "auditor role is read-only"}
    body = body or {}
    if path == "/api/snapshots":
        reason = str(body.get("reason") or "api_request")
        snapshot_path = write_assessment_snapshot(lake, reason=reason, on_snapshot_written=on_snapshot_written)
        return HTTPStatus.CREATED, {"snapshot_path": str(snapshot_path), "reason": reason}
    configure = _suffix_match(path, "/api/connectors/", "/configure")
    if configure is not None:
        state = str(body.get("state") or "enabled").lower()
        credentials, options = resolve_configure_payload(
            lake,
            connector_id=configure,
            credentials=body.get("credentials") if "credentials" in body else None,
            options=body.get("options") if "options" in body else None,
        )
        error = configure_payload_error(
            connector_id=configure,
            state=state,
            credentials=credentials,
            options=options,
        )
        if error:
            return HTTPStatus.BAD_REQUEST, {"error": "bad_request", "reason": error}
        error = enablement_probe_error(
            lake,
            connector_id=configure,
            state=state,
            credentials=credentials,
            options=options,
        )
        if error:
            return HTTPStatus.BAD_REQUEST, {"error": "bad_request", "reason": error}
        record = append_config_event(
            lake,
            connector_id=configure,
            state=state,
            actor=str(body.get("actor") or "console"),
            credentials=credentials,
            options=options,
        )
        return HTTPStatus.CREATED, {"event": record}
    probe = _suffix_match(path, "/api/connectors/", "/probe")
    if probe is not None:
        record = run_probe(
            lake,
            connector_id=probe,
            actor=str(body.get("actor") or "console"),
            credentials=body.get("credentials") if "credentials" in body else None,
            options=body.get("options") if "options" in body else None,
        )
        return HTTPStatus.CREATED, {"run": record}
    discover = _suffix_match(path, "/api/connectors/", "/discover")
    if discover is not None:
        record = run_discovery(
            lake,
            connector_id=discover,
            actor=str(body.get("actor") or "console"),
            credentials=body.get("credentials") if "credentials" in body else None,
            options=body.get("options") if "options" in body else None,
        )
        return HTTPStatus.CREATED, {"run": record}
    if path == "/api/scheduler/tick":
        results = scheduler_tick(lake)
        return HTTPStatus.CREATED, {"fired": len(results), "results": results}
    key = _post_response_key(path)
    if key is False:
        return HTTPStatus.NOT_FOUND, {"error": "not_found"}
    status, response = api_v1.handle_post("/api/v1/" + path[len("/api/") :], body, lake, share_lakes=share_lakes)
    if status >= HTTPStatus.BAD_REQUEST:
        if status == HTTPStatus.NOT_FOUND:
            not_found = {"error": "not_found"}
            if key is None:
                not_found["reason"] = "unknown evidence event"
            return status, not_found
        # Legacy approvals predate the v1 conflict response. Preserve their 400
        # and generic error while retaining v1's claim/version checks.
        detail = response["errors"][0]["detail"] if key == "event" else "invalid request"
        return HTTPStatus.BAD_REQUEST, {"error": "bad_request", "reason": detail}
    data = response["data"]
    return status, {key: data} if isinstance(key, str) else data


def _post_response_key(path: str) -> str | bool | None:
    """Whitelist legacy mutations and their historical success-body keys."""
    fixed = {
        "/api/workflows": "workflow",
        "/api/workflows/actions/run": "output",
        "/api/trust-shares": "share",
    }
    if path in fixed:
        return fixed[path]
    for prefix, suffix, key in (
        ("/api/violations/", "/triage", "event"),
        ("/api/evidence/", "/verify", None),
        ("/api/workflows/", "/run", "run"),
        ("/api/workflows/runs/", "/retry", "run"),
        ("/api/workflows/runs/", "/approve", "run"),
        ("/api/workflows/runs/", "/reject", "run"),
        ("/api/trust-shares/", "/revoke", "share"),
    ):
        if _suffix_match(path, prefix, suffix) is not None:
            return key
    return False
