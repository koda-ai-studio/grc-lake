"""GPU workload inventory and network exposure evidence from managed Kubernetes.

The fixture is a synthetic GPU cluster shaped like a CoreWeave CKS or Nebius
Managed Kubernetes tenant: ``kubectl get -o json`` List documents for core/v1
Services, apps/v1 and batch/v1 workloads, and KServe ``serving.kserve.io/v1beta1``
InferenceServices. GPUs are requested through the NVIDIA device plugin resource
``nvidia.com/gpu`` and InfiniBand through ``rdma/ib``, as both providers document.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import connectors_kubernetes
from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.connector_errors import collection_gaps
from security_lakehouse.connectors_kubernetes import (
    KubernetesClient,
    KubernetesFixtureClient,
    collect_kubernetes_evidence,
)
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures" / "kubernetes-neocloud"
CLUSTER = "gpu-east"
COLLECTED = datetime(2026, 10, 24, tzinfo=UTC)
NETWORK_SG = "SG-NETWORK-001"


def _rows(fixture: Path = FIXTURE) -> list[dict[str, Any]]:
    return collect_kubernetes_evidence(KubernetesFixtureClient(fixture, cluster_name=CLUSTER), collected_at=COLLECTED)


def _by(rows: list[dict[str, Any]], event_type: str) -> dict[str, dict[str, Any]]:
    prefix = f"kubernetes:{CLUSTER}:"
    return {r["entity"]["asset_id"].removeprefix(prefix): r for r in rows if r["event_type"] == event_type}


def _safeguards() -> dict[str, dict[str, Any]]:
    payload = json.loads((Path(__file__).parents[1] / "controls" / "safeguards.json").read_text(encoding="utf-8"))
    return {row["safeguard_id"]: row for row in payload["safeguards"]}


def test_gpu_cluster_events_are_valid_and_tagged_with_catalog_controls() -> None:
    rows = _rows()

    assert validate_raw_events(rows) == []
    # 3 namespaces + 4 workloads x 3 baseline signals + 3 accelerator workloads
    # + 5 externally typed Services (the ClusterIP one is skipped) + 2 InferenceServices.
    assert len(rows) == 25
    catalog = load_control_catalog()
    assert all(control in catalog for row in rows for control in row["controls"])
    assert collection_gaps(rows) == []


def test_accelerator_inventory_records_gpus_infiniband_and_runtime_without_a_verdict() -> None:
    inventory = _by(_rows(), "kubernetes.workload.accelerator_inventory")

    assert set(inventory) == {
        "Deployment:inference/vllm-llama",
        "Deployment:inference/nim-embed",
        "Job:training/llama-finetune",
    }
    for row in inventory.values():
        # Inventory is an observation: it never passes or fails a control.
        assert (row["status"], row["severity"]) == ("observed", "info")
        assert row["entity"]["asset_type"] == "kubernetes_workload"
        assert "safeguard_ids" not in row
    vllm = inventory["Deployment:inference/vllm-llama"]["attributes"]
    assert (vllm["gpu_count"], vllm["infiniband"], vllm["serving_runtime"]) == (1, False, "vllm")
    nim = inventory["Deployment:inference/nim-embed"]["attributes"]
    assert (nim["serving_runtime"], nim["nim_image"]) == ("nim", True)
    training = inventory["Job:training/llama-finetune"]["attributes"]
    assert (training["gpu_count"], training["infiniband"]) == (8, True)
    assert training["accelerator_resources"] == ["nvidia.com/gpu", "rdma/ib"]
    # InfiniBand job scope: the namespace's NetworkPolicy count travels with the job.
    assert training["namespace_network_policy_count"] == 1
    assert vllm["namespace_network_policy_count"] == 0


def test_workloads_without_accelerators_emit_no_inventory_event() -> None:
    assert "Deployment:default/web" not in _by(_rows(), "kubernetes.workload.accelerator_inventory")


@pytest.mark.parametrize(
    ("ref", "status", "severity", "reason"),
    [
        ("Service:inference/vllm-public", "open", "high", "public_load_balancer_unrestricted"),
        ("Service:inference/nim-restricted", "pass", "info", "public_load_balancer_source_restricted"),
        ("Service:default/web-internal", "pass", "info", "internal_load_balancer"),
        ("Service:default/web-nodeport", "not_evaluated", "info", "node_port_reachability_not_visible"),
        ("Service:default/web-pending", "not_evaluated", "info", "load_balancer_address_unknown"),
    ],
)
def test_service_exposure_is_judged_from_the_assigned_address_and_source_ranges(
    ref: str, status: str, severity: str, reason: str
) -> None:
    row = _by(_rows(), "kubernetes.service.network_exposure")[ref]

    assert (row["status"], row["severity"], row["attributes"]["finding_reason"]) == (status, severity, reason)
    assert row["entity"]["asset_type"] == "network"
    assert row["safeguard_ids"] == [NETWORK_SG]


def test_clusterip_services_are_not_exposure_evidence() -> None:
    assert "Service:default/web" not in _by(_rows(), "kubernetes.service.network_exposure")


def test_public_load_balancer_severity_rises_only_when_it_fronts_gpu_workloads(tmp_path: Path) -> None:
    for name in ("namespaces.json", "workloads.json"):
        shutil.copy(FIXTURE / name, tmp_path / name)
    services = json.loads((FIXTURE / "services.json").read_text())
    web_public = {**services["items"][0], "metadata": {"name": "web-public", "namespace": "default"}}
    web_public["spec"] = {**web_public["spec"], "selector": {"app": "web"}}
    (tmp_path / "services.json").write_text(json.dumps({"items": [services["items"][0], web_public]}))

    exposure = _by(_rows(tmp_path), "kubernetes.service.network_exposure")
    assert exposure["Service:inference/vllm-public"]["attributes"]["selects_accelerator_workload"] is True
    assert exposure["Service:inference/vllm-public"]["severity"] == "high"
    assert exposure["Service:default/web-public"]["attributes"]["selects_accelerator_workload"] is False
    assert (exposure["Service:default/web-public"]["status"], exposure["Service:default/web-public"]["severity"]) == (
        "open",
        "medium",
    )


def test_world_open_source_range_is_unrestricted() -> None:
    service = {
        "metadata": {"name": "lb", "namespace": "default"},
        "spec": {"type": "LoadBalancer", "loadBalancerSourceRanges": ["10.0.0.0/8", "0.0.0.0/0"]},
        "status": {"loadBalancer": {"ingress": [{"ip": "11.22.33.46"}]}},
    }
    rows = collect_kubernetes_evidence(_StaticClient(services=[service]), collected_at=COLLECTED)  # type: ignore[arg-type]
    assert rows[0]["attributes"]["finding_reason"] == "public_load_balancer_unrestricted"


def test_exposure_attributes_keep_no_addresses_selectors_or_labels() -> None:
    for row in _by(_rows(), "kubernetes.service.network_exposure").values():
        text = json.dumps(row["attributes"])
        assert "11.22.33" not in text and "10.16.0.12" not in text and "10.20.0.0" not in text
        assert "selector" not in row["attributes"] and "labels" not in row["attributes"]


@pytest.mark.parametrize(
    ("ref", "status", "reason"),
    [
        ("InferenceService:inference/reranker", "pass", "cluster_local"),
        ("InferenceService:inference/llama-chat", "not_evaluated", "external_url_authentication_not_visible"),
    ],
)
def test_inference_service_exposure_never_passes_an_externally_routed_endpoint(
    ref: str, status: str, reason: str
) -> None:
    row = _by(_rows(), "kubernetes.inference.network_exposure")[ref]

    assert (row["status"], row["attributes"]["finding_reason"]) == (status, reason)
    assert row["entity"]["asset_type"] == "service"
    assert row["safeguard_ids"] == [NETWORK_SG]
    # The model storage location is never carried into evidence.
    assert "storageUri" not in json.dumps(row) and "hf://" not in json.dumps(row)


def test_inference_service_attributes_describe_the_serving_stack() -> None:
    rows = _by(_rows(), "kubernetes.inference.network_exposure")
    chat = rows["InferenceService:inference/llama-chat"]["attributes"]
    assert (chat["model_format"], chat["gpu_count"], chat["url_scope"]) == ("huggingface", 2, "external")
    reranker = rows["InferenceService:inference/reranker"]["attributes"]
    assert (reranker["serving_runtime"], reranker["gpu_count"], reranker["url_scope"]) == ("triton", 1, "cluster_local")


def test_inference_service_without_url_is_not_evaluated() -> None:
    item = {"metadata": {"name": "pending", "namespace": "ml"}, "spec": {"predictor": {}}, "status": {}}
    rows = collect_kubernetes_evidence(_StaticClient(inference_services=[item]), collected_at=COLLECTED)  # type: ignore[arg-type]
    assert (rows[0]["status"], rows[0]["attributes"]["finding_reason"]) == ("not_evaluated", "no_url_reported")


def test_bound_events_apply_to_the_safeguard_and_carry_only_its_crosswalk_tags() -> None:
    safeguards = _safeguards()
    bound = [row for row in _rows() if row.get("safeguard_ids")]
    assert bound
    for row in bound:
        for safeguard_id in row["safeguard_ids"]:
            definition = safeguards[safeguard_id]
            assert row["entity"]["asset_type"] in definition["asset_types"]
            crosswalk = {member["control_id"] for member in definition["satisfies"]}
            assert set(row["controls"]) <= crosswalk, set(row["controls"]) - crosswalk


def test_one_asset_keeps_one_asset_type_across_signals() -> None:
    types: dict[str, set[str]] = {}
    for row in _rows():
        types.setdefault(row["entity"]["asset_id"], set()).add(row["entity"]["asset_type"])
    assert all(len(found) == 1 for found in types.values())


def test_existing_fixture_without_services_or_kserve_is_unchanged() -> None:
    rows = collect_kubernetes_evidence(
        KubernetesFixtureClient(Path(__file__).parent / "fixtures" / "kubernetes", cluster_name="prod-eks"),
        allowed_registries=["123456789012.dkr.ecr.us-east-1.amazonaws.com", "registry.k8s.io"],
        collected_at=COLLECTED,
    )
    assert len(rows) == 26
    assert not [r for r in rows if r.get("safeguard_ids")]


class _StaticClient:
    def __init__(self, **lists: list[dict[str, Any]]) -> None:
        self.cluster_name = CLUSTER
        self._lists = lists

    def __getattr__(self, name: str) -> Any:
        return lambda: self._lists.get(name, [])


# --- Live client: optional reads degrade to coverage gaps ---------------------------


class _ApiException(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status
        self.headers: dict[str, str] = {}


class _FakeApi:
    def __init__(self, pages: dict[str, list[Any]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, method: str) -> Any:
        def call(**kwargs: Any) -> Any:
            self.calls.append((method, kwargs))
            queue = self.pages.get(method)
            if not queue:
                return {"metadata": {}, "items": []}
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        return call


def _live(pages: dict[str, list[Any]]) -> tuple[KubernetesClient, _FakeApi]:
    api = _FakeApi(pages)
    apis = {name: api for name in ("core", "rbac", "networking", "apps", "batch", "custom")}
    return KubernetesClient(CLUSTER, apis=apis), api


def test_live_client_lists_kserve_inference_services_with_paging() -> None:
    items = json.loads((FIXTURE / "inference_services.json").read_text())["items"]
    client, api = _live(
        {
            "list_cluster_custom_object": [
                {"metadata": {"continue": "tok-1"}, "items": items[:1]},
                {"metadata": {}, "items": items[1:]},
            ]
        }
    )

    assert [i["metadata"]["name"] for i in client.inference_services()] == ["llama-chat", "reranker"]
    expected = {"group": "serving.kserve.io", "version": "v1beta1", "plural": "inferenceservices"}
    assert api.calls == [
        ("list_cluster_custom_object", {**expected, "limit": connectors_kubernetes.PAGE_LIMIT}),
        ("list_cluster_custom_object", {**expected, "limit": connectors_kubernetes.PAGE_LIMIT, "_continue": "tok-1"}),
    ]


def test_cluster_without_kserve_has_no_inference_services() -> None:
    client, _ = _live({"list_cluster_custom_object": [_ApiException(404)]})
    assert client.inference_services() == []


def test_denied_optional_reads_become_coverage_gaps_and_keep_baseline_evidence() -> None:
    client, api = _live(
        {
            "list_service_for_all_namespaces": [_ApiException(403)],
            "list_cluster_custom_object": [_ApiException(403)],
            "list_namespace": [{"metadata": {}, "items": [{"metadata": {"name": "default"}}]}],
        }
    )

    rows = collect_kubernetes_evidence(client, collected_at=COLLECTED)

    assert validate_raw_events(rows) == []
    gaps = collection_gaps(rows)
    assert {(gap["collection"], gap["reason"]) for gap in gaps} == {
        ("services", "permission_denied"),
        ("inference_services", "permission_denied"),
    }
    assert {gap["permission"] for gap in gaps} == {"list services", "list inferenceservices.serving.kserve.io"}
    gap_rows = [r for r in rows if r["event_type"] == "kubernetes.collection.gap"]
    assert all(r["controls"] == [] and "safeguard_ids" not in r for r in gap_rows)
    assert any(r["event_type"] == "kubernetes.namespace.network_policy" for r in rows)
    assert all(method.startswith("list_") for method, _ in api.calls)


def test_other_optional_read_failures_still_fail_the_sync() -> None:
    client, _ = _live({"list_service_for_all_namespaces": [_ApiException(500)] * 6})
    with pytest.raises(_ApiException):
        collect_kubernetes_evidence(client, collected_at=COLLECTED)
