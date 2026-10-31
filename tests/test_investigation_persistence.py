"""Persistent navigation must preserve recorded graph semantics without whole-model reads."""

import pytest

from security_lakehouse import investigation_graph as graph
from security_lakehouse.generations import publish_generation
from security_lakehouse.investigation_cache import ModelCache
from test_investigation_cache import generation


def test_persisted_neighborhood_survives_process_cache_loss(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path))
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0, raising=False)
    expected = graph.investigation_graph(tmp_path, root="control:TEST", depth=3)
    monkeypatch.setattr(graph, "_MODEL_CACHE", ModelCache())

    def forbidden(*args, **kwargs):
        raise AssertionError("a persisted neighborhood must not rebuild the complete model")

    monkeypatch.setattr(graph, "_build_model", forbidden)
    assert graph.investigation_graph(tmp_path, root="control:TEST", depth=3) == expected


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"view": "environment", "depth": 3},
        {"view": "investigation", "depth": 3},
        {"root": "control:TEST", "depth": 3, "limit": 2},
        {"root": "control:TEST", "layers": {"control", "evidence_type"}},
        {"root": "absent"},
        {"root_offset": 50},
        {"search": "missing"},
    ],
)
def test_persisted_query_equals_existing_builder(tmp_path, monkeypatch, query):
    publish_generation(tmp_path, generation(tmp_path))
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 10**12, raising=False)
    expected = graph.investigation_graph(tmp_path, **query)
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    assert graph.investigation_graph(tmp_path, **query) == expected


def test_index_reuse_survives_timestamp_settling(tmp_path, monkeypatch):
    from security_lakehouse import io

    publish_generation(tmp_path, generation(tmp_path))
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    expected = graph.investigation_graph(tmp_path)
    monkeypatch.setattr(io, "_RACY_TIMESTAMP_WINDOW_NS", 0)

    def forbidden(*args, **kwargs):
        raise AssertionError("timestamp settling must not rebuild an unchanged index")

    monkeypatch.setattr(graph, "_build_model", forbidden)
    assert graph.investigation_graph(tmp_path) == expected


def test_index_preserves_golden_queries_and_governance(tmp_path, monkeypatch):
    from security_lakehouse.cli import main
    from security_lakehouse.tracking import append_event

    assert main(["fixtures", "load", "--company", "golden", "--out", str(tmp_path), "--rebase-times"]) == 0
    vendors = [{"id": "fixture-vendor", "vendor_name": "Fixture", "status": "pending", "asset_refs": []}]
    queries = [
        {"view": view, "depth": depth, "limit": limit}
        for view in ("controls", "environment", "investigation")
        for depth in (1, 2, 3)
        for limit in (1, 150)
    ]
    queries += [
        {"root": "safeguard:SG-IDENTITY-001", "depth": 3, "framework": framework, "control_offset": offset}
        for framework in ("", "soc2", "missing")
        for offset in (0, 5, 500)
    ]
    queries += [
        {"view": view, "search": term, "layers": layers}
        for view in ("controls", "environment", "investigation")
        for term in ("", "a", "missing")
        for layers in ({"control", "evidence_type"}, {"asset"}, {"absent"})
    ]
    queries += [{"root": "safeguard:SG-IDENTITY-001", "layers": {"control"}, "depth": 3}]
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 10**12)
    expected = [
        graph.investigation_graph(tmp_path, platform_tenant_id="default", vendors=vendors, **q) for q in queries
    ]
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    for query, result in zip(queries, expected, strict=True):
        assert graph.investigation_graph(tmp_path, platform_tenant_id="default", vendors=vendors, **query) == result, (
            query
        )
    original = expected[0]
    append_event(tmp_path, violation_id="SOC2-CC6.1:fixture", actor="reviewer", state="resolved")
    vendors[0]["status"] = "approved"
    with pytest.raises(ValueError, match="version changed"):
        graph.investigation_graph(
            tmp_path, platform_tenant_id="default", vendors=vendors, expected_version=original["version"]
        )


def test_persistent_scope_and_pinned_generation_are_independent(tmp_path, monkeypatch):
    from security_lakehouse.generations import pin_generation

    a, b = tmp_path / "a", tmp_path / "b"
    publish_generation(a, generation(a, "tenant-a"))
    publish_generation(b, generation(b, "tenant-b"))
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    first = graph.investigation_graph(a, platform_tenant_id="a")
    assert graph.investigation_graph(b, platform_tenant_id="b")["version"] != first["version"]
    with pin_generation(a):
        publish_generation(a, generation(a, "replacement"))
        assert graph.investigation_graph(a, platform_tenant_id="a") == first
    with pytest.raises(ValueError, match="version changed"):
        graph.investigation_graph(a, platform_tenant_id="a", expected_version=first["version"])


