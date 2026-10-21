"""Agent-Bom report import preserves observations without inventing assurance."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_lakehouse.agent_bom_import import agent_bom_events, import_agent_bom_report
from security_lakehouse.cli import main
from security_lakehouse.io import read_jsonl
from security_lakehouse.pipeline import normalize_raw_events
from security_lakehouse.validation import validate_raw_events

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)
REPORT = {
    "schema_version": "1.0",
    "document_type": "AI-BOM",
    "scan_id": "scan-example",
    "generated_at": "2026-10-21T11:00:00Z",
    "ai_bom_version": "0.0.0-test",
    "scan_run": {"outcome": "partial"},
    "warnings": ["Do not copy secret text"],
    "findings": [
        {
            "id": "finding-one",
            "finding_type": "CVE",
            "severity": "high",
            "status": "new",
            "suppressed": False,
            "asset": {"identifier": "pkg:pypi/example@1.0"},
            "title": "Do not copy free text",
            "evidence": {"token": "fixture-secret"},
            "soc2_tags": ["SOC2-CC6.1"],
        }
    ],
}


def events(report=None, **kwargs):
    return agent_bom_events(report or REPORT, tenant_id="team-a", asset_id="repo:example", now=NOW, **kwargs)


def test_replay_provenance_and_explicit_control_binding():
    first = events(controls=["SOC2-CC7.1"])
    assert first == events(controls=["SOC2-CC7.1"])
    assert validate_raw_events(first) == []
    receipt, finding = first
    assert receipt["status"] == "not_evaluated"
    assert receipt["controls"] == []
    assert receipt["attributes"]["scan_outcome"] == "partial"
    assert finding["event_time"] == REPORT["generated_at"]
    assert finding["evidence"]["collected_at"] == REPORT["generated_at"]
    assert finding["controls"] == ["SOC2-CC7.1"]
    assert finding["event_type"] == "scanner.dependency"
    assert finding["status"] == "open"
    assert len(finding["attributes"]["report_sha256"]) == 64
    assert all(row["controls"] == [] for row in events())
    text = json.dumps(first)
    assert "fixture-secret" not in text and "Do not copy" not in text
    assert "SOC2-CC6.1" not in text


def test_tenant_and_asset_scope_are_caller_bound():
    report = {**REPORT, "tenant_id": "attacker", "asset_id": "other"}
    first = events(report)
    second = agent_bom_events(report, tenant_id="team-b", asset_id="repo:other", now=NOW)
    assert first[1]["event_id"] != second[1]["event_id"]
    assert first[1]["tenant_id"] == "team-a"
    assert first[1]["entity"]["asset_id"] == "repo:example"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "resolved"},
        {"suppressed": True},
        {"severity": "unknown"},
        {"finding_type": "CIS_ERROR"},
        {"status": "unrecognized"},
    ],
)
def test_suppressed_resolved_unknown_and_errors_never_become_pass_or_open(change):
    report = copy.deepcopy(REPORT)
    report["findings"][0].update(change)
    row = events(report, controls=["SOC2-CC7.1"])[1]
    assert row["status"] == "not_evaluated"
    if change.get("finding_type") == "CIS_ERROR":
        assert row["controls"] == []


def test_empty_report_is_a_receipt_not_a_passing_control():
    rows = events({**REPORT, "findings": [], "scan_run": {"outcome": "complete"}})
    assert len(rows) == 1 and rows[0]["status"] == "not_evaluated"
    assert rows[0]["attributes"]["finding_count"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"document_type": "unknown"},
        {"findings": None},
        {"generated_at": "2026-10-21"},
        {"generated_at": "2026-10-22T00:00:00Z"},
        {"scan_id": ""},
        {"findings": [None]},
        {"findings": REPORT["findings"] * 2},
    ],
)
def test_invalid_reports_fail_closed(change):
    with pytest.raises(ValueError):
        events({**REPORT, **change})


def test_invalid_control_and_malformed_suppression_fail():
    with pytest.raises(ValueError, match="control"):
        events(controls=["MISSING-CONTROL"])
    report = copy.deepcopy(REPORT)
    report["findings"][0]["suppressed"] = "false"
    with pytest.raises(ValueError, match="suppressed"):
        events(report)


def test_file_import_validation_precedes_write_and_refuses_overwrite(tmp_path):
    source, target = tmp_path / "report.json", tmp_path / "raw.jsonl"
    source.write_text(json.dumps(REPORT))
    summary = import_agent_bom_report(
        source, target, tenant_id="team-a", asset_id="repo:example", synthetic=True, now=NOW
    )
    original = target.read_bytes()
    assert summary["finding_count"] == 1
    assert all(row["attributes"]["synthetic"] for row in read_jsonl(target))
    with pytest.raises(FileExistsError):
        import_agent_bom_report(source, target, tenant_id="team-a", asset_id="repo:example", now=NOW)
    assert target.read_bytes() == original
    source.write_text('{"schema_version":"1.0","schema_version":"2.0"}')
    with pytest.raises(ValueError):
        import_agent_bom_report(source, tmp_path / "bad.jsonl", tenant_id="team-a", asset_id="repo:example", now=NOW)
    assert not (tmp_path / "bad.jsonl").exists()


def test_cli_import_and_pipeline_keep_mapping_and_synthetic_provenance(tmp_path):
    source, target = tmp_path / "report.json", tmp_path / "raw.jsonl"
    report = {**REPORT, "generated_at": datetime.now(UTC).isoformat()}
    source.write_text(json.dumps(report))
    assert (
        main(
            [
                "ingestion",
                "import-agent-bom",
                "--report",
                str(source),
                "--out",
                str(target),
                "--tenant-id",
                "team-a",
                "--asset-id",
                "repo:example",
                "--control",
                "SOC2-CC7.1",
                "--synthetic",
            ]
        )
        == 0
    )
    lake = tmp_path / "lake"
    result = normalize_raw_events(target, lake, tenant_id="team-a")
    assert result.silver_count == 2
    rows = read_jsonl(lake / "silver/normalized_events.jsonl")
    assert {row["status"] for row in rows} == {"open", "not_evaluated"}
    assert next(row for row in rows if row["status"] == "open")["control_ids"] == ["SOC2-CC7.1"]
    assert read_jsonl(lake / "gold/control_posture.jsonl")[0]["status"] == "fail"
    from security_lakehouse.evidence_provenance import contains_synthetic_evidence

    assert contains_synthetic_evidence(lake)


@pytest.mark.parametrize("status", [None, "resolved"])
def test_nullable_and_resolved_lifecycle_stay_unassessed_through_pipeline(tmp_path, status):
    report = copy.deepcopy(REPORT)
    report["findings"][0]["status"] = status
    source, target = tmp_path / "report.json", tmp_path / "raw.jsonl"
    source.write_text(json.dumps(report))
    import_agent_bom_report(
        source, target, tenant_id="team-a", asset_id="repo:example", controls=["SOC2-CC7.1"], now=NOW
    )
    lake = tmp_path / "lake"
    normalize_raw_events(target, lake, tenant_id="team-a")
    assert {row["status"] for row in read_jsonl(lake / "silver/normalized_events.jsonl")} == {"not_evaluated"}
    assert read_jsonl(lake / "gold/control_posture.jsonl")[0]["status"] == "not_evaluated"


def test_size_limit_and_failed_publication_leave_no_partial_output(tmp_path, monkeypatch):
    from security_lakehouse import agent_bom_import as module

    source, target = tmp_path / "report.json", tmp_path / "raw.jsonl"
    source.write_text(json.dumps(REPORT))
    with monkeypatch.context() as patch:
        patch.setattr(module, "MAX_REPORT_BYTES", 16)
        with pytest.raises(ValueError, match="import limit"):
            import_agent_bom_report(source, target, tenant_id="team-a", asset_id="repo:example", now=NOW)

    def failed_fsync(_):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(module.os, "fsync", failed_fsync)
    with pytest.raises(OSError, match="disk failure"):
        import_agent_bom_report(source, target, tenant_id="team-a", asset_id="repo:example", now=NOW)
    assert not target.exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json"]


def test_symlink_and_published_generation_are_not_writable(tmp_path):
    source, target = tmp_path / "report.json", tmp_path / "raw.jsonl"
    source.write_text(json.dumps(REPORT))
    target.symlink_to(tmp_path / "absent")
    with pytest.raises(FileExistsError):
        import_agent_bom_report(source, target, tenant_id="team-a", asset_id="repo:example", now=NOW)
    assert target.is_symlink() and not (tmp_path / "absent").exists()
    generation = tmp_path / "generations/generation-one"
    generation.mkdir(parents=True)
    (generation / "generation.json").write_text("{}")
    with pytest.raises(ValueError, match="immutable"):
        import_agent_bom_report(
            source, generation / "bronze/raw.jsonl", tenant_id="team-a", asset_id="repo:example", now=NOW
        )


@pytest.mark.parametrize(
    "change",
    [
        {"scan_run": {"outcome": []}},
        {"scan_run": {"schema_version": "2"}},
        {"findings": [{**REPORT["findings"][0], "schema_version": "2"}]},
    ],
)
def test_unsupported_nested_contracts_are_validation_errors(change):
    with pytest.raises(ValueError):
        events({**REPORT, **change})


def test_actual_producer_fixture_keeps_nullable_status_and_cve_identity(tmp_path):
    source = Path(__file__).parent / "fixtures/agent_bom/report.json"
    target = tmp_path / "raw.jsonl"
    summary = import_agent_bom_report(
        source, target, tenant_id="team-a", asset_id="repo:example", controls=["SOC2-CC7.1"], synthetic=True, now=NOW
    )
    rows = read_jsonl(target)
    assert summary["finding_count"] == 2
    assert summary["bound_vulnerability_count"] == 1
    assert [row["status"] for row in rows] == ["not_evaluated", "open", "not_evaluated"]
    assert rows[1]["attributes"]["cve_id"] == "CVE-2099-0001"
    assert rows[2]["attributes"]["upstream_status"] == "unknown"
    assert all(row["attributes"]["synthetic"] for row in rows)
    assert target.stat().st_mode & 0o777 == 0o600
