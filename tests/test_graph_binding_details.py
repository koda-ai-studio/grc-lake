"""Prepared graphs preserve the same applicability explanation as in-memory graphs."""

import sqlite3

from security_lakehouse import investigation_graph as graph
from security_lakehouse.investigation_staging import Staging
from test_investigation_graph_accuracy import _safeguard_lake


def test_staged_graph_keeps_complete_recorded_asset_types(tmp_path):
    _safeguard_lake(tmp_path)

    def check():
        return None

    expected_nodes, expected_edges, _ = graph._build_model(tmp_path, [], check)
    with sqlite3.connect(":memory:") as db:
        staging = Staging(db, tmp_path, check)
        nodes, edges, _ = graph._build_model(tmp_path, [], check, storage=staging)
        assert list(nodes.values()) == list(expected_nodes.values())
        assert list(edges.values()) == list(expected_edges.values())
        invalid = [edge for edge in edges.values() if edge.get("binding")]
        assert len(invalid) == 3
        assert all(edge.get("recorded_asset_types") for edge in invalid)
