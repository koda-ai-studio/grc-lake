"""Control-test posture is never presented as a framework (CCF) attestation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from security_lakehouse import api_v1
from security_lakehouse.cli import main


@pytest.fixture(scope="module")
def golden_lake(tmp_path_factory: pytest.TempPathFactory) -> Path:
    lake = tmp_path_factory.mktemp("golden") / "lake"
    assert main(["fixtures", "load", "--company", "golden", "--out", str(lake), "--rebase-times"]) == 0
    return lake


def _requirements(lake: Path) -> dict[str, dict]:
    payload = json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))
    return {row["control_id"]: row for row in payload["requirements"]}


def test_controls_carry_ccf_result_next_to_control_test_status(golden_lake: Path) -> None:
    status, body = api_v1.handle_get("/api/v1/controls", {"limit": ["500"]}, golden_lake)
    assert status == 200
    controls = {row["control_id"]: row for row in body["data"]}
    requirements = _requirements(golden_lake)

    cc68 = controls["SOC2-CC6.8"]
    assert cc68["status"] == "pass"
    assert cc68["ccf_status"] == "not_evaluated"
    assert cc68["reviewed_safeguard_count"] == 0
    assert cc68["proposed_safeguard_count"] == requirements["SOC2-CC6.8"]["pending_mapping_count"] > 0
    assert controls["SOC2-CC3.3"]["reviewed_safeguard_count"] == 0

    for control_id, row in controls.items():
        requirement = requirements[control_id]
        assert row["ccf_status"] == requirement["status"]
        assert row["reviewed_safeguard_count"] == len(requirement["reviewed_safeguard_ids"])
        assert row["proposed_safeguard_count"] == requirement["pending_mapping_count"]
    assert not [row for row in controls.values() if row["status"] == "pass" and row["ccf_status"] == "pass"]


def test_control_tests_carry_ccf_result_on_streamed_and_sorted_pages(golden_lake: Path) -> None:
    for params in ({"limit": ["500"]}, {"limit": ["500"], "sort": ["control_id"]}):
        status, body = api_v1.handle_get("/api/v1/control-tests", params, golden_lake)
        assert status == 200
        tests = {row["control_id"]: row for row in body["data"]}
        assert tests["SOC2-CC6.8"]["result"] == "pass"
        assert tests["SOC2-CC6.8"]["ccf_status"] == "not_evaluated"
        assert tests["SOC2-CC6.8"]["reviewed_safeguard_count"] == 0
        assert tests["SOC2-CC6.8"]["proposed_safeguard_count"] > 0


def test_framework_detail_separates_attested_passes_from_control_test_passes(golden_lake: Path) -> None:
    status, body = api_v1.handle_get("/api/v1/frameworks/soc2/detail", {"limit": ["100"]}, golden_lake)
    assert status == 200
    summary = body["data"]["summary"]
    controls = body["data"]["controls"]
    posture_passes = sum(row["posture"]["status"] == "pass" for row in controls)

    assert posture_passes > 0
    assert summary["passing_control_count"] == posture_passes
    assert summary["attested_pass_count"] == 0
    cc68 = next(row for row in controls if row["control_id"] == "SOC2-CC6.8")
    assert cc68["posture"]["status"] == "pass"
    assert cc68["ccf_status"] == "not_evaluated"
    assert cc68["reviewed_safeguard_count"] == 0
    assert cc68["proposed_safeguard_count"] > 0


def test_missing_assessment_reads_as_not_evaluated(golden_lake: Path, tmp_path: Path) -> None:
    from security_lakehouse.ccf_requirement_results import ccf_result_fields, load_requirement_results

    assert load_requirement_results(tmp_path) == {}
    assert ccf_result_fields({}, "SOC2-CC6.8") == {
        "ccf_status": "not_evaluated",
        "reviewed_safeguard_count": 0,
        "proposed_safeguard_count": 0,
    }
