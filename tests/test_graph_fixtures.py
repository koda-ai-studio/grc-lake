"""Compliance graph, crosswalk, and mockup-fixture tests."""

from __future__ import annotations

import json
import threading
import urllib.request
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from security_lakehouse.fixtures import find_fixture, list_fixtures
from security_lakehouse.graph import build_compliance_graph, build_framework_crosswalk, build_repository_graph
from security_lakehouse.server import _Handler


def _bootstrap_lake(lake: Path) -> None:
    (lake / "silver").mkdir(parents=True, exist_ok=True)
    (lake / "silver" / "normalized_events.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "event_id": f"evt-{i}",
                    "event_type": "cloud.config",
                    "asset_id": f"aws:role/svc-{i}",
                    "control_ids": ["SOC2-CC6.1"],
                    "status": "passed",
                    "severity": "info",
                }
            )
            for i in range(2)
        )
        + "\n",
        encoding="utf-8",
    )
    (lake / "gold").mkdir(parents=True, exist_ok=True)
    (lake / "gold" / "asset_risk.jsonl").write_text(
        json.dumps(
            {
                "asset_id": "aws:role/svc-0",
                "asset_owner": "platform",
                "asset_type": "iam_role",
                "environment": "prod",
                "risk_score": 12,
                "critical_open": 0,
                "high_open": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_compliance_graph_has_four_layers(tmp_path: Path) -> None:
    _bootstrap_lake(tmp_path)
    graph = build_compliance_graph(tmp_path)
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"framework", "control", "evidence_type", "asset"}.issubset(kinds)
    assert graph["counts"]["asset"] >= 1
    edge_kinds = {e["kind"] for e in graph["edges"]}
    assert {
        "framework_has_control",
        "control_requires_evidence",
        "evidence_covers_asset",
    }.issubset(edge_kinds)


def test_build_compliance_graph_keeps_record_level_bindings(tmp_path: Path) -> None:
    _bootstrap_lake(tmp_path)
    graph = build_compliance_graph(tmp_path)
    evidence_nodes = [n for n in graph["nodes"] if n["kind"] == "evidence_type"]
    assert len(evidence_nodes) == 2
    assert all(node["event_count"] == 1 for node in evidence_nodes)


def _write_repo_bronze(lake: Path) -> None:
    repo = "github:repo:acme/model-service"
    rows = [
        {
            "raw": {
                "event_id": "repo-code-graph",
                "tenant_id": "public",
                "event_time": "2026-05-24T12:00:00Z",
                "source": "github-public-repo",
                "event_type": "repository.code_graph",
                "entity": {
                    "asset_id": repo,
                    "asset_type": "repository",
                    "asset_owner": "acme",
                    "environment": "public",
                    "repo": "acme/model-service",
                },
                "severity": "info",
                "status": "observed",
                "controls": [],
                "evidence": {"evidence_id": "ev-code-graph"},
                "attributes": {
                    "nodes": [
                        {"id": repo, "kind": "repository", "label": "acme/model-service"},
                        {"id": f"{repo}:dir:.github", "kind": "directory", "label": ".github"},
                        {"id": f"{repo}:signal:ci_workflow", "kind": "evidence_signal", "label": "ci_workflow"},
                    ],
                    "edges": [
                        {"source": repo, "target": f"{repo}:dir:.github", "kind": "contains"},
                        {"source": repo, "target": f"{repo}:signal:ci_workflow", "kind": "has_signal"},
                    ],
                    "counts": {"signals": 1},
                },
            }
        },
        {
            "raw": {
                "event_id": "repo-codeowners",
                "tenant_id": "public",
                "event_time": "2026-05-24T12:00:00Z",
                "source": "github-public-repo",
                "event_type": "repository.codeowners",
                "entity": {
                    "asset_id": repo,
                    "asset_type": "repository",
                    "asset_owner": "acme",
                    "environment": "public",
                    "repo": "acme/model-service",
                },
                "severity": "info",
                "status": "observed",
                "controls": ["SOC2-CC6.1"],
                "evidence": {"evidence_id": "ev-codeowners"},
                "attributes": {"paths": [".github/CODEOWNERS"], "path_count": 1},
            }
        },
        {
            "raw": {
                "event_id": "repo-auth-gap",
                "tenant_id": "public",
                "event_time": "2026-05-24T12:00:00Z",
                "source": "github-public-repo",
                "event_type": "repository.authenticated_signal_gap",
                "entity": {
                    "asset_id": repo,
                    "asset_type": "repository",
                    "asset_owner": "acme",
                    "environment": "public",
                    "repo": "acme/model-service",
                },
                "severity": "info",
                "status": "requires_authenticated_connector",
                "controls": [],
                "evidence": {"evidence_id": "ev-auth-gap"},
                "attributes": {"requires_authenticated_connector": ["branch_protection_rules"]},
            }
        },
        {
            "raw": {
                "event_id": "repo-branch",
                "tenant_id": "customer-managed",
                "event_time": "2026-05-24T12:00:00Z",
                "source": "github-repo-governance",
                "event_type": "repository.governance.branch_protection",
                "entity": {
                    "asset_id": repo,
                    "asset_type": "repository",
                    "asset_owner": "acme",
                    "environment": "prod",
                    "repo": "acme/model-service",
                },
                "severity": "info",
                "status": "observed",
                "controls": ["SOC2-CC6.1", "ISO27001-A.5.15"],
                "evidence": {"evidence_id": "ev-branch"},
                "attributes": {
                    "governance": {
                        "available": True,
                        "required_pull_request_reviews": {"required_approving_review_count": 2},
                        "required_status_checks": {"contexts": ["quality", "web"]},
                    }
                },
            }
        },
    ]
    (lake / "bronze").mkdir(parents=True, exist_ok=True)
    (lake / "bronze" / "raw_events.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_build_compliance_graph_ids_stable_for_delimiter_free_values(tmp_path: Path) -> None:
    """Delimiter-free asset IDs stay stable; evidence IDs identify exact records."""
    (tmp_path / "silver").mkdir(parents=True, exist_ok=True)
    (tmp_path / "silver" / "normalized_events.jsonl").write_text(
        json.dumps(
            {
                "event_id": "evt-0",
                "event_type": "cloud_config",
                "asset_id": "svc-0",
                "control_ids": ["SOC2-CC6.1"],
                "status": "passed",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    graph = build_compliance_graph(tmp_path)
    ids = {n["id"] for n in graph["nodes"]}
    assert len([n for n in graph["nodes"] if n.get("event_type") == "cloud_config"]) == 1
    assert "asset:svc-0" in ids
    edge_targets = {e["target"] for e in graph["edges"] if e["kind"] == "evidence_covers_asset"}
    assert "asset:svc-0" in edge_targets


def test_build_compliance_graph_escapes_delimiter_collisions(tmp_path: Path) -> None:
    """Two event types differing only by an embedded ``:`` keep distinct node ids."""
    (tmp_path / "silver").mkdir(parents=True, exist_ok=True)
    (tmp_path / "silver" / "normalized_events.jsonl").write_text(
        "\n".join(
            json.dumps(
                {
                    "event_id": f"evt-{i}",
                    "event_type": event_type,
                    "asset_id": asset_id,
                    "control_ids": ["SOC2-CC6.1"],
                    "status": "passed",
                }
            )
            for i, (event_type, asset_id) in enumerate(
                [
                    ("a:b", "x:y"),
                    ("a", "x"),
                ]
            )
        )
        + "\n",
        encoding="utf-8",
    )
    graph = build_compliance_graph(tmp_path)
    evidence_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "evidence_type"}
    asset_ids = {n["id"] for n in graph["nodes"] if n["kind"] == "asset"}
    # Record hashes and escaped asset segments keep both identities distinct.
    assert all(identity.startswith("evidence:") for identity in evidence_ids)
    assert asset_ids == {"asset:x\\:y", "asset:x"}
    assert len(evidence_ids) == 2
    assert len(asset_ids) == 2


def test_build_repository_graph_links_repo_governance_and_controls(tmp_path: Path) -> None:
    _write_repo_bronze(tmp_path)
    graph = build_repository_graph(tmp_path)
    kinds = {node["kind"] for node in graph["nodes"]}
    assert {"repository", "directory", "evidence_signal", "signal_gap", "governance_signal", "control"}.issubset(kinds)
    edge_kinds = {edge["kind"] for edge in graph["edges"]}
    assert {"has_evidence", "evidence_maps_control", "has_governance_signal", "requires_status_check"}.issubset(
        edge_kinds
    )
    assert graph["counts"]["repository"] == 1


def test_build_repository_graph_fixture_includes_link_metadata() -> None:
    fixture_lake = Path(__file__).parent / "fixtures" / "repo-graph"
    graph = build_repository_graph(fixture_lake)
    evidence_nodes = [node for node in graph["nodes"] if node["kind"] == "evidence"]
    assert evidence_nodes
    linked = next(node for node in evidence_nodes if node.get("event_type") == "repository.codeowners")
    assert linked["control_ids"] == ["SOC2-CC6.1"]
    assert linked.get("evidence_id")
    branch = next(
        node for node in evidence_nodes if node.get("event_type") == "repository.governance.branch_protection"
    )
    assert branch.get("evidence_ref", "").startswith("https://")


def test_build_repository_graph_attaches_freshness_from_gold(tmp_path: Path) -> None:
    _write_repo_bronze(tmp_path)
    (tmp_path / "gold").mkdir(parents=True, exist_ok=True)
    (tmp_path / "gold" / "evidence_freshness.jsonl").write_text(
        json.dumps(
            {
                "event_id": "repo-codeowners",
                "evidence_id": "ev-codeowners",
                "status": "stale",
                "age_minutes": 9000,
                "source": "github-public-repo",
                "connector_id": "github-security",
                "freshness_slo_minutes": 1440,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    graph = build_repository_graph(tmp_path)
    codeowners = next(
        node for node in graph["nodes"] if node.get("kind") == "evidence" and node.get("evidence_id") == "ev-codeowners"
    )
    assert codeowners["freshness_status"] == "stale"
    assert codeowners["freshness_age_minutes"] == 9000


def test_crosswalk_returns_self_diagonal_and_shared_dimensions() -> None:
    crosswalk = build_framework_crosswalk()
    fids = crosswalk["frameworks"]
    assert len(fids) >= 2
    for row in crosswalk["matrix"]:
        for cell in row["cells"]:
            if cell["framework_id"] == row["framework_id"]:
                assert cell["is_self"] is True
            else:
                assert isinstance(cell["shared_risk_domains"], list)
                assert isinstance(cell["shared_owners"], list)


def test_list_fixtures_finds_shipped_companies() -> None:
    fixtures = list_fixtures()
    names = {f.company for f in fixtures}
    assert {"saas", "ai_lab"}.issubset(names)
    saas = find_fixture("saas")
    assert saas is not None
    assert saas.event_count > 0
    assert "SOC2-CC6.1" in saas.controls


def test_find_fixture_returns_none_for_unknown() -> None:
    assert find_fixture("does-not-exist") is None


def test_fixture_raw_events_use_only_known_controls() -> None:
    from security_lakehouse.catalog import load_control_catalog

    catalog = set(load_control_catalog().keys())
    for fixture in list_fixtures():
        for control_id in fixture.controls:
            assert control_id in catalog, f"fixture {fixture.company} references unknown control {control_id}"


# --- HTTP smoke -----------------------------------------------------------------


def _spin(lake: Path) -> ThreadingHTTPServer:
    (lake / "console.html").write_bytes(b"<!doctype html>")

    class Handler(_Handler):
        lake_dir = lake
        dashboard_path = lake / "console.html"
        web_dist = None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _get(server: ThreadingHTTPServer, path: str) -> tuple[int, dict]:
    host, port = server.server_address
    with urllib.request.urlopen(f"http://{host}:{port}{path}") as resp:  # noqa: S310
        return int(resp.status), json.loads(resp.read().decode("utf-8"))


@pytest.mark.parametrize("path", ["/api/graph", "/api/crosswalk", "/api/repo-graph"])
def test_graph_endpoints_return_200(tmp_path: Path, path: str) -> None:
    _bootstrap_lake(tmp_path)
    _write_repo_bronze(tmp_path)
    server = _spin(tmp_path)
    try:
        status, body = _get(server, path)
        assert status == HTTPStatus.OK
        assert isinstance(body, dict)
    finally:
        server.shutdown()
