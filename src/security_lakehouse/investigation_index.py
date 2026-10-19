"""Derived navigation indexes owned and budgeted with one completed graph model."""

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

ROOT_KINDS = {
    "controls": frozenset({"control", "safeguard", "ccf_category", "ccf_family", "framework"}),
    "environment": frozenset({"environment", "account", "repository", "asset"}),
    "investigation": frozenset({"finding", "source", "vendor", "evidence_type"}),
}


class ReadIndexes(NamedTuple):
    # Tuples retain compact adjacency without a mutable set per node/direction.
    # NamedTuple also lets the cache's reachable-object accounting include all
    # index storage and deduplicate node/edge objects shared with the model.
    outgoing: dict[str, tuple[str, ...]]
    incoming: dict[str, tuple[str, ...]]
    edge_rows: tuple[dict[str, Any], ...]
    edge_ordinals: dict[str, tuple[int, ...]]
    counts: dict[str, int]
    roots: dict[str, tuple[dict[str, Any], ...]]
    defaults: dict[str, str | None]


def default_root(
    choices: tuple[dict[str, Any], ...] | list[dict[str, Any]], observed: Callable[[str], bool]
) -> str | None:
    first_observed = None
    for node in choices:
        if node["kind"] == "control" and observed(node["id"]):
            if node["id"] == "control:SOC2-CC6.1":
                return str(node["id"])
            if first_observed is None:
                first_observed = str(node["id"])
    return first_observed or (str(choices[0]["id"]) if choices else None)


def build_indexes(
    nodes: Mapping[str, dict[str, Any]], edges: Mapping[str, dict[str, Any]], check: Callable[[], None]
) -> ReadIndexes:
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    ordinals: dict[str, list[int]] = defaultdict(list)
    rows = tuple(edges.values())
    for ordinal, edge in enumerate(rows):
        check()
        source, target = edge["source"], edge["target"]
        if source in nodes and target in nodes:
            outgoing[source].add(target)
            incoming[target].add(source)
            ordinals[source].append(ordinal)
    counts: Counter[str] = Counter()
    candidates: dict[str, list[dict[str, Any]]] = {view: [] for view in ROOT_KINDS}
    degrees = {}
    for key, node in nodes.items():
        check()
        counts[node["kind"]] += 1
        degrees[key] = len(outgoing.get(key, set()) | incoming.get(key, set()))
        for view, kinds in ROOT_KINDS.items():
            if node["kind"] in kinds:
                candidates[view].append(node)
    roots = {}
    defaults = {}
    for view, choices in candidates.items():
        check()
        choices.sort(
            key=lambda n: (
                n["kind"] != ("environment" if view == "environment" else "control"),
                -degrees[n["id"]],
                n.get("source_account_id", ""),
                n["id"],
            )
        )
        roots[view] = tuple(choices)
        defaults[view] = default_root(
            choices, lambda key: any(nodes[t]["kind"] == "evidence_type" for t in outgoing.get(key, ()))
        )
    check()
    return ReadIndexes(
        {key: tuple(values) for key, values in outgoing.items()},
        {key: tuple(values) for key, values in incoming.items()},
        rows,
        {key: tuple(values) for key, values in ordinals.items()},
        dict(counts),
        roots,
        defaults,
    )