def test_cancelled_index_build_is_not_published(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path))
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls > 100:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        graph.investigation_graph(tmp_path, checkpoint=cancel)
    assert not (tmp_path / ".graph-index/index.sqlite").exists()
    assert not list((tmp_path / ".graph-index").glob(".building-*"))
    assert graph.investigation_graph(tmp_path)["nodes"]


def test_persistent_index_does_not_hide_source_corruption(tmp_path, monkeypatch):
    sealed = generation(tmp_path)
    publish_generation(tmp_path, sealed)
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    graph.investigation_graph(tmp_path)
    (sealed / "silver/normalized_events.jsonl").write_text("{broken\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        graph.investigation_graph(tmp_path)


def test_index_directory_cannot_escape_lake(tmp_path, monkeypatch):
    lake, outside = tmp_path / "lake", tmp_path / "outside"
    outside.mkdir()
    publish_generation(lake, generation(lake))
    (lake / ".graph-index").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    with pytest.raises(ValueError, match="symlinks"):
        graph.investigation_graph(lake)
    assert not list(outside.iterdir())


def test_operator_can_prepare_index_before_http_reads(tmp_path, monkeypatch, capsys):
    from security_lakehouse.cli import main

    publish_generation(tmp_path, generation(tmp_path))
    assert main(["graph", "prepare-index", "--lake", str(tmp_path), "--tenant", "tenant-a"]) == 0
    import json

    receipt = json.loads(capsys.readouterr().out)
    assert receipt["counts"]["evidence_type"] == 1
    assert receipt["index_bytes"] > 0
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)

    def forbidden(*args, **kwargs):
        raise AssertionError("prepared HTTP scope must not rebuild")

    monkeypatch.setattr(graph, "_build_model", forbidden)
    assert (
        graph.investigation_graph(tmp_path, platform_tenant_id="tenant-a", vendors=[])["version"] == receipt["version"]
    )


def test_modified_derived_index_cannot_change_recorded_evidence(tmp_path, monkeypatch):
    import json
    import sqlite3

    publish_generation(tmp_path, generation(tmp_path))
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    expected = graph.investigation_graph(tmp_path, root="control:TEST")
    with sqlite3.connect(tmp_path / ".graph-index/index.sqlite") as db:
        row = json.loads(db.execute("SELECT data FROM nodes WHERE id='control:TEST'").fetchone()[0])
        row["status"] = "pass"
        row["label"] = "tampered"
        db.execute("UPDATE nodes SET data=? WHERE id='control:TEST'", (json.dumps(row),))
    assert graph.investigation_graph(tmp_path, root="control:TEST") == expected


def test_fresh_process_reuses_prepared_index(tmp_path):
    import json
    import subprocess
    import sys

    from security_lakehouse.graph_index_cli import prepare_index

    publish_generation(tmp_path, generation(tmp_path))
    expected = prepare_index(tmp_path)
    program = """
import json, sys
from pathlib import Path
from security_lakehouse import investigation_graph as graph
graph._PERSISTENT_MIN_BYTES = 0
def forbidden(*args, **kwargs):
    raise AssertionError('fresh process must reuse the prepared index')
graph._build_model = forbidden
print(json.dumps(graph.investigation_graph(Path(sys.argv[1]))))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, str(tmp_path)], capture_output=True, text=True, timeout=20
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["version"] == expected["version"]


def test_concurrent_processes_publish_one_complete_index(tmp_path):
    import json
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    publish_generation(tmp_path, generation(tmp_path))
    program = """
