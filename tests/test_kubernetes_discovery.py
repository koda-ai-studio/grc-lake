"""Discovery records configured node capacity without asserting hardware or compliance."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_lakehouse.connector_errors import collection_gaps
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.connectors_kubernetes import KubernetesFixtureClient, collect_kubernetes_evidence
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.validation import validate_raw_events
from test_kubernetes_gpu_evidence import _ApiException, _live

FIXTURE = Path(__file__).parent / "fixtures/kubernetes-discovery"
NOW = datetime(2026, 10, 30, tzinfo=UTC)


def test_nodes_and_tpu_workloads_are_discovered_without_inventing_verdicts():
    rows = collect_kubernetes_evidence(
        KubernetesFixtureClient(FIXTURE, cluster_name="discovery"), collected_at=NOW, tenant_id="account-a"
    )
    nodes = {row["attributes"]["node_name"]: row for row in rows if row["event_type"] == "kubernetes.node.inventory"}
    assert set(nodes) == {"gpu-worker", "tpu-worker", "cpu-worker"}
    gpu, tpu, cpu = [nodes[name]["attributes"] for name in ("gpu-worker", "tpu-worker", "cpu-worker")]
    assert gpu["capacity"] == {"cpu": "32", "memory": "128Gi", "nvidia.com/gpu": "8"}
    assert gpu["allocatable"]["nvidia.com/gpu"] == "7"
    assert gpu["node_info"]["containerRuntimeVersion"] == "containerd://2.1.0"
    assert gpu["ready"] == "True"
    assert tpu["capacity"]["google.com/tpu"] == "4"
    assert tpu["unschedulable"] is True
    assert cpu["provider_id"] is None and cpu["ready"] == "Unknown"
    assert all(n["attributes"]["hardware_type"] == "unknown" for n in nodes.values())
    assert all(n["status"] == "observed" and not n.get("safeguard_ids") for n in nodes.values())
    assert all(n["entity"]["asset_type"] == "kubernetes_node" and n["tenant_id"] == "account-a" for n in nodes.values())
    [workload] = [row for row in rows if row["event_type"] == "kubernetes.workload.accelerator_inventory"]
    assert workload["attributes"]["tpu_count"] == 4 and workload["attributes"]["gpu_count"] == 0
    assert workload["attributes"]["accelerator_resources"] == ["google.com/tpu"]
    assert validate_raw_events(rows) == []
    assert "do-not-collect" not in str(rows)
    assert collection_gaps(rows) == []


def test_node_api_paginates_and_retries_without_changing_the_cluster_endpoint(monkeypatch):
    from security_lakehouse.ingestion import backoff

    waits = []
    monkeypatch.setattr(backoff.time, "sleep", waits.append)
    limited = _ApiException(429)
    limited.headers = {"Retry-After": "7"}
    items = read_json(FIXTURE / "nodes.json")["items"]
    client, api = _live(
        {
            "list_node": [
                limited,
                {"items": items[:1], "metadata": {"continue": "next"}},
                {"items": items[1:]},
            ]
        }
    )
    assert client.nodes() == items
    assert [call[0] for call in api.calls] == ["list_node"] * 3
    assert api.calls[-1][1]["_continue"] == "next"
    assert waits == [7]


@pytest.mark.parametrize("status", [401, 403])
def test_denied_nodes_are_a_visible_gap_without_losing_other_evidence(status):
    client, _ = _live(
        {"list_node": [_ApiException(status)], "list_namespace": [{"items": [{"metadata": {"name": "default"}}]}]}
    )
    rows = collect_kubernetes_evidence(client, collected_at=NOW)
    assert any(row["event_type"] == "kubernetes.namespace.network_policy" for row in rows)
    assert [(gap["collection"], gap["reason"]) for gap in collection_gaps(rows)] == [("nodes", "permission_denied")]
    assert not any(row["event_type"] == "kubernetes.node.inventory" for row in rows)


@pytest.mark.parametrize("page", [{}, {"items": None}, {"items": ["invalid"]}])
def test_malformed_node_pages_cannot_report_empty_success(page):
    client, _ = _live({"list_node": [page]})
    rows = collect_kubernetes_evidence(client, collected_at=NOW)
    assert [(gap["collection"], gap["reason"]) for gap in collection_gaps(rows)] == [("nodes", "malformed_response")]


def test_discovery_reaches_the_lake_and_ccf_without_turning_inventory_into_a_pass(tmp_path):
    lake, out = tmp_path / "lake", tmp_path / "out"
    append_config_event(
        lake,
        connector_id="kubernetes-cluster",
        state="enabled",
        actor="test",
        credentials={"cluster_name": "discovery"},
    )
    result = run_connector_sync(lake, connector_id="kubernetes-cluster", fixture_dir=FIXTURE, materialize=False)
    assert result.result == "ok" and result.evidence_count == 7
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="discovery-org")
    assessment = read_json(out / "gold/ccf_assessment.json")
    assert assessment["asset_count"] == 4
    assert assessment["population_completeness"] == "not_established"
    assert not assessment["asset_results"]
    assert not any(row["status"] == "pass" for row in assessment["safeguards"])
    assert len(read_jsonl(lake / CONNECTOR_RAW_FILE)) == 7
    assert latest_run(lake, "kubernetes-cluster")["result"] == "ok"


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata", {}),
        ("spec", []),
        ("status", {"conditions": [{"type": "Ready", "status": {"private": "do-not-collect"}}]}),
        ("spec", {"providerID": {"private": "do-not-collect"}}),
    ],
)
def test_malformed_node_does_not_hide_valid_nodes_or_become_success(field, value):
    import copy

    items = read_json(FIXTURE / "nodes.json")["items"]
    bad = copy.deepcopy(items[0])
    bad[field] = value
    client, _ = _live({"list_node": [{"items": [items[1], bad]}]})
    rows = collect_kubernetes_evidence(client, collected_at=NOW)
    assert len([r for r in rows if r["event_type"] == "kubernetes.node.inventory"]) == 1
    assert collection_gaps(rows)[0]["reason"] == "malformed_response"
    assert "do-not-collect" not in str(rows)


@pytest.mark.parametrize("quantity", ["invalid", "-1", "0.5"])
def test_unknown_accelerator_quantities_are_collection_gaps_not_zero(quantity):
    workload = read_json(FIXTURE / "workloads.json")["items"][0]
    workload["spec"]["template"]["spec"]["containers"][0]["resources"] = {"limits": {"google.com/tpu": quantity}}
    client, _ = _live({"list_job_for_all_namespaces": [{"items": [workload]}]})
    rows = collect_kubernetes_evidence(client, collected_at=NOW)
    assert any(r["entity"]["asset_type"] == "kubernetes_workload" for r in rows)
    assert [(g["collection"], g["reason"]) for g in collection_gaps(rows)] == [
        ("accelerator_inventory", "malformed_response")
    ]


def test_denied_discovery_marks_the_connector_run_partial(tmp_path, monkeypatch):
    client, _ = _live({"list_node": [_ApiException(403)]})
    monkeypatch.setattr(KubernetesFixtureClient, "nodes", lambda _: client.nodes())
    append_config_event(
        tmp_path,
        connector_id="kubernetes-cluster",
        state="enabled",
        actor="test",
        credentials={"cluster_name": "discovery"},
    )
    result = run_connector_sync(tmp_path, connector_id="kubernetes-cluster", fixture_dir=FIXTURE)
    assert result.result == "ok"
    assert result.run["metadata"]["partial"] is True
    assert result.coverage_gaps[0]["collection"] == "nodes"
    assert latest_run(tmp_path, "kubernetes-cluster")["metadata"]["partial"] is True
    assert read_json(tmp_path / "gold/ccf_assessment.json")["population_completeness"] == "not_established"


def test_node_pagination_cannot_truncate_discovery_silently():
    client, _ = _live({"list_node": [{"items": [], "metadata": {"continue": "same"}}] * 2})
    rows = collect_kubernetes_evidence(client, collected_at=NOW)
    assert [(g["collection"], g["reason"]) for g in collection_gaps(rows)] == [("nodes", "pagination_incomplete")]


def test_discovered_nodes_remain_searchable_in_distinct_source_accounts(tmp_path):
    from security_lakehouse.investigation_graph import investigation_graph
    from security_lakehouse.io import write_jsonl

    client = KubernetesFixtureClient(FIXTURE, cluster_name="discovery")
    rows = [
        {**r, "connector_id": "kubernetes-cluster"}
        for account in ("account-a", "account-b")
        for r in collect_kubernetes_evidence(client, tenant_id=account, collected_at=NOW)
    ]
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, rows)
    run_pipeline(raw, lake, tenant_id="platform")
    assert read_json(lake / "gold/ccf_assessment.json")["asset_count"] == 8
    graph = investigation_graph(lake, view="environment", search="gpu-worker", depth=1)
    assert len(graph["roots"]) == 2
    assert len({r["id"] for r in graph["roots"]}) == 2
    assert all(r["kind"] == "asset" for r in graph["roots"])
