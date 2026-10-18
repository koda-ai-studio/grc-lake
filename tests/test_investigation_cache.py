"""Repeated reads reuse only generation-scoped, independently owned graph data."""

import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from security_lakehouse import investigation_graph as graph
from security_lakehouse.generations import new_generation, pin_generation, publish_generation, seal_generation
from security_lakehouse.io import write_json, write_jsonl_from_iterable
from security_lakehouse.tracking import append_event


def generation(lake, label="first"):
    result = new_generation(lake)
    write_json(result / "catalog/control_map.json", {"controls": [{"control_id": "TEST", "framework_id": "soc2"}]})
    write_json(result / "catalog/safeguards.json", {"safeguards": []})
    write_jsonl_from_iterable(
        result / "silver/normalized_events.jsonl",
        [
            {
                "event_id": "event",
                "tenant_id": "account",
                "asset_id": "asset",
                "asset_name": label,
                "event_type": "identity.test",
                "status": "fail",
                "control_ids": ["TEST"],
            }
        ],
    )
    seal_generation(result, legacy=True)
    return result


def spy_build(monkeypatch):
    calls = []
    original = graph._build_model

    def build(*args):
        calls.append(args[0])
        return original(*args)

    monkeypatch.setattr(graph, "_build_model", build)
    return calls


def test_repeated_and_changed_queries_reuse_build_without_leaking_mutable_responses(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path))
    calls = spy_build(monkeypatch)
    original = graph.investigation_graph(tmp_path, root="control:TEST", depth=3)
    first = copy.deepcopy(original)
    original["nodes"][0]["label"] = "corrupted"
    next(n for n in original["nodes"] if n["kind"] == "evidence_type")["control_ids"].append("foreign")
    original["edges"][0]["kind"] = "corrupted"
    assert graph.investigation_graph(tmp_path, root="control:TEST", depth=3) == first
    graph.investigation_graph(tmp_path, view="environment", search="first", layers={"asset"})
    assert len(calls) == 1


def test_pinned_generation_and_same_named_other_tenant_never_share_model(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    publish_generation(a, generation(a, "tenant-a"))
    publish_generation(b, generation(b, "tenant-b"))
    calls = spy_build(monkeypatch)
    old = graph.investigation_graph(a)
    assert old["version"] != graph.investigation_graph(b)["version"]
    with pin_generation(a):
        publish_generation(a, generation(a, "replacement"))
        assert graph.investigation_graph(a) == old
    with pytest.raises(ValueError, match="version changed"):
        graph.investigation_graph(a, expected_version=old["version"])
    assert len(calls) == 3


def test_triage_and_vendor_changes_invalidate_versions(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path))
    calls = spy_build(monkeypatch)
    vendors = [{"id": "vendor", "vendor_name": "Vendor", "status": "pending"}]
    first = graph.investigation_graph(tmp_path, vendors=vendors)
    assert graph.investigation_graph(tmp_path, vendors=copy.deepcopy(vendors)) == first
    append_event(tmp_path, violation_id="TEST:event", actor="reviewer", state="resolved", assignee="owner")
    with pytest.raises(ValueError, match="version changed"):
        graph.investigation_graph(tmp_path, vendors=vendors, expected_version=first["version"])
    second = graph.investigation_graph(tmp_path, vendors=vendors, view="investigation", depth=3)
    finding = next(n for n in second["nodes"] if n["kind"] == "finding")
    assert (finding["status"], finding["owner"]) == ("resolved", "owner")
    vendors[0]["status"] = "approved"
    with pytest.raises(ValueError, match="version changed"):
        graph.investigation_graph(tmp_path, vendors=vendors, expected_version=second["version"])
    assert len(calls) == 3


def test_cold_concurrent_reads_share_one_completed_build(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path))
    original = graph._build_model
    entered, release, waiting = Event(), Event(), Event()
    calls = []

    def build(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(graph, "_build_model", build)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(graph.investigation_graph, tmp_path)
        assert entered.wait(5)
        second = pool.submit(graph.investigation_graph, tmp_path, checkpoint=waiting.set)
        assert waiting.wait(5)
        release.set()
        assert first.result() == second.result()
    assert len(calls) == 1


def test_mutable_legacy_lakes_are_not_cached(tmp_path, monkeypatch):
    calls = spy_build(monkeypatch)
    graph.investigation_graph(tmp_path)
    graph.investigation_graph(tmp_path)
    assert len(calls) == 2


def test_same_generation_name_in_different_roots_does_not_share(tmp_path, monkeypatch):
    import shutil

    a, b = tmp_path / "a", tmp_path / "b"
    source = generation(a, "copied")
    publish_generation(a, source)
    destination = b / "generations" / source.name
    shutil.copytree(source, destination)
    publish_generation(b, destination)
    calls = spy_build(monkeypatch)
    assert graph.investigation_graph(a) == graph.investigation_graph(b)
    assert len(calls) == 2


def test_changed_during_build_is_not_retained(tmp_path, monkeypatch):
    publish_generation(tmp_path, generation(tmp_path))
    original = graph._build_model
    calls = []

    def build(*args):
        model = original(*args)
        if not calls:
            append_event(tmp_path, violation_id="TEST:event", actor="reviewer", state="resolved")
        calls.append(1)
        return model

    monkeypatch.setattr(graph, "_build_model", build)
    first = graph.investigation_graph(tmp_path)
    second = graph.investigation_graph(tmp_path)
    assert first["version"] != second["version"]
    assert graph.investigation_graph(tmp_path) == second
    assert len(calls) == 2


def test_cache_does_not_hide_corrupt_or_deleted_artifacts(tmp_path):
    sealed = generation(tmp_path)
    publish_generation(tmp_path, sealed)
    graph.investigation_graph(tmp_path)
    # Simulate corruption outside the supported generation writer. A warm
    # model must not bypass the normal parse error on the changed artifact.
    (sealed / "silver/normalized_events.jsonl").write_text("{broken\n")
    with pytest.raises(ValueError):
        graph.investigation_graph(tmp_path)
    (sealed / "silver/normalized_events.jsonl").unlink()
    result = graph.investigation_graph(tmp_path)
    assert result["counts"].get("evidence_type", 0) == 0


def test_missing_frozen_catalog_uses_live_fallback_without_reuse(tmp_path, monkeypatch):
    from tools.benchmark_investigation import make_generation

    publish_generation(tmp_path, make_generation(tmp_path, 2, "tenant"))
    calls = spy_build(monkeypatch)
    graph.investigation_graph(tmp_path)
    graph.investigation_graph(tmp_path)
    assert len(calls) == 2


def test_navigation_catalog_change_invalidates_warm_graph(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    write_json(registry, {"frameworks": [{"framework_id": "soc2", "name": "Before"}]})
    monkeypatch.setattr(graph.catalog, "DEFAULT_FRAMEWORK_REGISTRY", registry)
    publish_generation(tmp_path, generation(tmp_path))
    first = graph.investigation_graph(tmp_path)
    write_json(registry, {"frameworks": [{"framework_id": "soc2", "name": "After"}]})
    with pytest.raises(ValueError, match="version changed"):
        graph.investigation_graph(tmp_path, expected_version=first["version"])


def test_cancellation_is_checked_on_a_warm_hit(tmp_path):
    publish_generation(tmp_path, generation(tmp_path))
    graph.investigation_graph(tmp_path)

    def cancel():
        raise RuntimeError("disconnected")

    with pytest.raises(RuntimeError, match="disconnected"):
        graph.investigation_graph(tmp_path, checkpoint=cancel)
