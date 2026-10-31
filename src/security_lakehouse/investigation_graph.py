"""Bounded neighborhoods of recorded evidence and explicitly scoped relationships.

Catalog edges describe mappings, not evaluated compliance or attack paths.
The browser receives a bounded slice; each response states how many nodes matched
the walk and whether the slice was truncated.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from itertools import islice
from pathlib import Path
from typing import Any

from security_lakehouse import catalog
from security_lakehouse import safeguards as safeguard_catalog
from security_lakehouse.asset_names import asset_name_for, names_from_assets
from security_lakehouse.catalog import control_catalog_view, framework_registry_view
from security_lakehouse.ccf_evaluation import INVALID_ASSET_TYPE_REASON, binding_applies
from security_lakehouse.ccf_requirement_results import ccf_result_fields, requirement_results_from
from security_lakehouse.domain_identity import source_asset_key
from security_lakehouse.event_status import FAIL_STATUSES, normalize_event_status
from security_lakehouse.generations import generation_identity, generation_reader, pinned_path
from security_lakehouse.investigation_cache import Key, Model, ModelCache
from security_lakehouse.investigation_index import build_indexes, default_root
from security_lakehouse.investigation_persistence import read as read_persistent_index
from security_lakehouse.investigation_repository import add_repository_context
from security_lakehouse.io import canonical_sha256, file_version, read_json, read_jsonl
from security_lakehouse.mapping_review import effective_safeguards
from security_lakehouse.models import instant_sort_key
from security_lakehouse.safeguards import effective_review_state, load_ccf_categories, load_ccf_families
from security_lakehouse.tracking import list_events

_MODEL_CACHE = ModelCache()
_PERSISTENT_MIN_BYTES = 8 * 1024 * 1024
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
_FINDING_SUMMARY = ("id", "kind", "label", "owner", "severity", "status", "next_action", "evidence_id", "event_type")
_FINDING_SUMMARY_LIMIT = 5
# Every generated input read by _build_model/add_repository_context. Missing
# optional files also participate, so later additions cannot reuse an old model.
_MODEL_FILES = (
    "catalog/control_map.json",
    "catalog/safeguards.json",
    "gold/ccf_assessment.json",
    "gold/control_posture.jsonl",
    "gold/control_tests.jsonl",
    "gold/evidence_freshness.jsonl",
    "silver/normalized_events.jsonl",
    "gold/asset_risk.jsonl",
    "bronze/raw_events.jsonl",
    "gold/violation_tracking.jsonl",
)


def _model_key(
    lake: Path, vendors: list[dict[str, Any]] | None, check: Callable[[], None], platform_tenant_id: str | None = None
) -> Key | None:
    identity = generation_identity(lake)
    if identity is None or not all(pinned_path(lake / relative).is_file() for relative in _MODEL_FILES[:2]):
        # Legacy live catalogs include mutable org mapping decisions. Never
        # treat their absence as an immutable empty catalog.
        return None
    versions = []
    for relative in (*_MODEL_FILES, *(("entities/bindings.jsonl",) if platform_tenant_id is not None else ())):
        check()
        versions.append(file_version(lake / relative, base_dir=lake))
    for path in (catalog.DEFAULT_FRAMEWORK_REGISTRY, safeguard_catalog.DEFAULT_FAMILIES):
        check()
        versions.append(file_version(path))
    return str(lake.resolve()), canonical_sha256([identity, versions, vendors or [], platform_tenant_id])


def _model(
    lake: Path, vendors: list[dict[str, Any]] | None, check: Callable[[], None], platform_tenant_id: str | None = None
) -> Model:
    # Vendor records originate outside the generation. Own the supplied snapshot
    # so subsequent caller mutations cannot alter a cached graph.
    vendors = deepcopy(vendors)
    key = _model_key(lake, vendors, check, platform_tenant_id)

    def build() -> Model:
        nodes, edges, frameworks = (
            _build_model(lake, vendors, check)
            if platform_tenant_id is None
            else _build_model(lake, vendors, check, platform_tenant_id)
        )
        version = _graph_version(nodes.values(), edges.values(), check)
        return nodes, edges, frameworks, version, build_indexes(nodes, edges, check)

    if key is None:
        return build()
    return _MODEL_CACHE.get_or_build(
        key, build, lambda: _model_key(lake, vendors, check, platform_tenant_id) == key, check
    )


def _id(kind: str, *parts: str) -> str:
    return kind + ":" + canonical_sha256(parts)


def _graph_version(nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]], check: Callable[[], None]) -> str:
    """Hash the existing canonical [nodes, edges] encoding in bounded row batches."""
    digest = hashlib.sha256(b"[")
    for separator, rows in ((b"", nodes), (b",", edges)):
        digest.update(separator + b"[")
        iterator = iter(rows)
        first = True
        while True:
            check()
            batch = list(islice(iterator, 128))
            if not batch:
                break
            if not first:
                digest.update(b",")
            encoded = json.dumps(batch, sort_keys=True, separators=(",", ":"), default=str)
            digest.update(encoded[1:-1].encode("utf-8"))
            first = False
        digest.update(b"]")
    digest.update(b"]")
    check()
    return digest.hexdigest()


def validate_bounds(
    *, view: str = "controls", depth: int = 2, limit: int = 150, root_offset: int = 0, control_offset: int = 0, **_: Any
) -> None:
    """Reject out-of-range request bounds before any build work starts."""
    if root_offset < 0 or control_offset < 0:
        raise ValueError("invalid root offset")
    if depth not in (1, 2, 3) or not 1 <= limit <= 300 or view not in ("controls", "environment", "investigation"):
        raise ValueError("invalid graph bounds or view")


def _build_model(
    lake: Path,
    vendors: list[dict[str, Any]] | None,
    check: Callable[[], None],
    platform_tenant_id: str | None = None,
    storage: Any = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], Mapping[str, Mapping[str, Any]]]:
    """Release source rows and temporary bindings before fingerprinting and traversal."""
    nodes: dict[str, dict[str, Any]] = {} if storage is None else storage.nodes
    edges: dict[str, dict[str, Any]] = {} if storage is None else storage.edges
    insert_node = nodes.setdefault if storage is None else storage.nodes.insert_default

    def node(kind, identity, label, **fields):
        insert_node(identity, {"id": identity, "kind": kind, "label": label, **fields})
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
    assessment = storage.assessment if storage is not None else None
    if assessment is None:
        assessment = read_json(assessment_path, base_dir=lake) if pinned_path(assessment_path).is_file() else {}
    assessed = {row["safeguard_id"]: row for row in assessment.get("safeguards", [])}
    requirements = requirement_results_from(assessment)
    posture = {
        r["control_id"]: r for r in read_jsonl(lake / "gold/control_posture.jsonl", missing_ok=True, base_dir=lake)
    }
    tests = {r["control_id"]: r for r in read_jsonl(lake / "gold/control_tests.jsonl", missing_ok=True, base_dir=lake)}
    frameworks = framework_registry_view()
    for cid, row in controls.items():
        check()
        fid = str(row.get("framework_id") or "")
        node("framework", "framework:" + fid, frameworks.get(fid, {}).get("name", fid), framework_id=fid)
        evaluated = posture.get(cid, {})
        # The control test is the verdict the Controls page shows; posture alone
        # reports missing evidence as stale.
        tested = tests.get(cid, {})
        node(
            "control",
            "control:" + cid,
            cid,
            subtitle=row.get("title"),
            framework_id=fid,
            owner=row.get("owner"),
            status=tested.get("result") or evaluated.get("status", "not_evaluated"),
            posture_status=evaluated.get("status", "not_evaluated"),
            missing_evidence_types=sorted(tested.get("missing_evidence_types") or []),
            stale_evidence_types=sorted(
                {*(tested.get("stale_evidence_types") or []), *(tested.get("expired_evidence_types") or [])}
            ),
            risk_score=evaluated.get("risk_score"),
            rule_reasons=list(evaluated.get("rule_reasons") or []),
            evaluation_rule=evaluated.get("evaluation_rule"),
            open_event_count=evaluated.get("open_event_count"),
            **ccf_result_fields(requirements, cid),
            basis="Catalog requirement; evidence links are recorded bindings",
        )
        edge("framework:" + fid, "control:" + cid, "framework_has_control")
    for row in load_ccf_categories():
        node("ccf_category", "category:" + row["category_id"], row["label"], basis="Catalog taxonomy")
    for fid, row in load_ccf_families().items():
        node("ccf_family", "family:" + fid, row["label"], basis="Catalog taxonomy")
        edge("category:" + row["category"], "family:" + fid, "contains")
    eligible_types: dict[str, set[str]] = {}
    for row in safeguards["safeguards"]:
        check()
        sid = "safeguard:" + row["safeguard_id"]
        eligible_types[row["safeguard_id"]] = set(row.get("asset_types") or [])
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

    check()
    # Keyed exactly as the freshness projection records each source row.
    freshness = (
        storage.freshness
        if storage is not None
        else {
            (str(r.get("tenant_id") or ""), str(r.get("event_id") or ""), str(r.get("asset_id") or "")): r
            for r in read_jsonl(lake / "gold/evidence_freshness.jsonl", missing_ok=True, base_dir=lake)
        }
    )
    triage = {} if storage is None else storage.triage
    if storage is None:
        for decision in sorted(list_events(lake), key=lambda r: instant_sort_key(r.get("occurred_at"))):
            triage[decision["violation_id"]] = decision
    events = (
        []
        if storage is not None
        else read_jsonl(lake / "silver/normalized_events.jsonl", missing_ok=True, base_dir=lake)
    )
    asset_names = (
        storage.names
        if storage is not None
        else names_from_assets(read_jsonl(lake / "gold/asset_risk.jsonl", missing_ok=True, base_dir=lake))
    )
    evidence_by_event = defaultdict(list)
    findings_by_control: dict[str, set[str]] = defaultdict(set)
    check()
    ordered_events = sorted(((canonical_sha256(event), event) for event in events), key=lambda item: item[0])
    # Safeguard bindings are judged on every type recorded for the asset, as in
    # the CCF assessment, so one event cannot validate a binding on its own.
    asset_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    for _, event in ordered_events:
        asset_types[source_asset_key({**event, "asset_id": event.get("asset_id") or ""})].add(
            str(event.get("asset_type"))
        )
    for event_hash, event in ordered_events if storage is None else storage.events():
        check()
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
        eid = "evidence:" + event_hash
        if storage is None:
            evidence_by_event[(account, event.get("event_id"), asset)].append(eid)
        else:
            storage.evidence(account, event.get("event_id"), asset, eid)
        recorded = str(event.get("tenant_id") or ""), str(event.get("event_id") or "")
        # Rows written without an asset id apply to the event as a whole.
        fresh = freshness.get((*recorded, str(event.get("asset_id") or "")), freshness.get((*recorded, ""), {}))
        node(
            "evidence_type",
            eid,
            event.get("event_type") or "Evidence",
            **observed,
            event_type=event.get("event_type"),
            control_ids=sorted(set(event.get("control_ids") or [])),
            evidence_id=event.get("event_id"),
            evidence_ref=event.get("evidence_ref"),
            raw_sha256=event.get("raw_sha256"),
            collected_at=event.get("evidence_collected_at"),
            freshness_evaluated_at=fresh.get("evaluated_at"),
            freshness_expires_at=fresh.get("expires_at"),
            freshness_age_minutes=fresh.get("age_minutes"),
            freshness_status=fresh.get("status", "missing"),
            status=event.get("status"),
            basis="Observed record; not a compliance verdict",
        )
        if asset:
            kind = "repository" if event.get("asset_type") == "repository" else "asset"
            node(
                kind,
                aid,
                event.get("asset_name") or asset_name_for(event, asset_names) or asset,
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
        for cid in sorted(set(event.get("control_ids") or [])):
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
                    event_type=event.get("event_type"),
                    control_ids=[cid],
                    basis="Observed failing evidence; review the linked control and affected asset",
                    next_action="Review evidence and assign remediation in Findings",
                )
                edge(aid, finding, "has_finding")
                edge(finding, eid, "has_evidence")
                if storage is None:
                    findings_by_control[cid].add(finding)
                else:
                    storage.finding(cid, finding, _SEVERITY_RANK.get(str(event.get("severity")), 4))
        for sid in sorted(set(event.get("safeguard_ids") or [])):
            if binding_applies(
                asset_types[(account, asset)] if storage is None else storage.types(account, asset),
                eligible_types.get(sid, set()),
            ):
                edge("safeguard:" + sid, eid, "has_evidence")
            else:
                edge(
                    "safeguard:" + sid,
                    eid,
                    "has_evidence",
                    binding="invalid_asset_type",
                    binding_reason=INVALID_ASSET_TYPE_REASON,
                )

    # A failing control lists its findings (owner, next action) on the control
    # itself, so the default walk reaches them without widening the canvas.
    summaries = (
        (
            (
                cid,
                len(keys),
                sorted(keys, key=lambda key: (_SEVERITY_RANK.get(str(nodes[key].get("severity")), 4), key))[
                    :_FINDING_SUMMARY_LIMIT
                ],
            )
            for cid, keys in sorted(findings_by_control.items())
        )
        if storage is None
        else storage.summaries(_FINDING_SUMMARY_LIMIT)
    )
    for cid, count, ranked in summaries:
        check()
        if (control := nodes.get("control:" + cid)) is not None:
            control["finding_count"] = count
            control["findings"] = [{field: nodes[key].get(field) for field in _FINDING_SUMMARY} for key in ranked]
            nodes["control:" + cid] = control

    check()
    if platform_tenant_id is not None:
        from security_lakehouse.investigation_entities import add_entity_bindings

        add_entity_bindings(lake, platform_tenant_id, nodes, node, edge, check)
    add_repository_context(lake, node, edge, _id, evidence_by_event if storage is None else storage)
    check()

    for vendor in vendors or []:
        check()
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
        vendor_node = nodes[vid]
        vendor_node["next_action"] = (
            f"{unresolved} recorded asset references are not present in this evidence generation. Review vendor links."
            if unresolved
            else "Review the vendor assessment and its explicitly recorded asset links."
        )

        nodes[vid] = vendor_node

    return nodes, edges, frameworks


@generation_reader
def investigation_graph(
    lake: Path,
    *,
    platform_tenant_id: str | None = None,
    root: str | None = None,
    view: str = "controls",
    depth: int = 2,
    limit: int = 150,
    layers: set[str] | None = None,
    search: str = "",
    root_offset: int = 0,
    framework: str = "",
    control_offset: int = 0,
    vendors: list[dict[str, Any]] | None = None,
    expected_version: str | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Build one bounded slice; ``checkpoint`` may raise to abort before any result exists."""
    validate_bounds(view=view, depth=depth, limit=limit, root_offset=root_offset, control_offset=control_offset)
    check = checkpoint or (lambda: None)
    check()
    source = pinned_path(lake / "silver/normalized_events.jsonl")
    if (
        source.is_file()
        and source.stat().st_size >= _PERSISTENT_MIN_BYTES
        and _model_key(lake, vendors, check, platform_tenant_id) is not None
    ):
        indexed = read_persistent_index(
            lake,
            deepcopy(vendors),
            platform_tenant_id,
            check,
            model_files=_MODEL_FILES,
            build_model=_build_model,
            graph_version=_graph_version,
            root=root,
            view=view,
            depth=depth,
            limit=limit,
            layers=layers,
            search=search,
            root_offset=root_offset,
            framework=framework,
            control_offset=control_offset,
            expected_version=expected_version,
            allow_build=source.stat().st_size <= 8 * 1024 * 1024,
        )
        if indexed is not None:
            return indexed
    nodes, _edges, frameworks, version, indexes = _model(lake, vendors, check, platform_tenant_id)

    check()
    if expected_version and version != expected_version:
        raise ValueError("graph version changed; refresh before expanding")
    # Unfiltered reads use membership views and preordered roots directly. Layer
    # filters alter degree ordering, so only that query rebuilds the root order.
    if layers and set(indexes.counts).issubset(layers):
        layers = None
    eligible = {key for key, n in nodes.items() if n["kind"] in layers} if layers else nodes.keys()
    outgoing, incoming = indexes.outgoing, indexes.incoming

    def linked(links: dict[str, tuple[str, ...]], key: str) -> set[str]:
        if layers and key not in eligible:
            return set()
        result = set(links.get(key, ()))
        return result & eligible if layers else result

    def neighbors(key: str) -> set[str]:
        return linked(outgoing, key) | linked(incoming, key)

    choices: tuple[dict[str, Any], ...] | list[dict[str, Any]] = indexes.roots[view]
    if layers or search:
        folded = search.casefold()
        choices = [n for n in choices if n["id"] in eligible and folded in (n["label"] + " " + n["id"]).casefold()]
        if layers:
            choices.sort(
                key=lambda n: (
                    n["kind"] != ("environment" if view == "environment" else "control"),
                    -len(neighbors(n["id"])),
                    n.get("source_account_id", ""),
                    n["id"],
                )
            )
    if root is None:
        root = (
            default_root(choices, lambda key: any(nodes[t]["kind"] == "evidence_type" for t in linked(outgoing, key)))
            if layers or search
            else indexes.defaults[view]
        )
    selected = {root} if root is not None and root in eligible else set()
    ordered = list(selected)
    distances = {key: 0 for key in selected}
    upstream = set()
    # A control path walks upstream and downstream independently: reaching a
    # shared framework or safeguard must not turn back into sibling controls.
    walks = (outgoing, incoming) if view == "controls" else (None,)
    for links in walks:
        frontier = {root} if root is not None and root in eligible else set()
        visited = set(frontier)
        for hop in range(1, depth + 1):
            following = set()
            check()
            for key in frontier:
                if view != "controls" and key != root and nodes[key]["kind"] in {"framework", "control", "safeguard"}:
                    continue
                following.update((linked(links, key) if links is not None else neighbors(key)) - visited)
            visited.update(following)
            for key in following:
                distances[key] = min(distances.get(key, hop), hop)
            if links is incoming:
                upstream.update(following)
            ordered.extend(sorted(following - selected))
            selected.update(following)
            frontier = following
            if links is outgoing:
                # Producing sources point inward to evidence. Show them as context
                # without expanding into the source's other records.
                producers = {
                    key
                    for evidence in following
                    if nodes[evidence]["kind"] == "evidence_type"
                    for key in linked(incoming, evidence)
                    if nodes[key]["kind"] == "source"
                } - selected
                visited.update(producers)
                for key in producers:
                    distances[key] = hop + 1
                ordered.extend(sorted(producers))
                selected.update(producers)
    ordered.sort(key=lambda key: (distances[key], key not in upstream, key))
    framework_groups = []
    grouped_controls: dict[str, list[str]] = defaultdict(list)
    selected_framework = ""
    control_count = 0
    if root in nodes and nodes[root]["kind"] == "safeguard":
        # Count the full direct mapping set before the response cap. Return only
        # one framework page, keeping original nodes and recorded edge endpoints.
        for key in sorted(linked(incoming, root)):
            if nodes[key]["kind"] == "control":
                grouped_controls[nodes[key]["framework_id"]].append(key)
        framework_groups = [
            {"framework_id": fid, "label": frameworks.get(fid, {}).get("name", fid), "control_count": len(keys)}
            for fid, keys in sorted(grouped_controls.items())
        ]
        selected_framework = framework or next(iter(sorted(grouped_controls)), "")
        page_controls = grouped_controls.get(selected_framework, [])
        control_count = len(page_controls)
        page_ids = {root, *page_controls[control_offset : control_offset + 5]}
        # Only framework context for this page; taxonomy and other frameworks
        # remain available by selecting another starting point.
        page_ids.add("framework:" + selected_framework)
        # Keep recorded evidence and its assets available alongside mappings.
        page_ids.update(
            key for key in ordered if nodes[key]["kind"] not in {"control", "framework", "ccf_family", "ccf_category"}
        )
        ordered = [key for key in ordered if key in page_ids]
        selected = set(ordered)
    check()
    kept = set(ordered[:limit])
    # Inspect only outgoing edges of returned nodes, preserving canonical edge
    # insertion order (including reciprocal and differently typed edges).
    edge_ordinals = []
    for key in kept:
        check()
        for ordinal in indexes.edge_ordinals.get(key, ()):
            if indexes.edge_rows[ordinal]["target"] in kept:
                edge_ordinals.append(ordinal)
    return {
        "nodes": [deepcopy(nodes[k]) for k in ordered[:limit]],
        "edges": [deepcopy(indexes.edge_rows[i]) for i in sorted(edge_ordinals)],
        "counts": dict(indexes.counts),
        "version": version,
        "root": root,
        "root_missing": root is not None and root not in eligible,
        "roots": [
            {"id": n["id"], "label": n["label"], "kind": n["kind"]} for n in choices[root_offset : root_offset + 50]
        ],
        "root_count": len(choices),
        "root_offset": root_offset,
        "next_root_offset": root_offset + 50 if root_offset + 50 < len(choices) else None,
        "framework_groups": framework_groups,
        "selected_framework": selected_framework,
        "control_count": control_count,
        "control_offset": control_offset,
        "next_control_offset": control_offset + 5 if control_offset + 5 < control_count else None,
        "depth": depth,
        "limit": limit,
        "truncated": len(selected) > limit,
        "matching_nodes": len(selected),
        "boundary": "Recorded relationships; not network reachability or complete inventory",
    }
