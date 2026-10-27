"""Human-readable CLI output preserves the canonical assessment's semantics."""

from __future__ import annotations

import json
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

from security_lakehouse import assessment
from security_lakehouse.cli import main


def test_version_uses_installed_distribution_metadata(capsys) -> None:
    expected = version("grc-lake")
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert expected == project["project"]["version"]
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out == f"grc-lake {expected}\n"


def test_summary_reports_the_golden_assessment_counts(tmp_path, capsys) -> None:
    lake = str(tmp_path / "lake")
    assert main(["fixtures", "load", "--company", "golden", "--out", lake, "--rebase-times"]) == 0
    capsys.readouterr()
    assert main(["assessment", "status", "--lake", lake]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(["assessment", "status", "--lake", lake, "--format", "summary"]) == 0
    output = capsys.readouterr().out
    posture = payload["posture"]
    assert f"Posture    {posture['score']} / 100  {posture['state']}" in output
    assert (
        f"Controls   {posture['control_count']} total, {posture['not_evaluated_control_count']} not evaluated, {posture['stale_control_count']} stale"
        in output
    )
    assert (
        f"Tests      {posture['failed_control_test_count']} failing, {posture['warning_control_test_count']} warning"
        in output
    )
    assert (
        f"Violations {posture['open_violation_count']} open ({posture['critical_violation_count']} critical, {posture['high_violation_count']} high)"
        in output
    )
    assert (
        f"Evidence   {payload['evidence_freshness']['count']} records, {posture['stale_evidence_count']} stale/expired/missing"
        in output
    )
    assert len(output.split("\n\n", 1)[0].splitlines()) == 6


@pytest.mark.parametrize("format_args", [[], ["--format", "json"]])
def test_json_preserves_existing_serialization(monkeypatch, capsys, format_args, tmp_path) -> None:
    payload = {"z": ["évidence"], "posture": {"score": 3.14, "state": "critical"}, "a": None}
    monkeypatch.setattr(assessment, "build_current_posture", lambda *args, **kwargs: payload)
    assert main(["assessment", "status", "--lake", str(tmp_path), *format_args]) == 0
    assert capsys.readouterr().out == json.dumps(payload, indent=2, sort_keys=True) + "\n"


def test_summary_uses_aggregate_counts_once_not_truncated_details(monkeypatch, capsys, tmp_path) -> None:
    calls = []

    def build(lake, *, freshness_days):
        calls.append((lake, freshness_days))
        return {
            "posture": {
                "score": 42.5,
                "state": "attention_required",
                "control_count": 50,
                "not_evaluated_control_count": 7,
                "stale_control_count": 9,
                "failed_control_test_count": 12,
                "warning_control_test_count": 3,
                "open_violation_count": 1000,
                "critical_violation_count": 200,
                "high_violation_count": 300,
                "stale_evidence_count": 800,
            },
            "violations": [],
            "evidence_freshness": {"count": 2000, "stale_evidence": []},
        }

    monkeypatch.setattr(assessment, "build_current_posture", build)
    assert main(["assessment", "status", "--lake", str(tmp_path), "--freshness-days", "3", "--format", "summary"]) == 0
    assert calls == [(str(tmp_path), 3)]
    output = capsys.readouterr().out
    assert "50 total, 7 not evaluated, 9 stale" in output
    assert "1000 open (200 critical, 300 high)" in output
    assert "2000 records, 800 stale/expired/missing" in output


def test_empty_lake_summary_stays_not_evaluated(tmp_path, capsys) -> None:
    assert main(["assessment", "status", "--lake", str(tmp_path), "--format", "summary"]) == 0
    output = capsys.readouterr().out
    assert "not_evaluated" in output
    assert "Controls   0 total, 0 not evaluated, 0 stale" in output
    assert "Evidence   0 records, 0 stale/expired/missing" in output


@pytest.mark.parametrize("output_format", ["json", "summary"])
def test_failed_assessment_does_not_print_a_success_summary(monkeypatch, capsys, output_format, tmp_path) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("assessment unavailable")

    monkeypatch.setattr(assessment, "build_current_posture", fail)
    assert main(["assessment", "status", "--lake", str(tmp_path), "--format", output_format]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "error: assessment unavailable\n"


def test_summary_states_attested_framework_results_next_to_control_tests(tmp_path, capsys) -> None:
    lake = tmp_path / "lake"
    assert main(["fixtures", "load", "--company", "golden", "--out", str(lake), "--rebase-times"]) == 0
    capsys.readouterr()
    assert main(["assessment", "status", "--lake", str(lake), "--format", "summary"]) == 0
    output = capsys.readouterr().out
    ccf = json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))
    counts = {status: sum(r["status"] == status for r in ccf["requirements"]) for status in ("pass", "fail")}
    not_assessed = len(ccf["requirements"]) - counts["pass"] - counts["fail"]
    assert (
        f"Framework  {counts['pass']} attested, {counts['fail']} failing, {not_assessed} not assessed "
        "(CCF requirements through reviewed mappings)"
    ) in output


def test_summary_explains_passing_access_test_without_framework_attestation(tmp_path, capsys) -> None:
    from security_lakehouse.io import read_json, read_jsonl, write_jsonl
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import complete_events

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, complete_events())
    run_pipeline(raw, lake, tenant_id="audit")
    before = {path.name: path.read_bytes() for path in (lake / "gold").iterdir() if path.is_file()}
    assert read_jsonl(lake / "gold/control_tests.jsonl")[0]["result"] == "pass"
    ccf = read_json(lake / "gold/ccf_assessment.json")
    access = next(row for row in ccf["requirements"] if row["control_id"] == "SOC2-CC6.1")
    assert access["status"] == "not_evaluated"

    assert main(["assessment", "status", "--lake", str(lake), "--format", "summary"]) == 0
    output = capsys.readouterr().out
    for explanation in (
        "Technical tests",
        "explicitly bound",
        "proposed mappings cannot attest",
        "Missing = required evidence absent",
        "stale = outside its freshness window",
        "partial = collection incomplete",
        "not evaluated = no supported verdict",
        "observed = no verdict asserted",
        "Maintainer mapping review is not independent workpaper review",
        "Hash verification checks content consistency, not reviewer identity",
        "SOC2-CC6.1",
        "AUDITOR_WALKTHROUGH.md#first-run-access-control-path",
    ):
        assert explanation in output
    assert before == {path.name: path.read_bytes() for path in (lake / "gold").iterdir() if path.is_file()}
