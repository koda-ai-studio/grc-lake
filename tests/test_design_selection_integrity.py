"""Design selections cannot suppress adverse evidence in the operating period."""

import copy

import pytest

from security_lakehouse.audit_workpapers import export_workpaper, verify_workpaper_export
from test_control_assurance import case, evaluate
from test_declared_control_population import build_case


@pytest.mark.parametrize("status", ["fail", "open", "observed"])
@pytest.mark.parametrize("at_start", [False, True])
def test_selected_adverse_record_remains_in_operating_population(tmp_path, status, at_start):
    plan, events = case(tmp_path)
    adverse = copy.deepcopy(events[1])
    adverse.update(event_id="selected-adverse", status=status)
    adverse["evidence"]["evidence_id"] = adverse["event_id"]
    if at_start:
        adverse["event_time"] = adverse["evidence"]["collected_at"] = plan["period_start"]
    events.append(adverse)
    plan["controls"][0]["design_event_ids"].append(adverse["event_id"])
    control = evaluate(tmp_path, plan, events)["controls"][0]
    assert control["design"]["status"] == "insufficient_evidence"
    operating = control["operating"]
    assert operating["population_event_count"] == 3
    if status == "observed":
        assert operating["status"] == "insufficient_evidence"
        assert adverse["event_id"] in operating["invalid_event_ids"]
    else:
        assert operating["status"] == "sample_fail"
        assert adverse["event_id"] in operating["deviation_event_ids"]


def test_selecting_mid_period_record_cannot_remove_a_tested_asset(tmp_path):
    plan, events = case(tmp_path)
    extra = copy.deepcopy(events[1])
    extra.update(event_id="different-asset", status="pass")
    extra["entity"]["asset_id"] = "additional-asset"
    extra["evidence"]["evidence_id"] = extra["event_id"]
    events.append(extra)
    plan["controls"][0]["design_event_ids"].append(extra["event_id"])
    operating = evaluate(tmp_path, plan, events)["controls"][0]["operating"]
    assert operating["observed_asset_count"] == 2
    assert operating["status"] == "insufficient_evidence"
    assert any(gap["asset_id"] == "additional-asset" for gap in operating["gaps"])


def test_failure_survives_workpaper_export_and_integrity_verification(tmp_path):
    plan, events = case(tmp_path)
    adverse = copy.deepcopy(events[1])
    adverse.update(event_id="selected-failure", status="fail")
    adverse["evidence"]["evidence_id"] = adverse["event_id"]
    events.append(adverse)
    plan["controls"][0]["design_event_ids"].append(adverse["event_id"])
    _, _, content = build_case(tmp_path, plan, events, declared_extra=set())
    assert content["population"]["status"] == "declared_scope_reconciled"
    assert content["assurance"]["controls"][0]["operating"]["status"] == "sample_fail"
    assert content["evidence"][adverse["event_id"]]["status"] == "failed"
    output = tmp_path / "export"
    export_workpaper(content, output)
    assert verify_workpaper_export(output)["ok"]
    assert "Observed deviation" in (output / "index.html").read_text()
