"""The investigation graph must state recorded evidence exactly, across processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from security_lakehouse.cli import main
from security_lakehouse.investigation_graph import investigation_graph
from test_api_v1 import _write_jsonl


@pytest.fixture(scope="module")
def golden(tmp_path_factory: pytest.TempPathFactory) -> Path:
    lake = tmp_path_factory.mktemp("golden")
    assert main(["fixtures", "load", "--company", "golden", "--out", str(lake), "--rebase-times"]) == 0
    return lake


def _version_in_process(lake: Path, seed: str) -> str:
    script = (
        "import sys; from pathlib import Path; "
        "from security_lakehouse.investigation_graph import investigation_graph; "
        "print(investigation_graph(Path(sys.argv[1]))['version'])"
    )
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run(
        [sys.executable, "-c", script, str(lake)], env=env, capture_output=True, text=True, check=True, timeout=120
    )
    return result.stdout.strip()


def test_graph_version_is_identical_across_hash_seeds(golden: Path) -> None:
    versions = {_version_in_process(golden, seed) for seed in ("1", "2", "3", "4")}
    assert len(versions) == 1


def test_control_nodes_carry_ccf_result_and_posture_reasons(golden: Path) -> None:
    posture = {
        row["control_id"]: row
        for row in map(json.loads, (golden / "gold/control_posture.jsonl").read_text(encoding="utf-8").splitlines())
    }
    assessment = json.loads((golden / "gold/ccf_assessment.json").read_text(encoding="utf-8"))
    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    passing = sorted(cid for cid, row in posture.items() if row["status"] == "pass" and cid in requirements)
    assert passing, "golden must contain a passing posture row to compare against the CCF result"
    cid = passing[0]
    graph = investigation_graph(golden, root="control:" + cid, depth=1)
    node = next(n for n in graph["nodes"] if n["id"] == "control:" + cid)
    requirement = requirements[cid]

    assert node["status"] == "pass"
    assert node["ccf_status"] == requirement["status"]
    assert node["ccf_status"] != "pass"
    assert node["reviewed_safeguard_count"] == len(requirement["reviewed_safeguard_ids"])
    assert node["proposed_safeguard_count"] == requirement["pending_mapping_count"]
    assert node["rule_reasons"] == posture[cid]["rule_reasons"]
    assert node["evaluation_rule"] == posture[cid]["evaluation_rule"]
    assert node["open_event_count"] == posture[cid]["open_event_count"]


def test_control_without_assessment_or_posture_is_not_evaluated(tmp_path: Path) -> None:
    graph = investigation_graph(tmp_path, root="control:SOC2-CC6.1", depth=1)
    node = next(n for n in graph["nodes"] if n["id"] == "control:SOC2-CC6.1")
    assert node["status"] == "not_evaluated"
    assert node["ccf_status"] == "not_evaluated"
    assert node["reviewed_safeguard_count"] == 0
    assert node["proposed_safeguard_count"] == 0
    assert node["rule_reasons"] == []
    assert node["evaluation_rule"] is None
    assert node["open_event_count"] is None


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_control_walk_shows_the_source_that_produced_its_evidence(golden: Path, depth: int) -> None:
    graph = investigation_graph(golden, root="control:SOC2-CC6.1", depth=depth)
    kinds = {n["id"]: n["kind"] for n in graph["nodes"]}
    evidence = {key for key, kind in kinds.items() if kind == "evidence_type"}
    produces = [e for e in graph["edges"] if e["kind"] == "produces"]
    assert evidence
    assert produces
    assert all(kinds[e["source"]] == "source" and e["target"] in evidence for e in produces)
    # A source is context for the reached evidence, not a hop toward its other records.
    reached = {e["target"] for e in graph["edges"] if e["kind"] == "control_requires_evidence"}
    assert evidence <= reached


def _safeguard_lake(lake: Path) -> None:
    base = {
        "tenant_id": "account-a",
        "source": "okta",
        "event_type": "identity.mfa",
        "status": "pass",
        "event_time": "2026-10-01T00:00:00Z",
        "safeguard_ids": ["SG-IDENTITY-001"],
    }
    _write_jsonl(
        lake / "silver/normalized_events.jsonl",
        [
            {**base, "event_id": "valid", "asset_id": "user-1", "asset_type": "identity_user"},
            {**base, "event_id": "wrong-type", "asset_id": "repo-1", "asset_type": "repository"},
            {**base, "event_id": "mixed-a", "asset_id": "host-1", "asset_type": "identity_user"},
            {**base, "event_id": "mixed-b", "asset_id": "host-1", "asset_type": "host"},
        ],
    )


def test_safeguard_evidence_with_an_inapplicable_asset_type_is_marked_invalid(tmp_path: Path) -> None:
    _safeguard_lake(tmp_path)
    graph = investigation_graph(tmp_path, root="safeguard:SG-IDENTITY-001", depth=1, limit=300)
    evidence = {n["id"]: n["evidence_id"] for n in graph["nodes"] if n["kind"] == "evidence_type"}
    edges = {
        evidence[e["target"]]: e
        for e in graph["edges"]
        if e["kind"] == "has_evidence" and e["source"] == "safeguard:SG-IDENTITY-001"
    }
    assert set(edges) == {"valid", "wrong-type", "mixed-a", "mixed-b"}
    assert "binding" not in edges["valid"]
    for event_id in ("wrong-type", "mixed-a", "mixed-b"):
        assert edges[event_id]["binding"] == "invalid_asset_type"
        assert edges[event_id]["binding_reason"] == "The asset type does not establish safeguard applicability."