import json, sys
from pathlib import Path
from security_lakehouse.graph_index_cli import prepare_index
print(json.dumps(prepare_index(Path(sys.argv[1]))))
"""

    def prepare(_):
        completed = subprocess.run(
            [sys.executable, "-c", program, str(tmp_path)], capture_output=True, text=True, timeout=20
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(prepare, range(3)))
    assert len({r["version"] for r in results}) == 1
    assert not list((tmp_path / ".graph-index").glob(".building-*"))


def test_large_unprepared_read_does_not_start_index_build(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path, "x" * (9 * 2**20)))
    original = graph._build_model

    def ordinary(*args, **kwargs):
        assert kwargs.get("storage") is None, "HTTP reads must not prepare a large index"
        return original(*args, **kwargs)

    monkeypatch.setattr(graph, "_build_model", ordinary)
    assert graph.investigation_graph(tmp_path)["nodes"]
    assert not (tmp_path / ".graph-index").exists()


def test_operator_external_database_requires_explicit_tenant(tmp_path, monkeypatch, capsys):
    from security_lakehouse.cli import main

    monkeypatch.setenv("GRC_LAKE_DATABASE_URL", "sqlite:///" + str(tmp_path / "external.db"))
    assert main(["graph", "prepare-index", "--lake", str(tmp_path)]) == 1
    assert "requires --tenant" in capsys.readouterr().err
    assert not (tmp_path / "external.db").exists()


def test_waiting_preparer_can_cancel_without_changing_index(tmp_path):
    import fcntl

    from security_lakehouse.graph_index_cli import prepare_index
    from security_lakehouse.io import file_sha256

    publish_generation(tmp_path, generation(tmp_path))
    prepare_index(tmp_path)
    path = tmp_path / ".graph-index/index.sqlite"
    original = file_sha256(path)
    publish_generation(tmp_path, generation(tmp_path, "replacement"))
    with (path.parent / "build.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(ValueError, match="timed out"):
            prepare_index(tmp_path, timeout=0.1)
    assert file_sha256(path) == original
    assert not list(path.parent.glob(".building-*"))
    assert prepare_index(tmp_path)["version"]


def test_prepared_read_does_not_require_directory_write(tmp_path, monkeypatch):
    from security_lakehouse.graph_index_cli import prepare_index

    publish_generation(tmp_path, generation(tmp_path))
    prepared = prepare_index(tmp_path)
    directory = tmp_path / ".graph-index"
    directory.chmod(0o500)
    monkeypatch.setattr(graph, "_PERSISTENT_MIN_BYTES", 0)
    try:
        assert graph.investigation_graph(tmp_path)["version"] == prepared["version"]
    finally:
        directory.chmod(0o700)


def test_root_ranking_does_not_rescan_all_evidence_for_each_asset():
    import sqlite3

    from security_lakehouse.investigation_sqlite import initialize, populate

    with sqlite3.connect(":memory:") as db:
        initialize(db)
        nodes = [
            {"id": f"{kind}:{i}", "kind": kind, "label": str(i)}
            for i in range(1000)
            for kind in ("asset", "evidence_type")
        ]
        edges = [{"id": f"edge:{i}", "source": f"asset:{i}", "target": f"evidence_type:{i}"} for i in range(1000)]
        steps = 0

        def budget():
            nonlocal steps
            steps += 1
            return int(steps > 500)

        db.set_progress_handler(budget, 1000)
        populate(db, nodes, edges, version="fixture", key="fixture", frameworks={}, check=lambda: None)
        assert db.execute("SELECT count(*) FROM roots WHERE view='environment'").fetchone()[0] == 1000


def test_index_disk_ceiling_fails_without_publishing_partial_state(tmp_path, monkeypatch):
    import sqlite3

    from security_lakehouse import investigation_persistence
    from security_lakehouse.graph_index_cli import prepare_index

    publish_generation(tmp_path, generation(tmp_path))
    monkeypatch.setattr(investigation_persistence, "MAX_INDEX_BYTES", 4 * 4096)
    with pytest.raises(sqlite3.OperationalError, match="full"):
        prepare_index(tmp_path)
    assert not (tmp_path / ".graph-index/index.sqlite").exists()
    assert not list((tmp_path / ".graph-index").glob(".building-*"))


def test_one_hop_response_edges_do_not_scan_the_whole_inventory():
    import sqlite3

    from security_lakehouse.investigation_sqlite import initialize, populate, query

    with sqlite3.connect(":memory:") as db:
        initialize(db)
        nodes = [{"id": "account:fixture", "kind": "account", "label": "Fixture"}] + [
            {"id": f"asset:{i}", "kind": "asset", "label": str(i)} for i in range(10000)
        ]
        edges = [{"id": f"edge:{i}", "source": "account:fixture", "target": f"asset:{i}"} for i in range(10000)]
        populate(db, nodes, edges, version="fixture", key="fixture", frameworks={}, check=lambda: None)
        calls = 0

        def budget():
            nonlocal calls
            calls += 1
            assert calls <= 20, "bounded response must not scan the full edge inventory"

        result = query(
            db,
            key="fixture",
            check=budget,
            root="account:fixture",
            view="environment",
            depth=1,
            limit=2,
            layers=None,
            search="",
            root_offset=0,
            framework="",
            control_offset=0,
            expected_version=None,
        )
        assert result["matching_nodes"] == 10001
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1


def test_temporary_staging_respects_disk_ceiling(tmp_path, monkeypatch):
    import sqlite3

    from security_lakehouse import investigation_persistence
    from security_lakehouse.graph_index_cli import prepare_index

    publish_generation(tmp_path, generation(tmp_path, "x" * (2 * 2**20)))
    monkeypatch.setattr(investigation_persistence, "MAX_INDEX_BYTES", 2**20)

    def must_not_populate(*args, **kwargs):
        pytest.fail("oversized scratch data reached final index population")

    monkeypatch.setattr(investigation_persistence.sql, "populate", must_not_populate)
    with pytest.raises(sqlite3.OperationalError, match="full"):
        prepare_index(tmp_path)
    assert not (tmp_path / ".graph-index/index.sqlite").exists()
    assert not list((tmp_path / ".graph-index").glob(".building-*"))
