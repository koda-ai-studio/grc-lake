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
    unattested = [cid for cid in passing if requirements[cid]["status"] != "pass"]
    attested = [cid for cid in passing if requirements[cid]["status"] == "pass"]
    assert unattested and attested, "golden must contain attested and unattested passing posture rows"
    for cid in (unattested[0], attested[0]):
        graph = investigation_graph(golden, root="control:" + cid, depth=1)
        node = next(n for n in graph["nodes"] if n["id"] == "control:" + cid)
        requirement = requirements[cid]

        assert node["status"] == "pass"
        assert node["ccf_status"] == requirement["status"]
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


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_control_nodes_carry_the_control_test_result_and_missing_evidence(golden: Path) -> None:
    tests = {row["control_id"]: row for row in _jsonl(golden / "gold/control_tests.jsonl")}
    posture = {row["control_id"]: row for row in _jsonl(golden / "gold/control_posture.jsonl")}
    needs = [cid for cid, row in tests.items() if row["result"] == "needs_evidence"]
    assert "SOC2-CC7.2" in needs and "ISO27001-A.5.15" in needs
    assert posture["SOC2-CC7.2"]["status"] == "stale"
    for cid, row in tests.items():
        graph = investigation_graph(golden, root="control:" + cid, depth=1)
        node = next(n for n in graph["nodes"] if n["id"] == "control:" + cid)
        assert node["status"] == row["result"], cid
        assert node["posture_status"] == posture[cid]["status"], cid
        assert node["missing_evidence_types"] == row["missing_evidence_types"], cid
        assert node["stale_evidence_types"] == sorted({*row["stale_evidence_types"], *row["expired_evidence_types"]})
    cc72 = investigation_graph(golden, root="control:SOC2-CC7.2", depth=1)["nodes"]
    assert len(next(n for n in cc72 if n["id"] == "control:SOC2-CC7.2")["missing_evidence_types"]) == 6


@pytest.mark.parametrize("depth", [1, 2])
def test_failing_control_reaches_its_finding_within_the_default_depth(golden: Path, depth: int) -> None:
    root = "control:NIST-AI-RMF-GOVERN-1.2"
    deep = investigation_graph(golden, root=root, depth=3)
    expected = {n["id"]: n for n in deep["nodes"] if n["kind"] == "finding" and n["control_ids"] == [root[8:]]}
    assert expected

    graph = investigation_graph(golden, root=root, depth=depth)
    control = next(n for n in graph["nodes"] if n["id"] == root)
    assert control["finding_count"] == len(expected)
    for summary in control["findings"]:
        finding = expected[summary["id"]]
        assert summary["kind"] == "finding"
        assert summary["owner"] == finding["owner"] and summary["owner"]
        assert summary["next_action"] == finding["next_action"] and summary["next_action"]
        assert summary["severity"] == finding["severity"]
        assert summary["status"] == finding["status"]


def _failing_events(count: int, control_ids: list[str]) -> list[dict]:
    return [
        {
            "tenant_id": "a",
            "source": "okta",
            "event_id": f"fail-{index}",
            "event_type": "identity.mfa",
            "status": "failed",
            "severity": "critical" if index == count - 1 else "low",
            "asset_id": f"user-{index}",
            "asset_type": "identity_user",
            "control_ids": control_ids,
            "event_time": "2026-10-01T00:00:00Z",
        }
        for index in range(count)
    ]


def test_control_findings_are_bounded_most_severe_first_and_scoped_to_the_control(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", _failing_events(7, ["SOC2-CC6.1", "SOC2-CC6.2"]))
    graph = investigation_graph(tmp_path, root="control:SOC2-CC6.1", depth=2, limit=300)
    control = next(n for n in graph["nodes"] if n["id"] == "control:SOC2-CC6.1")
    assert control["finding_count"] == 7
    assert len(control["findings"]) == 5
    assert control["findings"][0]["severity"] == "critical"
    assert all(item["label"] == "SOC2-CC6.1 finding" for item in control["findings"])
    # The canvas keeps its shape: findings are not added to the default walk.
    assert not [n for n in graph["nodes"] if n["kind"] == "finding"]


def test_passing_control_carries_no_findings(tmp_path: Path) -> None:
    graph = investigation_graph(tmp_path, root="control:SOC2-CC6.1", depth=1)
    control = next(n for n in graph["nodes"] if n["id"] == "control:SOC2-CC6.1")
    assert "findings" not in control and "finding_count" not in control


def test_passed_evidence_without_a_freshness_record_is_never_fresh(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "tenant_id": "account-a",
                "source": "okta",
                "event_id": "no-freshness",
                "event_type": "identity.mfa",
                "status": "pass",
                "asset_id": "user-1",
                "asset_type": "identity_user",
                "control_ids": ["SOC2-CC6.1"],
                "event_time": "2026-10-01T00:00:00Z",
            }
        ],
    )
    graph = investigation_graph(tmp_path, root="control:SOC2-CC6.1", depth=1)
    evidence = next(n for n in graph["nodes"] if n["kind"] == "evidence_type")
    assert evidence["freshness_status"] == "missing"


def test_freshness_is_matched_to_the_exact_recorded_event(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from security_lakehouse.evidence_freshness import build_evidence_freshness

    base = {
        "source": "okta",
        "event_type": "identity.mfa",
        "status": "pass",
        "asset_type": "identity_user",
        "control_ids": ["SOC2-CC6.1"],
        "evidence_ref": "s3://evidence.example.com/mfa.json",
    }
    events = [
        # One event id recorded on two assets: each keeps its own freshness.
        {**base, "tenant_id": "a", "event_id": "shared", "asset_id": "old", "event_time": "2026-01-01T00:00:00Z"},
        {**base, "tenant_id": "a", "event_id": "shared", "asset_id": "new", "event_time": "2026-10-01T00:00:00Z"},
        # Account recorded only under its canonical field name.
        {**base, "source_account_id": "b", "event_id": "canon", "asset_id": "u", "event_time": "2026-01-01T00:00:00Z"},
    ]
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", events)
    freshness = build_evidence_freshness(events, now=datetime(2026, 10, 1, 0, 10, tzinfo=UTC))
    _write_jsonl(tmp_path / "gold/evidence_freshness.jsonl", freshness)
    expected = {(r["asset_id"], r["event_id"]): r["status"] for r in freshness}
    assert expected[("new", "shared")] == "fresh"
    assert expected[("old", "shared")] != "fresh"

    graph = investigation_graph(tmp_path, root="control:SOC2-CC6.1", depth=2, limit=300)
    nodes = {n["id"]: n for n in graph["nodes"]}
    covers = {
        e["source"]: nodes[e["target"]]["asset_id"] for e in graph["edges"] if e["kind"] == "evidence_covers_asset"
    }
    actual = {(covers[key], n["evidence_id"]): n["freshness_status"] for key, n in nodes.items() if key in covers}
    assert actual == expected
