"""Bounded graph neighborhoods preserve nearby context without visiting siblings."""

from security_lakehouse import investigation_graph as graph
from security_lakehouse.investigation_index import build_indexes


def _model(monkeypatch, *, count=10, guarded=False):
    nodes = {
        "control:root": {"id": "control:root", "kind": "control", "label": "Root"},
        "framework:parent": {"id": "framework:parent", "kind": "framework", "label": "Parent"},
        "control:sibling": {"id": "control:sibling", "kind": "control", "label": "Sibling"},
        "source:producer": {"id": "source:producer", "kind": "source", "label": "Producer"},
    }
    edges = {}

    def edge(source, target, kind):
        key = f"{source}:{target}"
        edges[key] = {"id": key, "source": source, "target": target, "kind": kind}

    edge("framework:parent", "control:root", "framework_has_control")
    edge("framework:parent", "control:sibling", "framework_has_control")
    for i in range(count):
        evidence, asset = f"evidence:{i:04}", f"asset:{i:04}"
        nodes[evidence] = {"id": evidence, "kind": "evidence_type", "label": evidence}
        nodes[asset] = {"id": asset, "kind": "asset", "label": asset}
        edge("control:root", evidence, "control_requires_evidence")
        edge(evidence, asset, "observed_on")
        edge("source:producer", evidence, "produces")
    indexes = build_indexes(nodes, edges, lambda: None)
    if guarded:

        class GuardedNodes(dict):
            def items(self):
                raise AssertionError("all-layer query rescanned the full node model")

        nodes = GuardedNodes(nodes)
    monkeypatch.setattr(graph, "_model", lambda *args: (nodes, edges, {}, "version", indexes))
    return nodes, indexes


def test_small_cap_retains_recorded_parent_before_deeper_evidence(monkeypatch, tmp_path):
    _model(monkeypatch)
    result = graph.investigation_graph(tmp_path, root="control:root", depth=3, limit=3)
    assert [node["id"] for node in result["nodes"]] == [
        "control:root",
        "framework:parent",
        "evidence:0000",
    ]
    assert result["truncated"] is True
    assert result["matching_nodes"] == 23
    assert "control:sibling" not in {node["id"] for node in result["nodes"]}
    kept = {node["id"] for node in result["nodes"]}
    assert all(edge["source"] in kept and edge["target"] in kept for edge in result["edges"])


def test_all_layers_reuses_index_without_full_model_scan(monkeypatch, tmp_path):
    _, indexes = _model(monkeypatch, count=2000, guarded=True)
    result = graph.investigation_graph(
        tmp_path,
        root="control:root",
        depth=1,
        limit=3,
        layers=set(indexes.counts),
    )
    assert result["root"] == "control:root"
    assert len(result["nodes"]) == 3
    assert result["matching_nodes"] == 2003


def test_selective_layers_still_filter_nodes_and_do_not_mutate_model(monkeypatch, tmp_path):
    nodes, _ = _model(monkeypatch)
    before = repr(nodes)
    result = graph.investigation_graph(
        tmp_path,
        root="control:root",
        depth=2,
        layers={"control", "evidence_type"},
    )
    assert {node["kind"] for node in result["nodes"]} == {"control", "evidence_type"}
    assert "control:sibling" not in {node["id"] for node in result["nodes"]}
    assert repr(nodes) == before
