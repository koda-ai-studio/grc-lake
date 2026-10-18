"""Graph fingerprints preserve expansion tokens without whole-model JSON copies."""

import tracemalloc

import pytest

from security_lakehouse import investigation_graph as graph
from security_lakehouse.io import canonical_sha256


@pytest.mark.parametrize("count", [0, 1, 127, 128, 129, 513])
def test_version_matches_existing_tokens_across_chunk_boundaries(count):
    nodes = [{"id": str(i), "label": "雪 ❄", "nested": {"b": None, "a": [True, 1.5]}} for i in range(count)]
    edges = [{"source": str(i), "target": str(i + 1), "kind": "contains"} for i in range(count)]
    assert graph._graph_version(iter(nodes), iter(edges), lambda: None) == canonical_sha256([nodes, edges])


def test_version_scratch_memory_is_bounded_for_large_models():
    # 24 MiB of JSON should not require another full string and UTF-8 copy.
    def rows():
        for i in range(12000):
            yield {"id": str(i), "label": str(i) + "x" * 2048}

    tracemalloc.start()
    try:
        version = graph._graph_version(rows(), iter(()), lambda: None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(version) == 64
    assert peak < 2 * 1024 * 1024, f"fingerprint used {peak / 2**20:.1f} MiB of scratch memory"


def test_version_cancellation_stops_consuming_the_model():
    consumed = 0

    def rows():
        nonlocal consumed
        for i in range(10000):
            consumed += 1
            yield {"id": str(i)}

    def cancel():
        if consumed >= 256:
            raise RuntimeError("disconnected")

    with pytest.raises(RuntimeError, match="disconnected"):
        graph._graph_version(rows(), iter(()), cancel)
    assert consumed <= 512


def test_reciprocal_edges_count_one_neighbor_and_keep_both_directions(tmp_path, monkeypatch):
    nodes = {key: {"id": key, "label": key, "kind": "asset"} for key in "abcde"}
    edges = {
        str(i): {"id": str(i), "source": source, "target": target, "kind": "contains"}
        for i, (source, target) in enumerate((("a", "b"), ("b", "a"), ("c", "d"), ("c", "e")))
    }
    monkeypatch.setattr(graph, "_build_model", lambda *args: (nodes, edges, {}))
    result = graph.investigation_graph(tmp_path, view="environment", depth=1)
    # Two distinct neighbors outrank the reciprocal pair's single neighbor.
    assert [row["id"] for row in result["roots"]] == ["c", "a", "b", "d", "e"]
    pair = graph.investigation_graph(tmp_path, view="environment", root="a", depth=1)
    assert {row["id"] for row in pair["nodes"]} == {"a", "b"}
    assert {(row["source"], row["target"]) for row in pair["edges"]} == {("a", "b"), ("b", "a")}
