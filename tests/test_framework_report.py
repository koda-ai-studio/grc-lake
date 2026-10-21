"""Portable framework reports keep catalog, mapping and evidence claims distinct."""

import hashlib
import json
import zipfile
from copy import deepcopy

import pytest

from security_lakehouse.framework_report import build_framework_report, export_framework_report, summarize_coverage
from security_lakehouse.generations import generation_identity
from security_lakehouse.io import write_jsonl
from security_lakehouse.pipeline import run_pipeline
from test_assurance_truth import event
from test_ccf_operational_assessment import assessment, normalized


def test_counts_include_unobserved_requirements_without_inflating_assessment():
    data = assessment([normalized()])
    passed = data["requirements"][0]
    data["requirements"] += [
        {
            **passed,
            "control_id": "PENDING",
            "status": "not_evaluated",
            "reviewed_safeguard_ids": [],
            "pending_mapping_count": 2,
        },
        {**passed, "control_id": "STALE", "status": "stale"},
        {**passed, "control_id": "UNMAPPED", "status": "unmapped", "reviewed_safeguard_ids": []},
    ]
    controls = {r["control_id"]: {"framework_id": "fixture", "title": r["control_id"]} for r in data["requirements"]}
    before = deepcopy(data)
    result = summarize_coverage(data, controls)
    summary = result["frameworks"][0]
    assert summary["catalogued"] == 4
    assert summary["mapped"] == 3
    assert summary["with_reviewed_mapping"] == 2
    assert summary["assessed"] == 1
    assert summary["assessed_pct"] == 25.0
    assert summary["status_counts"] == {"pass": 1, "fail": 0, "stale": 1, "not_evaluated": 1, "unmapped": 1}
    assert len(result["requirements"]) == 4
    assert data == before
    with pytest.raises(ValueError, match="framework"):
        summarize_coverage(data, controls, framework_ids=["missing"])
    with pytest.raises(ValueError, match="catalog"):
        summarize_coverage(data, {**controls, "LOST": {"framework_id": "fixture"}})
    data["requirements"].append(passed)
    with pytest.raises(ValueError, match="duplicate"):
        summarize_coverage(data, controls)


@pytest.fixture
def lake(tmp_path):
    raw = tmp_path / "events.jsonl"
    write_jsonl(raw, [{**event(), "safeguard_ids": ["SG-IDENTITY-001"], "attributes": {"synthetic": True}}])
    target = tmp_path / "lake"
    run_pipeline(raw, target, tenant_id="audit")
    return target


def test_frozen_report_contains_catalog_denominators_and_synthetic_provenance(lake):
    result = build_framework_report(
        lake, tenant_id="audit", framework_ids=["soc2", "iso-27001-2022", "nist-csf-2.0", "nist-800-53-rev5"]
    )
    assert result["generation"] == generation_identity(lake)
    assert result["scope"] == "observed_assets"
    assert result["population_completeness"] == "not_established"
    assert result["contains_synthetic_evidence"] is True
    assert len(result["frameworks"]) == 4
    assert all(r["catalogued"] > r["assessed"] for r in result["frameworks"])
    assert len(result["requirements"]) == sum(r["catalogued"] for r in result["frameworks"])
    assert "raw_path" not in json.dumps(result)


def test_export_escapes_html_and_hashes_files_without_overwriting(lake, tmp_path):
    report = build_framework_report(lake, tenant_id="audit", framework_ids=["soc2"])
    report["requirements"][0]["title"] = '<script>alert("unsafe")</script>'
    report["review_log_verified_at_assessment"] = False
    out = tmp_path / "coverage.zip"
    export_framework_report(report, out)
    with zipfile.ZipFile(out) as bundle:
        assert set(bundle.namelist()) == {"index.html", "coverage.json", "manifest.json"}
        html = bundle.read("index.html").decode()
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert "Synthetic evidence" in html
        assert "Review ledger was unverified" in html
        manifest = json.loads(bundle.read("manifest.json"))
        for name, digest in manifest["files"].items():
            assert hashlib.sha256(bundle.read(name)).hexdigest() == digest
    assert out.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        export_framework_report(report, out)


def test_mismatched_tenant_generation_or_corruption_fails_closed(lake):
    with pytest.raises(ValueError, match="tenant"):
        build_framework_report(lake, tenant_id="other")
    with pytest.raises(ValueError, match="generation"):
        build_framework_report(lake, tenant_id="audit", expected_generation="wrong")
    (lake / "mart/security_lakehouse.sqlite").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_framework_report(lake, tenant_id="audit")


def test_missing_generation_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="generation"):
        build_framework_report(tmp_path, tenant_id="audit")


def test_generation_is_pinned_even_when_new_assessment_is_published(lake, tmp_path, monkeypatch):
    from security_lakehouse import framework_report

    before = generation_identity(lake)
    original = framework_report.read_summary
    raw = tmp_path / "next.jsonl"
    write_jsonl(raw, [{**event("fail"), "safeguard_ids": ["SG-IDENTITY-001"]}])

    def interleave(target):
        run_pipeline(raw, target, tenant_id="audit")
        return original(target)

    monkeypatch.setattr(framework_report, "read_summary", interleave)
    report = build_framework_report(lake, tenant_id="audit", framework_ids=["soc2"])
    assert report["generation"] == before
    assert report["contains_synthetic_evidence"] is True
    assert generation_identity(lake) != before


def test_failed_publication_removes_temporary_file(lake, tmp_path, monkeypatch):
    from security_lakehouse import framework_report

    report = build_framework_report(lake, tenant_id="audit", framework_ids=["soc2"])
    out = tmp_path / "report.zip"

    def fail(_):
        raise OSError("simulated write failure")

    monkeypatch.setattr(framework_report.os, "fsync", fail)
    with pytest.raises(OSError, match="write failure"):
        export_framework_report(report, out)
    assert not out.exists()
    assert not list(tmp_path.glob(".framework-report-*"))


def test_cli_scope_and_no_overwrite_boundaries(lake, tmp_path, capsys):
    from security_lakehouse.cli import main

    base = ["assessment", "framework-report", "--lake", str(lake), "--tenant-id", "audit", "--framework", "soc2"]
    target = tmp_path / "review.zip"
    assert main([*base, "--out", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["frameworks"] == 1
    with pytest.raises(SystemExit):
        main([*base, "--out", str(target)])
    with pytest.raises(SystemExit, match="outside the lake"):
        main([*base, "--out", str(lake / "report.zip")])
    symlink = tmp_path / "alias.zip"
    symlink.symlink_to(tmp_path / "absent.zip")
    with pytest.raises(SystemExit):
        main([*base, "--out", str(symlink)])
    assert not (tmp_path / "absent.zip").exists()


def test_empty_evidence_keeps_full_denominator_and_zero_assessed(tmp_path):
    raw = tmp_path / "empty.jsonl"
    write_jsonl(raw, [])
    lake = tmp_path / "empty-lake"
    run_pipeline(raw, lake, tenant_id="audit")
    report = build_framework_report(lake, tenant_id="audit", framework_ids=["soc2"])
    summary = report["frameworks"][0]
    assert summary["catalogued"] > 0
    assert summary["assessed"] == 0
    assert summary["status_counts"]["pass"] == 0
    assert summary["assessed_pct"] == 0
    assert summary["requirements_with_gaps"] == summary["catalogued"]
