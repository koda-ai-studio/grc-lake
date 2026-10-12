"""Bounded neighborhoods of recorded evidence and explicitly scoped relationships.

Catalog edges describe mappings, not evaluated compliance or attack paths.
The browser receives a bounded slice; hidden neighbors stay explicitly counted.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from security_lakehouse.catalog import control_catalog_view, framework_registry_view
from security_lakehouse.domain_identity import source_asset_key
from security_lakehouse.event_status import FAIL_STATUSES, normalize_event_status
from security_lakehouse.generations import generation_reader, pinned_path
from security_lakehouse.investigation_repository import add_repository_context
from security_lakehouse.io import canonical_sha256, read_json, read_jsonl
from security_lakehouse.mapping_review import effective_safeguards
from security_lakehouse.models import instant_sort_key
from security_lakehouse.safeguards import effective_review_state, load_ccf_categories, load_ccf_families
from security_lakehouse.tracking import list_events


def _id(kind: str, *parts: str) -> str:
    return kind + ":" + canonical_sha256(parts)


@generation_reader
def investigation_graph(
    lake: Path,
    *,
    root: str | None = None,
    view: str = "controls",
    depth: int = 2,
    limit: int = 150,
    layers: set[str] | None = None,
    search: str = "",
    root_offset: int = 0,
    vendors: list[dict[str, Any]] | None = None,
    expected_version: str | None = None,
) -> dict[str, Any]:
    if root_offset < 0:
        raise ValueError("invalid root offset")
    if depth not in (1, 2, 3) or not 1 <= limit <= 300 or view not in ("controls", "environment", "investigation"):
        raise ValueError("invalid graph bounds or view")
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def node(kind, identity, label, **fields):
        nodes.setdefault(identity, {"id": identity, "kind": kind, "label": label, **fields})
        return identity

    def edge(source, target, kind, **fields):
        if source in nodes and target in nodes:
            identity = _id("edge", source, target, kind)
            edges[identity] = {"id": identity, "source": source, "target": target, "kind": kind, **fields}

    frozen_controls = lake / "catalog/control_map.json"
    controls = (
        {r["control_id"]: r for r in read_json(frozen_controls, base_dir=lake)["controls"]}
        if pinned_path(frozen_controls).is_file()
        else control_catalog_view()
    )
    frozen = lake / "catalog/safeguards.json"
    safeguards = read_json(frozen, base_dir=lake) if pinned_path(frozen).is_file() else effective_safeguards(lake)
    assessment_path = lake / "gold/ccf_assessment.json"
    assessment = read_json(assessment_path, base_dir=lake) if pinned_path(assessment_path).is_file() else {}
    assessed = {row["safeguard_id"]: row for row in assessment.get("safeguards", [])}
    frameworks = framework_registry_view()
    for cid, row in controls.items():
        fid = str(row.get("framework_id") or "")
        node("framework", "framework:" + fid, frameworks.get(fid, {}).get("name", fid), framework_id=fid)
        node(
            "control",
            "control:" + cid,
            cid,
            subtitle=row.get("title"),
            framework_id=fid,
            owner=row.get("owner"),
            basis="Catalog requirement; evidence links are recorded bindings",
        )
        edge("framework:" + fid, "control:" + cid, "framework_has_control")
    for row in load_ccf_categories():
        node("ccf_category", "category:" + row["category_id"], row["label"], basis="Catalog taxonomy")
    for fid, row in load_ccf_families().items():
        node("ccf_family", "family:" + fid, row["label"], basis="Catalog taxonomy")
        edge("category:" + row["category"], "family:" + fid, "contains")
    for row in safeguards["safeguards"]:
        sid = "safeguard:" + row["safeguard_id"]
        node(
            "safeguard",
            sid,
            row.get("title") or row["safeguard_id"],
            owner=row.get("owner"),
            basis="Catalog definition; a mapping does not establish assessment coverage",
            status=assessed.get(row["safeguard_id"], {}).get("status", "not_evaluated"),
        )
        edge("family:" + str(row.get("risk_domain")), sid, "contains")
        for member in row.get("satisfies", []):
            edge("control:" + member["control_id"], sid, "maps_to", review_state=effective_review_state(member))

    freshness = {
        (r.get("tenant_id", ""), r.get("event_id")): r
        for r in read_jsonl(lake / "gold/evidence_freshness.jsonl", missing_ok=True, base_dir=lake)
    }
    triage = {}
    for decision in sorted(list_events(lake), key=lambda r: instant_sort_key(r.get("occurred_at"))):
        triage[decision["violation_id"]] = decision
    events = read_jsonl(lake / "silver/normalized_events.jsonl", missing_ok=True, base_dir=lake)
    asset_names = {
        row["asset_id"]: row.get("asset_name")
        for row in read_jsonl(lake / "gold/asset_risk.jsonl", missing_ok=True, base_dir=lake)
    }
    asset_scopes = defaultdict(set)
    for event in events:
        account, asset = source_asset_key({**event, "asset_id": event.get("asset_id") or ""})
        asset_scopes[asset].add(account)
    evidence_by_event = defaultdict(list)
    for event in sorted(events, key=canonical_sha256):
        account, asset = source_asset_key({**event, "asset_id": event.get("asset_id") or ""})
        provider = str(event.get("source") or "")
        observed = dict(
            source_account_id=account,
            provider=provider,
            owner=event.get("asset_owner"),
            environment=event.get("environment"),
            observed_at=event.get("event_time"),
        )
        aid = _id("asset", account, asset)
        eid = "evidence:" + canonical_sha256(event)
        evidence_by_event[(account, event.get("event_id"), asset)].append(eid)
        fresh = freshness.get((account, event.get("event_id")), {})
        node(
            "evidence_type",
            eid,
            event.get("event_type") or "Evidence",
            **observed,
            evidence_id=event.get("event_id"),
            evidence_ref=event.get("evidence_ref"),
            raw_sha256=event.get("raw_sha256"),
            freshness_status=fresh.get("status"),
            status=event.get("status"),
            basis="Observed record; not a compliance verdict",
        )
        if asset:
            kind = "repository" if event.get("asset_type") == "repository" else "asset"
            node(
                kind,
                aid,
                event.get("asset_name") or (asset_names.get(asset) if len(asset_scopes[asset]) == 1 else None) or asset,
                **observed,
                asset_id=asset,
                subtitle=event.get("asset_type"),
                basis="Observed asset; inventory completeness not established",
            )
            edge(eid, aid, "evidence_covers_asset")
            if environment := event.get("environment"):
                env = node(
                    "environment", _id("environment", account, environment), environment, source_account_id=account
                )
                edge(env, aid, "contains")
            if account:
                acc = node("account", _id("account", account), account, source_account_id=account)
                edge(acc, aid, "contains")
        if provider:
            src = node(
                "source",
                _id("source", account, provider),
                provider,
                source_account_id=account,
                provider=provider,
                basis="Evidence producer; no vendor assessment implied",
            )
            edge(src, eid, "produces")
        for cid in set(event.get("control_ids") or []):
            edge("control:" + cid, eid, "control_requires_evidence")
            if normalize_event_status(event.get("status")) in FAIL_STATUSES:
                decision = triage.get(cid + ":" + str(event.get("event_id")), {})
                finding = node(
                    "finding",
                    _id("finding", account, cid, str(event.get("event_id")), asset),
                    cid + " finding",
                    **{**observed, "owner": decision.get("assignee") or observed["owner"]},
                    severity=event.get("severity"),
                    status=decision.get("state", "open"),
                    evidence_id=event.get("event_id"),
                    basis="Observed failing evidence",
                    next_action="Review evidence and assign remediation in Findings",
                )
                edge(aid, finding, "has_finding")
                edge(finding, eid, "has_evidence")
        for sid in set(event.get("safeguard_ids") or []):
            edge("safeguard:" + sid, eid, "has_evidence")

    add_repository_context(lake, node, edge, _id, evidence_by_event)

    for vendor in vendors or []:
        vid = node(
            "vendor",
            "vendor:" + vendor["id"],
            vendor["vendor_name"],
            owner=vendor.get("owner"),
            status=vendor.get("status"),
            severity=vendor.get("risk_level"),
            basis="Recorded vendor assessment",
        )
        unresolved = 0
        for ref in vendor.get("asset_refs", []):
            target = _id("asset", ref["source_account_id"], ref["asset_id"])
            if target not in nodes:
                unresolved += 1
            edge(vid, target, "vendor_uses_asset")
        nodes[vid]["next_action"] = (
            f"{unresolved} recorded asset references are not present in this evidence generation. Review vendor links."
            if unresolved
            else "Review the vendor assessment and its explicitly recorded asset links."
        )

    version = canonical_sha256([list(nodes.values()), list(edges.values())])
    if expected_version and version != expected_version:
        raise ValueError("graph version changed; refresh before expanding")
    eligible = {key for key, n in nodes.items() if not layers or n["kind"] in layers}
    adjacency: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for e in edges.values():
        if e["source"] in eligible and e["target"] in eligible:
            outgoing[e["source"]].add(e["target"])
            incoming[e["target"]].add(e["source"])
            adjacency[e["source"]].add(e["target"])
            adjacency[e["target"]].add(e["source"])
    root_kinds = (
        {"control", "safeguard", "ccf_category", "ccf_family", "framework"}
        if view == "controls"
        else (
            {"environment", "account", "repository", "asset"}
            if view == "environment"
            else {"finding", "source", "vendor", "evidence_type"}
        )
    )
    choices = sorted(
        (
            n
            for n in nodes.values()
            if n["kind"] in root_kinds
            and n["id"] in eligible
            and search.casefold() in (n["label"] + " " + n["id"]).casefold()
        ),
        key=lambda n: (
            n["kind"] != ("environment" if view == "environment" else "control"),
            -len(adjacency[n["id"]]),
            n.get("source_account_id", ""),
            n["id"],
        ),
    )
    if root is None:
        observed_controls = [
            n
            for n in choices
            if n["kind"] == "control" and any(nodes[target]["kind"] == "evidence_type" for target in outgoing[n["id"]])
        ]
        preferred = next((n for n in observed_controls if n["id"] == "control:SOC2-CC6.1"), None)
        root = (preferred or (observed_controls[0] if observed_controls else choices[0]))["id"] if choices else None
    selected = {root} if root in eligible else set()
    ordered = list(selected)
    # A control path walks upstream and downstream independently: reaching a
    # shared framework or safeguard must not turn back into sibling controls.
    walks = (outgoing, incoming) if view == "controls" else (adjacency,)
    for links in walks:
        frontier = {root} if root in eligible else set()
        visited = set(frontier)
        for _ in range(depth):
            following = set()
            for key in frontier:
                if view != "controls" and key != root and nodes[key]["kind"] in {"framework", "control", "safeguard"}:
                    continue
                following.update(links[key] - visited)
            visited.update(following)
            ordered.extend(sorted(following - selected))
            selected.update(following)
            frontier = following
    kept = set(ordered[:limit])
    return {
        "nodes": [nodes[k] for k in ordered[:limit]],
        "edges": [e for e in edges.values() if e["source"] in kept and e["target"] in kept],
        "counts": dict(Counter(n["kind"] for n in nodes.values())),
        "version": version,
        "root": root,
        "root_missing": root is not None and root not in eligible,
        "roots": [
            {"id": n["id"], "label": n["label"], "kind": n["kind"]} for n in choices[root_offset : root_offset + 50]
        ],
        "root_count": len(choices),
        "root_offset": root_offset,
        "next_root_offset": root_offset + 50 if root_offset + 50 < len(choices) else None,
        "depth": depth,
        "limit": limit,
        "truncated": len(selected) > limit,
        "matching_nodes": len(selected),
        "boundary": "Recorded relationships; not network reachability or complete inventory",
    }
