"""Exercise provider-shaped fixtures through collection, evaluation and export."""

import json

import pytest
from jsonschema import Draft7Validator
from tools import qualify_connector_workflow as qualification

from test_oscal import _ASSESSMENT_RESULTS_SCHEMA


def test_three_source_workflow_retains_evidence_and_replays(tmp_path):
    out = tmp_path / "qualification"
    report = qualification.qualify(out)
    assert report["status"] == "passed", report
    assert report["qualification_level"] == "synthetic_connector_workflow_only"
    assert report["observed_counts"] == {"github-repo-governance": 7, "okta": 8, "jira": 8}
    assert all(report["checks"].values())
    assert report["checks"]["failed_collection_preserves_evidence"]
    assert report["checks"]["replay_preserves_event_ids"]
    assert report["checks"]["raw_to_silver_hashes_verified"]
    assert report["checks"]["synthetic_exports_labeled"]
    assert report["checks"]["snapshot_frozen_after_recollection"]
    assert json.loads((out / "report.json").read_text()) == report
    assert len(report["input_sha256"]) > 3
    assert isinstance(report["source_tree_dirty"], bool)
    assert "synthetic demonstration" in (out / "evidence.html").read_text().lower()
    Draft7Validator(_ASSESSMENT_RESULTS_SCHEMA).validate(json.loads((out / "assessment-results.json").read_text()))
    assert (out / "verification.json").is_file()
    with pytest.raises(FileExistsError):
        qualification.qualify(out)


def test_dropped_provider_records_cannot_report_success(tmp_path, monkeypatch):
    original = qualification.run_connector_sync

    def drop_records(lake, **kwargs):
        result = original(lake, **kwargs)
        path = lake / qualification.CONNECTOR_RAW_FILE
        rows = qualification.read_jsonl(path)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows if row["source"] != "okta"))
        return result

    monkeypatch.setattr(qualification, "run_connector_sync", drop_records)
    report = qualification.qualify(tmp_path / "qualification")
    assert report["status"] != "passed"
    assert report["checks"]["expected_source_counts"] is False


def test_provider_exception_is_retained_without_secret_text(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("provider-secret-token")

    monkeypatch.setattr(qualification, "run_connector_sync", broken)
    out = tmp_path / "qualification"
    report = qualification.qualify(out)
    assert report["status"] == "error"
    assert report["error_type"] == "RuntimeError"
    assert "provider-secret-token" not in (out / "report.json").read_text()


@pytest.mark.parametrize("key", ["GRC_LAKE_COMMERCIAL_HOSTED", "TRUSTOPS_COMMERCIAL_HOSTED", "GRC_LAKE_DATA_DIR"])
def test_hosted_or_catalog_overrides_rejected_before_writes(tmp_path, monkeypatch, key):
    monkeypatch.setenv(key, "1")
    out = tmp_path / "qualification"
    with pytest.raises(ValueError, match="locally"):
        qualification.qualify(out)
    assert not out.exists()


def test_failed_cli_returns_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification, "qualify", lambda _: {"status": "failed"})
    assert qualification.main(["--out", str(tmp_path / "qualification")]) == 1


def test_broken_provenance_cannot_report_success(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification, "verify_event", lambda *a: {"verified": False})
    report = qualification.qualify(tmp_path / "qualification")
    assert report["status"] == "failed"
    assert report["checks"]["raw_to_silver_hashes_verified"] is False


def test_cli_environment_error_exits_without_success_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GRC_LAKE_COMMERCIAL_HOSTED", "1")
    out = tmp_path / "qualification"
    with pytest.raises(SystemExit) as exc:
        qualification.main(["--out", str(out)])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unset hosted mode" in captured.err
    assert not out.exists()
