"""The qualification runner retains inspectable evidence and detects false passes."""

import json

import pytest
from tools import qualify_control_workflow as qualification


def test_complete_matrix_exports_reviewable_evidence_without_claiming_live_qualification(tmp_path):
    output = tmp_path / "qualification"
    report = qualification.qualify(output)
    assert report["status"] == "passed", report
    assert report["qualification_level"] == "synthetic_workflow_only"
    assert len(report["cases"]) == len(qualification.SAFEGUARDS) * len(qualification.SCENARIOS)
    assert all(case["status"] == "passed" for case in report["cases"])
    assert json.loads((output / "report.json").read_text()) == report
    for case in report["cases"]:
        assert all(case["checks"].values())
        assert case["observed"] == case["expected"]
        bundle = output / case["directory"] / "workpaper"
        content = json.loads((bundle / "workpaper.json").read_text())
        assert content["synthetic_fixture"] is True
        assert content["assurance"]["review_status"] == "pending_human_review"
        assert content["plan"]["tenant_id"] == "qualification"
        assert content["assurance"]["controls"][0]["requirement_mappings"]
        assert (bundle / "index.html").is_file()
        assert case["input_sha256"] and case["content_sha256"]
    with pytest.raises(FileExistsError):
        qualification.qualify(output)


def test_false_pass_is_retained_as_a_failed_case(tmp_path, monkeypatch):
    original = qualification.build_workpaper

    def false_pass(*args, **kwargs):
        content = original(*args, **kwargs)
        content["assurance"]["controls"][0]["operating"]["status"] = "sample_pass"
        return content

    monkeypatch.setattr(qualification, "build_workpaper", false_pass)
    result = qualification.run_case(tmp_path / "case", qualification.SAFEGUARDS[0], "observed_failure")
    assert result["status"] == "failed"
    assert result["observed"]["operating"] == "sample_pass"
    assert result["expected"]["operating"] == "sample_fail"
    assert result["checks"]["expected_outcomes"] is False
    assert (tmp_path / "case/workpaper/workpaper.json").is_file()


def test_execution_error_is_a_retained_failure_without_exception_text(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("provider-secret-must-not-be-recorded")

    monkeypatch.setattr(qualification, "build_workpaper", broken)
    result = qualification.run_case(tmp_path / "case", qualification.SAFEGUARDS[0], "complete_samples")
    assert result["status"] == "error"
    assert result["error_type"] == "RuntimeError"
    assert "provider-secret" not in json.dumps(result)
    assert json.loads((tmp_path / "case/result.json").read_text()) == result


def test_cli_returns_nonzero_for_failed_qualification(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification, "qualify", lambda out: {"status": "failed", "cases": []})
    assert qualification.main(["--out", str(tmp_path / "report")]) == 1


def test_cli_rejects_hosted_environment_without_reporting_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GRC_LAKE_COMMERCIAL_HOSTED", "1")
    output = tmp_path / "report"
    with pytest.raises(SystemExit) as exc:
        qualification.main(["--out", str(output)])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unset hosted mode and data-directory overrides" in captured.err
    assert not output.exists()


@pytest.mark.parametrize("name", ["GRC_LAKE_COMMERCIAL_HOSTED", "TRUSTOPS_COMMERCIAL_HOSTED", "GRC_LAKE_DATA_DIR"])
def test_operator_environment_cannot_redirect_qualification(tmp_path, monkeypatch, name):
    monkeypatch.setenv(name, "1")
    with pytest.raises(ValueError, match="locally"):
        qualification.qualify(tmp_path / "report")
    assert not (tmp_path / "report").exists()
