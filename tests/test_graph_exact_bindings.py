"""Investigation paths must follow observed bindings, never evidence-type fanout."""

from pathlib import Path

from security_lakehouse.graph import analyze_coverage, build_compliance_graph
from test_api_v1 import _write_jsonl


def test_same_type_does_not_join_disjoint_controls_and_assets(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "event_id": "one",
                "event_type": "identity.access_review",
                "control_ids": ["SOC2-CC6.1"],
                "asset_id": "alpha",
            },
            {
                "event_id": "two",
                "event_type": "identity.access_review",
                "control_ids": ["SOC2-CC7.2"],
                "asset_id": "beta",
            },
        ],
    )
    graph = build_compliance_graph(tmp_path)
    coverage = analyze_coverage(tmp_path, graph)
    assets = {row["asset_id"]: row for row in coverage["assets"]}
    assert [row["id"] for row in assets["asset:alpha"]["controls"]] == ["control:SOC2-CC6.1"]
    assert [row["id"] for row in assets["asset:beta"]["controls"]] == ["control:SOC2-CC7.2"]


def test_binding_ids_are_stable_deduplicated_and_keep_provenance(tmp_path: Path) -> None:
    event = {
        "event_id": "one",
        "event_type": "identity.access_review",
        "control_ids": ["SOC2-CC6.1"],
        "asset_id": "alpha",
        "source": "okta",
        "event_time": "2026-10-11T12:00:00Z",
        "raw_sha256": "abc",
    }
    path = tmp_path / "silver/normalized_events.jsonl"
    _write_jsonl(path, [event, event])
    graph = build_compliance_graph(tmp_path)
    evidence = [node for node in graph["nodes"] if node["kind"] == "evidence_type"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_id"] == "one"
    assert evidence[0]["provider"] == "okta"
    assert evidence[0]["raw_sha256"] == "abc"
    assert len({edge["id"] for edge in graph["edges"]}) == len(graph["edges"])
    _write_jsonl(path, [event])
    assert build_compliance_graph(tmp_path) == graph


def test_investigation_depth_bounds_and_source_account_identity(tmp_path: Path) -> None:
    from security_lakehouse.investigation_graph import investigation_graph

    events = [
        {
            "event_id": "one",
            "tenant_id": "account-a",
            "source": "github",
            "environment": "production",
            "event_type": "repository.vulnerability",
            "asset_id": "repo",
            "asset_type": "repository",
            "control_ids": ["SOC2-CC6.1"],
            "status": "fail",
            "severity": "high",
        },
        {
            "event_id": "two",
            "tenant_id": "account-b",
            "source": "github",
            "environment": "production",
            "event_type": "repository.vulnerability",
            "asset_id": "repo",
            "asset_type": "repository",
            "control_ids": ["SOC2-CC7.2"],
            "status": "pass",
        },
    ]
    _write_jsonl(tmp_path / "silver/normalized_events.jsonl", events)
    result = investigation_graph(tmp_path, view="environment", depth=3, limit=100)
    assert result["root"]
    assert any(n["kind"] == "finding" and n["severity"] == "high" for n in result["nodes"])
    assert len([n for n in result["nodes"] if n["kind"] == "repository"]) == 1
    assert all(n.get("source_account_id") != "account-b" for n in result["nodes"])
    shallow = investigation_graph(tmp_path, root=result["root"], depth=1, limit=100)
    assert len(shallow["nodes"]) < len(result["nodes"])
    capped = investigation_graph(tmp_path, root=result["root"], depth=3, limit=2)
    assert len(capped["nodes"]) == 2 and capped["truncated"]
    ids = {n["id"] for n in capped["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in capped["edges"])
    missing = investigation_graph(tmp_path, root="missing", depth=3)
    assert missing["nodes"] == [] and missing["root_missing"]


def test_investigation_vendor_requires_explicit_scoped_relationship(tmp_path: Path) -> None:
    from security_lakehouse.investigation_graph import investigation_graph

    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "event_id": "one",
                "tenant_id": "account-a",
                "source": "github",
                "asset_id": "repo",
                "asset_type": "repository",
                "control_ids": ["SOC2-CC6.1"],
            },
        ],
    )
    vendors = [{"id": "v1", "vendor_name": "github", "asset_refs": []}]
    graph = investigation_graph(tmp_path, root="vendor:v1", vendors=vendors)
    assert graph["edges"] == []
    vendors[0]["asset_refs"] = [{"source_account_id": "account-a", "asset_id": "repo"}]
    linked = investigation_graph(tmp_path, root="vendor:v1", depth=1, vendors=vendors)
    assert any(n["kind"] == "repository" for n in linked["nodes"])
    assert all(n["kind"] != "source" for n in linked["nodes"])


