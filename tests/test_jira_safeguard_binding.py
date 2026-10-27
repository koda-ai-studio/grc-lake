"""Workflow evidence is scoped and never substitutes for remediation verification."""

import json
from pathlib import Path

import pytest

from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.safeguards import load_ccf_families, load_safeguards

FIXTURE = Path(__file__).parent / "fixtures/jira"
SID = "SG-REMEDIATIONTRACKING-001"
CONTROL = "NIST-800-53-CA-5"


def test_remediation_tracking_has_an_operational_family():
    definition = next(r for r in load_safeguards()["safeguards"] if r["safeguard_id"] == SID)
    assert definition["risk_domain"] == "remediation-tracking"
    family = load_ccf_families()[definition["risk_domain"]]
    assert family["category"] == "governance-risk"
    assert family["nist_800_53_families"] == ["CA"]
    assert "does not verify" in family["description"]


def sync(lake, fixture):
    append_config_event(lake, connector_id="jira-ticketing", state="enabled", actor="fixture-operator")
    assert run_connector_sync(lake, connector_id="jira-ticketing", fixture_dir=fixture).result == "ok"
    return read_json(lake / "gold/ccf_assessment.json"), read_jsonl(lake / CONNECTOR_RAW_FILE)


def test_jira_workflow_findings_reach_scoped_ccf_without_attesting_requirements(tmp_path):
    result, raw = sync(tmp_path / "lake", FIXTURE)
    assert {r["entity"]["asset_type"] for r in raw if r["entity"]["asset_id"].startswith("jira:issue:")} == {
        "workflow_ticket"
    }
    safeguard = next(r for r in result["safeguards"] if r["safeguard_id"] == SID)
    assert safeguard["status"] == "fail"
    definition = next(r for r in load_safeguards()["safeguards"] if r["safeguard_id"] == SID)
    assert definition["asset_types"] == ["workflow_ticket"]
    assert all(m["review_status"] == "proposed" and not m.get("maintainer_review_ref") for m in definition["satisfies"])
    for row in raw:
        if row["event_type"] == "jira.workflow.ticket":
            assert row["safeguard_ids"] == [SID]
            assert row["controls"] == [CONTROL]
        else:
            assert row.get("safeguard_ids", []) == []
    assert all(SID not in r["reviewed_safeguard_ids"] for r in result["requirements"])
    assert next(r for r in result["requirements"] if r["control_id"] == CONTROL)["status"] == "not_evaluated"


@pytest.mark.parametrize("resolution", ["Fixed", "Done", "Resolved", "Won't Fix", "Custom", None])
def test_closed_ticket_never_proves_verified_remediation(tmp_path, resolution):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    issue = json.loads((FIXTURE / "issues.json").read_text())[0]
    issue["fields"]["resolution"] = {"name": resolution} if resolution else None
    (fixture / "issues.json").write_text(json.dumps([issue]))
    (fixture / "projects.json").write_text("[]")
    result, raw = sync(tmp_path / "lake", fixture)
    ticket = next(r for r in raw if r["event_type"] == "jira.workflow.ticket")
    assert ticket["status"] in {"observed", "not_evaluated"}
    assert next(r for r in result["safeguards"] if r["safeguard_id"] == SID)["status"] == "not_evaluated"


def test_missing_jira_fields_are_unknown_instead_of_unassigned_failure(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "issues.json").write_text(json.dumps([{"key": "SEC-1", "fields": {}}]))
    (fixture / "projects.json").write_text("[]")
    _, raw = sync(tmp_path / "lake", fixture)
    ticket = next(r for r in raw if r["event_type"] == "jira.workflow.ticket")
    assert ticket["status"] == "not_evaluated"
