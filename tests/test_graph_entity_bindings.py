"""Canonical alias graph edges require exact current evidence and tenant scope."""

import json

import pytest

from security_lakehouse.entity_history import record_bindings
from security_lakehouse.generations import new_generation, publish_generation, seal_generation
from security_lakehouse.investigation_graph import investigation_graph
from security_lakehouse.io import canonical_sha256, write_json, write_jsonl


@pytest.fixture
def bound_lake(tmp_path):
    rows = [
        dict(
            source=source,
            source_account_id="org",
            tenant_id="org",
            asset_type="device",
            asset_id="same-id",
            event_id=source + ":event",
            event_time="2026-10-21T12:00:00Z",
            raw_sha256="a" * 64,
            event_type="device.posture",
            control_ids=["TEST"],
            status="pass",
        )
        for source in ("intune", "crowdstrike")
    ]
    publish(tmp_path, rows, [{"tenant_id": "org", "event_id": r["event_id"], "status": "fresh"} for r in rows])
    manifest = {
        "schema_version": "1.0",
        "platform_tenant_id": "customer",
        "entities": [
            {
                "key": "device-17",
                "entity_type": "device",
                "bindings": [
                    {
                        **{k: r[k] for k in ("source", "source_account_id", "asset_type", "asset_id")},
                        "evidence_sha256": canonical_sha256(r),
                        "asserted_by": "reviewer",
                        "asserted_at": "2026-10-21T13:00:00Z",
                        "reason": "Enrollment reference",
                    }
                    for r in rows
                ],
            }
        ],
    }
    record_bindings(
        tmp_path,
        platform_tenant_id="customer",
        bindings=manifest,
        actor="operator",
        reason="fixture",
        expected_revision=0,
        request_id="initial",
    )
    return tmp_path, rows, manifest


def publish(lake, rows, freshness=()):
    generation = new_generation(lake)
    write_json(generation / "catalog/control_map.json", {"controls": [{"control_id": "TEST", "framework_id": "soc2"}]})
    write_json(generation / "catalog/safeguards.json", {"safeguards": []})
    write_jsonl(generation / "silver/normalized_events.jsonl", rows)
    write_jsonl(generation / "gold/evidence_freshness.jsonl", freshness)
    seal_generation(generation, legacy=True)
    publish_generation(lake, generation)


def graph(lake, **kwargs):
    return investigation_graph(lake, platform_tenant_id="customer", view="environment", depth=3, limit=100, **kwargs)


def test_aliases_link_exact_evidence_not_ambiguous_asset_ids(bound_lake):
    lake, rows, _ = bound_lake
    result = graph(lake)
    canonical = [n for n in result["roots"] if n["kind"] == "canonical_entity"]
    assert len(canonical) == 1
    result = graph(lake, root=canonical[0]["id"])
    aliases = [n for n in result["nodes"] if n["kind"] == "entity_alias"]
    assert len(aliases) == 2
    assert all(n["asserted_by"] == "reviewer" and n["binding_revision"] == 1 for n in aliases)
    references = [e for e in result["edges"] if e["kind"] == "assertion_references_evidence"]
    assert {e["target"] for e in references} == {"evidence:" + canonical_sha256(r) for r in rows}
    assert all("Caller-asserted" in n["basis"] for n in aliases)


def test_revocation_invalidates_cached_graph(bound_lake):
    lake, _, manifest = bound_lake
    before = graph(lake)
    record_bindings(
        lake,
        platform_tenant_id="customer",
        bindings={**manifest, "entities": []},
        actor="operator",
        reason="revoke",
        expected_revision=1,
        request_id="revoke",
    )
    after = graph(lake)
    assert before["version"] != after["version"]
    assert after["counts"].get("canonical_entity", 0) == 0
    with pytest.raises(ValueError, match="version"):
        graph(lake, expected_version=before["version"])


def test_missing_anchor_is_visible_without_an_identity_link(bound_lake):
    lake, rows, _ = bound_lake
    publish(lake, rows[1:])
    result = graph(lake)
    stale = [n for n in result["roots"] if n["kind"] == "entity_alias" and n["label"].startswith("Missing evidence")]
    assert stale
    missing = graph(lake, root=stale[0]["id"])
    node = next(n for n in missing["nodes"] if n["id"] == stale[0]["id"])
    assert node["status"] == "evidence_missing"
    assert not any(e["target"] == node["id"] or e["source"] == node["id"] for e in missing["edges"])


def test_namespace_not_inferred_from_source_account_and_not_reused_from_cache(bound_lake):
    lake, _, _ = bound_lake
    graph(lake)
    with pytest.raises(ValueError, match="tenant"):
        investigation_graph(lake, platform_tenant_id="other", view="environment")
    unscoped = investigation_graph(lake, view="environment")
    assert unscoped["counts"].get("canonical_entity", 0) == 0


def test_corrupt_history_cannot_reuse_cached_graph(bound_lake):
    lake, _, _ = bound_lake
    graph(lake)
    path = lake / "entities/bindings.jsonl"
    row = json.loads(path.read_text())
    row["reason"] = "modified"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="hash chain"):
        graph(lake)


def test_stale_anchor_has_no_identity_edges(bound_lake):
    lake, rows, _ = bound_lake
    publish(lake, rows, [{"tenant_id": "org", "event_id": r["event_id"], "status": "stale"} for r in rows])
    result = graph(lake)
    assert result["counts"].get("canonical_entity", 0) == 0
    aliases = [n for n in result["roots"] if n["kind"] == "entity_alias"]
    assert len(aliases) == 2
    focused = graph(lake, root=aliases[0]["id"])
    assert focused["nodes"][0]["status"] == "evidence_stale"
    assert focused["edges"] == []


@pytest.mark.parametrize("freshness", ["expired", "missing", None])
def test_out_of_sla_or_unknown_anchor_has_no_identity_edges(bound_lake, freshness):
    lake, rows, _ = bound_lake
    records = (
        []
        if freshness is None
        else [{"tenant_id": "org", "event_id": r["event_id"], "status": freshness} for r in rows]
    )
    publish(lake, rows, records)
    result = graph(lake)
    assert result["counts"].get("canonical_entity", 0) == 0
    aliases = [n for n in result["roots"] if n["kind"] == "entity_alias"]
    assert len(aliases) == 2
    assert all(n["label"].startswith("Stale evidence for") for n in aliases)
    focused = graph(lake, root=aliases[0]["id"])
    assert focused["nodes"][0]["status"] == "evidence_stale"
    assert focused["edges"] == []


def test_graph_binding_read_does_not_wait_for_writer(bound_lake):
    from security_lakehouse.entity_history import EntityHistoryBusy, graph_binding_snapshot
    from security_lakehouse.ledger import chain_lock

    lake, _, _ = bound_lake
    with chain_lock(lake / "entities/bindings.jsonl"), pytest.raises(EntityHistoryBusy, match="busy"):
        graph_binding_snapshot(lake, "customer", lambda: None)


def test_graph_history_verification_honors_cancellation(bound_lake):
    from security_lakehouse.entity_history import graph_binding_snapshot

    lake, _, _ = bound_lake
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("cancelled during verification")

    with pytest.raises(RuntimeError, match="cancelled"):
        graph_binding_snapshot(lake, "customer", cancel)