def test_investigation_uses_frozen_catalog_and_rejects_changed_version(tmp_path: Path, monkeypatch) -> None:
    import pytest

    from security_lakehouse import investigation_graph as module
    from security_lakehouse.io import write_json

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    write_json(catalog / "control_map.json", {"controls": [{"control_id": "FROZEN", "framework_id": "soc2"}]})
    write_json(
        catalog / "safeguards.json",
        {
            "safeguards": [
                {
                    "safeguard_id": "SAFE",
                    "risk_domain": "identity-access",
                    "satisfies": [{"control_id": "FROZEN", "review_status": "proposed"}],
                }
            ]
        },
    )
    monkeypatch.setattr(module, "control_catalog_view", lambda: pytest.fail("live requirements used"))
    monkeypatch.setattr(module, "effective_safeguards", lambda _: pytest.fail("live mappings used"))
    first = module.investigation_graph(tmp_path, root="control:FROZEN", depth=1)
    assert any(edge.get("review_state") == "proposed" for edge in first["edges"])
    assert all(n["id"] != "control:SOC2-CC6.1" for n in first["nodes"])
    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl", [{"event_id": "new", "asset_id": "one", "control_ids": ["FROZEN"]}]
    )
    with pytest.raises(ValueError, match="version changed"):
        module.investigation_graph(tmp_path, root="control:FROZEN", expected_version=first["version"])


def test_finding_retains_observed_failure_and_records_current_triage(tmp_path: Path) -> None:
    from security_lakehouse.investigation_graph import investigation_graph
    from security_lakehouse.tracking import append_event

    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "event_id": "one",
                "asset_id": "repo",
                "control_ids": ["SOC2-CC6.1"],
                "status": "failed",
                "severity": "high",
            }
        ],
    )
    append_event(tmp_path, violation_id="SOC2-CC6.1:one", actor="reviewer", state="resolved", assignee="owner")
    result = investigation_graph(tmp_path, view="investigation")
    finding = next(n for n in result["nodes"] if n["kind"] == "finding")
    assert finding["status"] == "resolved"
    assert finding["owner"] == "owner"
    assert finding["severity"] == "high"


def test_repository_topology_joins_only_the_recorded_account_and_asset(tmp_path: Path) -> None:
    import shutil

    from security_lakehouse.investigation_graph import investigation_graph

    fixture = Path(__file__).parent / "fixtures/repo-graph/bronze/raw_events.jsonl"
    (tmp_path / "bronze").mkdir()
    shutil.copyfile(fixture, tmp_path / "bronze/raw_events.jsonl")
    initial = investigation_graph(tmp_path, view="environment", search="acme/model-service", depth=2)
    assert any(n["kind"] == "repository" for n in initial["nodes"])
    assert any(n["kind"] in {"directory", "governance_signal", "evidence_signal"} for n in initial["nodes"])
    assert len({n["source_account_id"] for n in initial["nodes"] if n["kind"] == "repository"}) == 1


def test_legacy_compliance_graph_keeps_source_account_asset_identity(tmp_path: Path):
    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {"event_id": "one", "tenant_id": "a", "asset_id": "same", "control_ids": ["SOC2-CC6.1"]},
            {"event_id": "two", "tenant_id": "b", "asset_id": "same", "control_ids": ["SOC2-CC7.2"]},
        ],
    )
    graph = build_compliance_graph(tmp_path)
    assert len([n for n in graph["nodes"] if n["kind"] == "asset"]) == 2
    report = analyze_coverage(tmp_path, graph)
    assert all(len(row["controls"]) == 1 for row in report["assets"])


def test_investigation_starting_points_page_without_dangling_edges(tmp_path: Path):
    from security_lakehouse.investigation_graph import investigation_graph

    first = investigation_graph(tmp_path)
    second = investigation_graph(tmp_path, root_offset=50, expected_version=first["version"])
    assert len(first["roots"]) == len(second["roots"]) == 50
    assert not ({n["id"] for n in first["roots"]} & {n["id"] for n in second["roots"]})
    assert first["next_root_offset"] == 50 and second["next_root_offset"] == 100


def test_repository_context_preserves_explicit_source_account_identity(tmp_path: Path):
    from security_lakehouse.investigation_graph import investigation_graph

    _write_jsonl(
        tmp_path / "bronze/raw_events.jsonl",
        [
            {
                "raw": {
                    "event_id": "repo-observation",
                    "source_account_id": "account-a",
                    "event_type": "repository.governance.branch_protection",
                    "entity": {"asset_id": "same/repo", "asset_type": "repository"},
                    "attributes": {},
                }
            }
        ],
    )
    result = investigation_graph(tmp_path, view="environment", depth=1)
    repo = next(n for n in result["nodes"] if n["kind"] == "repository")
    assert repo["source_account_id"] == "account-a"


def test_investigation_findings_keep_the_exact_affected_control(tmp_path: Path):
    from security_lakehouse.investigation_graph import investigation_graph

    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "event_id": "branch-rule",
                "tenant_id": "account-a",
                "source": "github-repo-governance",
                "event_type": "repository.governance.branch_protection",
                "asset_id": "repo",
                "asset_type": "repository",
                "control_ids": ["SOC2-CC6.1"],
                "status": "failed",
                "severity": "high",
            }
        ],
    )
    result = investigation_graph(tmp_path, view="environment", depth=3, limit=100)
    finding = next(node for node in result["nodes"] if node["kind"] == "finding")
    evidence = next(node for node in result["nodes"] if node["kind"] == "evidence_type")
    assert finding["control_ids"] == evidence["control_ids"] == ["SOC2-CC6.1"]
    assert finding["event_type"] == evidence["event_type"] == "repository.governance.branch_protection"
