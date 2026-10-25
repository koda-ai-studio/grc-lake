"""Unified golden fixture tests."""

from __future__ import annotations

import json
from pathlib import Path

from security_lakehouse import api_v1
from security_lakehouse.assessment import build_current_posture
from security_lakehouse.fixtures import find_fixture
from security_lakehouse.golden_fixture import (
    GOLDEN_COMPANY,
    build_golden_events,
    golden_control_ids,
    golden_fixture_summary,
)
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.validation import validate_raw_events


def test_golden_fixture_summary_lists_37_controls() -> None:
    summary = golden_fixture_summary()
    assert summary["company"] == GOLDEN_COMPANY
    assert summary["control_count"] == 37
    assert summary["soc2_control_count"] == 33
    assert summary["nist_ai_control_count"] == 4
    assert len(golden_control_ids()) == 37


def test_golden_events_validate() -> None:
    rows = build_golden_events()
    assert len(rows) == 37
    assert validate_raw_events(rows) == []
    assert {row["controls"][0] for row in rows} == set(golden_control_ids())


def test_golden_fixture_ships_and_populates_dashboard(tmp_path: Path) -> None:
    fixture = find_fixture(GOLDEN_COMPANY)
    assert fixture is not None
    assert fixture.event_count >= len(golden_control_ids())
    expected_controls = set(golden_control_ids()) | {
        "ISO27001-A.5.15",
        "ISO27001-A.5.13",
        "ISO27001-A.5.28",
        "ISO27001-A.8.17",
    }
    assert set(fixture.controls) == expected_controls

    run_pipeline(fixture.raw_path, tmp_path)
    posture_rows = [
        json.loads(line)
        for line in (tmp_path / "gold" / "control_posture.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(posture_rows) == len(expected_controls)
    assert {row["control_id"] for row in posture_rows} == expected_controls

    posture = build_current_posture(tmp_path)
    assert posture["posture"]["control_count"] == len(expected_controls)
    assert posture["posture"]["framework_count"] == 3
    frameworks = {row["framework"] for row in posture["frameworks"]}
    assert frameworks == {"SOC 2", "NIST AI RMF", "ISO 27001:2022"}

    # Supplemental records cover the required types across the dataset, but
    # belong to distinct assets. They must not complete another asset's test.
    # Public observations also remain excluded from verdict support.
    tests = api_v1.handle_get("/api/v1/control-tests", {"limit": ["500"]}, tmp_path)[1]["data"]
    incomplete = {row["control_id"]: row for row in tests if row["missing_evidence_types"]}
    assert set(incomplete) == {
        "SOC2-CC6.1",
        "SOC2-CC7.2",
        "NIST-AI-RMF-MAP-1.5",
        "NIST-AI-RMF-MEASURE-2.7",
    }
    for row in incomplete.values():
        assert row["missing_evidence_types"] == row["required_evidence_types"]
        assert row["confidence_inputs"]["freshness"] == 0
        assert all(kind in row["next_action"] for kind in row["missing_evidence_types"])
    assert {cid: row["result"] for cid, row in incomplete.items()} == {
        "SOC2-CC6.1": "fail",
        "SOC2-CC7.2": "needs_evidence",
        "NIST-AI-RMF-MAP-1.5": "fail",
        "NIST-AI-RMF-MEASURE-2.7": "needs_evidence",
    }
    cc61 = next(row for row in tests if row["control_id"] == "SOC2-CC6.1")
    linked = next(row for row in posture_rows if row["control_id"] == "SOC2-CC6.1")
    assert cc61["evidence_count"] == 4
    assert linked["evidence_count"] == 6  # Two public observations retained.
    assert cc61["next_action"].startswith("request ")


def test_golden_asset_types_match_their_event_types() -> None:
    from security_lakehouse.golden_fixture import build_golden_events

    ai_asset_types = {"model", "agent", "ai_model", "ai_agent"}
    ai_event_types = {"model.lineage", "runtime.inference"}
    for row in build_golden_events():
        is_ai_asset = row["entity"]["asset_type"] in ai_asset_types
        assert is_ai_asset == (row["event_type"] in ai_event_types), row["event_id"]


def test_committed_golden_fixture_asset_types_match_event_types() -> None:
    from security_lakehouse.golden_fixture import golden_fixture_path

    ai_asset_types = {"model", "agent", "ai_model", "ai_agent"}
    ai_event_types = {"model.lineage", "runtime.inference", "ai.model_inventory", "model.inventory"}
    for line in golden_fixture_path().read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        is_ai_asset = row["entity"]["asset_type"] in ai_asset_types
        assert is_ai_asset == (row["event_type"] in ai_event_types), row["event_id"]
        if is_ai_asset:
            assert not row["entity"]["asset_id"].startswith("golden:asset:soc2-"), row["event_id"]


def test_golden_sources_match_their_event_types() -> None:
    """A model-drift alert comes from the SIEM, never from AWS Config."""
    from security_lakehouse.golden_fixture import golden_fixture_path

    expected = {
        "cloud.config": {"aws_config"},
        "iam.access_review": {"okta"},
        "monitoring.audit": {"audit_log"},
        "monitoring.detection": {"siem"},
        "scm.branch_protection": {"github"},
        "scanner.dependency": {"github"},
        "model.lineage": {"model_registry"},
        "runtime.inference": {"runtime_gateway"},
    }
    for line in golden_fixture_path().read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["event_type"] in expected:
            assert row["source"] in expected[row["event_type"]], (row["event_id"], row["event_type"], row["source"])


def test_committed_golden_fixture_is_exactly_the_generator_output() -> None:
    """The demo loads the committed JSONL, so it must not drift from the generator."""
    from security_lakehouse.golden_fixture import golden_fixture_path, render_golden_fixture

    assert golden_fixture_path().read_text(encoding="utf-8") == render_golden_fixture()


def test_golden_assets_have_readable_names_and_keep_stable_ids() -> None:
    from security_lakehouse.golden_fixture import build_golden_fixture_rows

    rows = build_golden_fixture_rows()
    names_by_id: dict[str, set[str]] = {}
    for row in rows:
        entity = row["entity"]
        name = entity.get("asset_name")
        assert isinstance(name, str) and name.strip(), row["event_id"]
        assert ":" not in name, row["event_id"]
        names_by_id.setdefault(entity["asset_id"], set()).add(name)
    # One name per asset, and no two assets share a name.
    assert all(len(names) == 1 for names in names_by_id.values())
    assert len({next(iter(names)) for names in names_by_id.values()}) == len(names_by_id)
    ids = set(names_by_id)
    assert {"golden:asset:soc2-cc1.1", "golden:model:risk-scorer", "golden:agent:triage-agent"} <= ids
    assert "github:repo:acme/model-service" in ids


def test_golden_asset_names_reach_evidence_findings_and_graph(tmp_path: Path) -> None:
    from security_lakehouse.graph import build_compliance_graph

    fixture = find_fixture(GOLDEN_COMPANY)
    assert fixture is not None
    run_pipeline(fixture.raw_path, tmp_path)

    silver = [
        json.loads(line)
        for line in (tmp_path / "silver" / "normalized_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    # Names are display data on gold assets; normalized events keep the v1 shape.
    assert not [row for row in silver if "asset_name" in row]

    status, body = api_v1.handle_get("/api/v1/evidence", {"limit": ["500"]}, tmp_path)
    assert status == 200
    first = next(row for row in body["data"] if row["event_id"] == "golden-001")
    assert first["asset_id"] == "golden:asset:soc2-cc1.1"
    assert first["asset_name"] == "Customer records bucket"

    assets = {row["asset_id"]: row for row in api_v1.handle_get("/api/v1/assets", {}, tmp_path)[1]["data"]}
    assert assets["golden:model:risk-scorer"]["asset_name"] == "Risk scorer model"

    violations = build_current_posture(tmp_path)["violations"]
    assert violations and all(v.get("asset_name") for v in violations)

    graph = build_compliance_graph(tmp_path)
    asset_nodes = [node for node in graph["nodes"] if node["kind"] == "asset"]
    assert asset_nodes
    assert not [node for node in asset_nodes if str(node["label"]).startswith("golden:")]
    customer = next(node for node in asset_nodes if node.get("asset_id") == "golden:asset:soc2-cc1.1")
    assert customer["label"] == "Customer records bucket"


def test_asset_names_come_from_raw_entities_and_only_label_known_assets() -> None:
    from security_lakehouse.asset_names import asset_names_from_raw, with_asset_names

    raw = [
        {"entity": {"asset_id": "arn:aws:s3:::logs", "asset_name": "  Logs bucket "}},
        {"entity": {"asset_id": "arn:aws:s3:::logs", "asset_name": "Renamed later"}},
        {"entity": {"id": "i-123"}},
        {"entity": "not-an-object"},
    ]
    names = asset_names_from_raw(raw)
    assert names == {"arn:aws:s3:::logs": "Logs bucket"}
    rows = with_asset_names([{"asset_id": "arn:aws:s3:::logs"}, {"asset_id": "i-123"}], names)
    assert rows == [{"asset_id": "arn:aws:s3:::logs", "asset_name": "Logs bucket"}, {"asset_id": "i-123"}]


def test_golden_ai_inventory_carries_asset_names(tmp_path: Path) -> None:
    from security_lakehouse.ai_governance import list_ai_inventory

    fixture = find_fixture(GOLDEN_COMPANY)
    assert fixture is not None
    run_pipeline(fixture.raw_path, tmp_path)
    items = list_ai_inventory(lake=tmp_path, limit=100)
    assert items and all(item.get("asset_name") for item in items)
    by_id = {item["asset_id"]: item for item in items}
    assert by_id["golden:model:risk-scorer"]["asset_name"] == "Risk scorer model"


def test_golden_required_types_are_present_across_each_control_dataset() -> None:
    """Dataset type coverage does not establish completeness for each asset."""
    from security_lakehouse.catalog import load_control_catalog
    from security_lakehouse.evidence_types import expand_evidence_types
    from security_lakehouse.golden_fixture import build_golden_fixture_rows
    from security_lakehouse.programs import with_program_requirements

    catalog = with_program_requirements(load_control_catalog())
    rows = build_golden_fixture_rows()
    missing = {}
    for cid in golden_control_ids():
        observed = {t for r in rows if cid in r["controls"] for t in expand_evidence_types(r["event_type"])}
        absent = set(catalog[cid]["required_evidence_types"]) - observed
        if absent:
            missing[cid] = sorted(absent)
    assert not missing, missing


def test_access_review_alias_preserves_raw_type_without_inventing_other_evidence() -> None:
    from security_lakehouse.evidence_types import expand_evidence_types

    assert expand_evidence_types("iam.access_review") == ["iam.access_review", "identity.access_review"]
    assert expand_evidence_types("runtime.inference") == ["runtime.inference"]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_golden_demo_reaches_attested_passes_only_through_reviewed_bindings(tmp_path: Path) -> None:
    """The demo shows the payoff: a few framework passes, each one honestly earned."""
    from security_lakehouse.ccf_evaluation import binding_applies
    from security_lakehouse.cli import main
    from security_lakehouse.safeguards import ATTESTABLE_STATES, effective_review_state

    lake = tmp_path / "lake"
    assert main(["fixtures", "load", "--company", "golden", "--out", str(lake), "--rebase-times"]) == 0
    assessment = json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))
    catalog = json.loads((lake / "catalog" / "safeguards.json").read_text(encoding="utf-8"))
    safeguards = {row["safeguard_id"]: row for row in catalog["safeguards"]}
    silver = _jsonl(lake / "silver" / "normalized_events.jsonl")
    freshness = {row["event_id"]: row["status"] for row in _jsonl(lake / "gold" / "evidence_freshness.jsonl")}
    asset_types: dict[str, set[str]] = {}
    for row in silver:
        asset_types.setdefault(row["asset_id"], set()).add(row["asset_type"])
    safeguard_results = {row["safeguard_id"]: row for row in assessment["safeguards"]}

    passes = [row for row in assessment["requirements"] if row["status"] == "pass"]
    assert 2 <= len(passes) <= 5, [row["control_id"] for row in passes]
    for requirement in passes:
        control_id = requirement["control_id"]
        assert requirement["pending_mapping_count"] == 0
        assert requirement["reviewed_safeguard_ids"]
        for safeguard_id in requirement["reviewed_safeguard_ids"]:
            definition = safeguards[safeguard_id]
            member = next(m for m in definition["satisfies"] if m["control_id"] == control_id)
            assert effective_review_state(member) in ATTESTABLE_STATES
            result = safeguard_results[safeguard_id]
            assert result["status"] == "pass"
            assert result["assessed_asset_count"] == result["applicable_asset_count"] >= 1
            bound = [row for row in assessment["asset_results"] if row["safeguard_id"] == safeguard_id]
            assert bound and all(row["status"] == "pass" for row in bound)
            eligible = set(definition["asset_types"])
            crosswalk = {m["control_id"] for m in definition["satisfies"]}
            required = set(definition.get("required_evidence_types") or [])
            for row in bound:
                assert binding_applies(asset_types[row["asset_id"]], eligible), row
                events = [event for event in silver if event["event_id"] in row["event_ids"]]
                assert events and all(freshness[event["event_id"]] == "fresh" for event in events)
                assert all(set(event["control_ids"]) <= crosswalk for event in events)
                assert required <= {kind for event in events for kind in event["evidence_types"]}

    # The payoff reaches the console's control tests, and the demo keeps its
    # failures, gaps and unattested passes next to it.
    tests = api_v1.handle_get("/api/v1/control-tests", {"limit": ["500"]}, lake)[1]["data"]
    attested = {row["control_id"] for row in tests if row["result"] == "pass" and row["ccf_status"] == "pass"}
    assert attested == {row["control_id"] for row in passes}
    assert [row for row in tests if row["result"] == "fail"]
    assert [row for row in tests if row["result"] == "pass" and row["ccf_status"] != "pass"]
    assert {"not_evaluated", "unmapped"} <= {row["status"] for row in assessment["requirements"]}
