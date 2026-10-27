"""GPU cloud evidence reaches the CCF assessment through sync and the pipeline.

A synthetic GPU Kubernetes cluster (CoreWeave/Nebius shaped) and a synthetic
Lambda Cloud account are synced into one lake from fixtures, then the pipeline
builds ``gold/ccf_assessment.json``. Safeguard verdicts come only from explicit
bindings; framework requirements follow the reviewed crosswalk, and proposed
mappings are never attested.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_json
from security_lakehouse.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
CLUSTER = "gpu-east"
ACCOUNT = "5c8d0f6a2b3e4d1f9a7b6c5d4e3f2a10"
NETWORK, ACCESS = "SG-NETWORK-001", "SG-IDENTITY-001"


def _k8s(ref: str) -> str:
    return f"kubernetes:{CLUSTER}:{ref}"


def _lambda(ref: str) -> str:
    return f"lambda_cloud:{ACCOUNT}:{ref}"


@pytest.fixture(scope="module")
def assessment(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("neocloud")
    lake = root / "lake"
    append_config_event(
        lake, connector_id="kubernetes-cluster", state="enabled", actor="t", credentials={"cluster_name": CLUSTER}
    )
    append_config_event(
        lake, connector_id="lambda-cloud", state="enabled", actor="t", credentials={"credential_ref": "LAMBDA_API_KEY"}
    )
    k8s = run_connector_sync(
        lake, connector_id="kubernetes-cluster", fixture_dir=FIXTURES / "kubernetes-neocloud", materialize=False
    )
    gpu = run_connector_sync(
        lake, connector_id="lambda-cloud", fixture_dir=FIXTURES / "lambda-cloud", materialize=False
    )
    assert (k8s.evidence_count, gpu.evidence_count) == (25, 14)
    out = root / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="neocloud-test")
    return read_json(out / "gold" / "ccf_assessment.json")


def _asset_results(assessment: dict[str, Any], safeguard_id: str) -> dict[str, str]:
    return {
        row["asset_id"]: row["status"] for row in assessment["asset_results"] if row["safeguard_id"] == safeguard_id
    }


def test_no_asset_is_ambiguous_across_signals(assessment: dict[str, Any]) -> None:
    assert assessment["ambiguous_asset_count"] == 0


def test_network_safeguard_verdicts_per_exposed_asset(assessment: dict[str, Any]) -> None:
    instance = "instance:0a1b2c3d4e5f40718293a4b5c6d7e8f"
    assert _asset_results(assessment, NETWORK) == {
        _k8s("Service:inference/vllm-public"): "fail",
        _k8s("Service:inference/nim-restricted"): "pass",
        _k8s("Service:default/web-internal"): "pass",
        _k8s("Service:default/web-nodeport"): "not_evaluated",
        _k8s("Service:default/web-pending"): "not_evaluated",
        _k8s("InferenceService:inference/reranker"): "pass",
        _k8s("InferenceService:inference/llama-chat"): "not_evaluated",
        _lambda(f"{instance}1"): "pass",
        _lambda(f"{instance}2"): "fail",
        _lambda(f"{instance}3"): "fail",
        _lambda(f"{instance}4"): "not_evaluated",  # us-south-1: firewall rules do not apply
        _lambda(f"{instance}5"): "not_evaluated",  # terminated: observation only
    }
    network = {row["safeguard_id"]: row for row in assessment["safeguards"]}[NETWORK]
    assert (network["status"], network["invalid_binding_count"]) == ("fail", 0)


def test_access_safeguard_fails_on_weak_keys_and_never_passes_on_observations(assessment: dict[str, Any]) -> None:
    results = _asset_results(assessment, ACCESS)
    instance = "instance:0a1b2c3d4e5f40718293a4b5c6d7e8f"
    assert results[_lambda(f"{instance}2")] == "fail"  # 1024-bit RSA
    assert results[_lambda(f"{instance}3")] == "fail"  # DSA
    # Strong keys are observations: logical access is not established by key strength.
    assert results[_lambda(f"{instance}1")] == "not_evaluated"
    assert results[_lambda("identity:7d2e1f0a3b4c5d6e7f8a9b0c1d2e3f01")] == "fail"  # key without expiry
    assert results[_lambda("identity:7d2e1f0a3b4c5d6e7f8a9b0c1d2e3f02")] == "fail"  # unused key
    assert results[_lambda("identity:7d2e1f0a3b4c5d6e7f8a9b0c1d2e3f03")] == "not_evaluated"  # expired only
    assert "pass" not in results.values()


def test_inventory_rows_bind_nothing(assessment: dict[str, Any]) -> None:
    bound = {row["asset_id"] for row in assessment["asset_results"]}
    assert _k8s("Deployment:inference/vllm-llama") not in bound
    assert _k8s("Job:training/llama-finetune") not in bound


def test_framework_requirements_follow_the_reviewed_crosswalk(assessment: dict[str, Any]) -> None:
    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    for control_id in ("FEDRAMP-SC-7", "NIST-800-53-SC-7", "CMMC-3.13.6"):
        assert NETWORK not in requirements[control_id]["reviewed_safeguard_ids"]
        assert requirements[control_id]["status"] == "not_evaluated"
    assert requirements["NIST-800-53-IA-5"]["status"] == "not_evaluated"
    # A proposed mapping is never attested, even when the safeguard has evidence.
    iso = requirements["ISO27001-A.8.22"]
    assert NETWORK not in iso["reviewed_safeguard_ids"]
    assert iso["pending_mapping_count"] >= 1
    assert iso["status"] != "pass"
