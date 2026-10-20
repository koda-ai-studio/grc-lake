"""A self-consistent replacement must not satisfy an independently retained digest."""

import copy
import json
from pathlib import Path

import pytest

from security_lakehouse.audit_workpapers import build_workpaper, export_workpaper, verify_workpaper_export
from security_lakehouse.cli import main
from security_lakehouse.io import canonical_sha256
from security_lakehouse.pipeline import run_pipeline


@pytest.fixture(scope="module")
def content(tmp_path_factory):
    root = Path(__file__).resolve().parents[1] / "examples/control-assurance"
    lake = tmp_path_factory.mktemp("handoff") / "lake"
    run_pipeline(root / "events.jsonl", lake)
    return build_workpaper(
        lake,
        plan=json.loads((root / "plan.json").read_text()),
        baseline=json.loads((root / "baseline.json").read_text()),
    )


def test_pinned_content_accepts_original_without_asserting_review(content, tmp_path):
    export_workpaper(content, tmp_path / "bundle")
    digest = canonical_sha256(content)
    result = verify_workpaper_export(tmp_path / "bundle", expected_content_sha256=digest)
    assert result["ok"] is True
    assert result["bundle_integrity_verified"] is True
    assert result["expected_content_matches"] is True
    assert result["content_sha256"] == digest
    assert result["verification_scope"] == "bundle_consistency_and_expected_content"
    assert "review identity requires server record" in result["authentication"]


@pytest.mark.parametrize("changed", ["tenant", "period", "conclusion", "narrative"])
def test_self_consistent_replacement_rejected(content, tmp_path, changed):
    digest = canonical_sha256(content)
    replacement = copy.deepcopy(content)
    if changed == "tenant":
        replacement["tenant_id"] = "different-tenant"
    elif changed == "period":
        replacement["plan"]["period_end"] = "2026-02-01T00:00:00Z"
    elif changed == "conclusion":
        replacement["assurance"]["controls"][0]["operating"]["status"] = "sample_pass"
    else:
        replacement["narrative"]["text"] = "Replacement narrative"
    export_workpaper(replacement, tmp_path / "bundle")
    assert verify_workpaper_export(tmp_path / "bundle")["ok"] is True
    result = verify_workpaper_export(tmp_path / "bundle", expected_content_sha256=digest)
    assert result["ok"] is False
    assert result["bundle_integrity_verified"] is True
    assert result["expected_content_matches"] is False
    assert result["content_sha256"] == canonical_sha256(replacement)


@pytest.mark.parametrize("damage", ["html", "manifest", "extra_file", "symlink", "missing"])
def test_matching_pin_cannot_bypass_bundle_checks(content, tmp_path, damage):
    bundle = tmp_path / "bundle"
    export_workpaper(content, bundle)
    if damage == "html":
        (bundle / "index.html").write_text("Changed")
    elif damage == "manifest":
        (bundle / "manifest.json").write_text("{}")
    elif damage == "extra_file":
        (bundle / "extra.txt").write_text("Unexpected")
    elif damage == "symlink":
        (bundle / "index.html").unlink()
        (bundle / "index.html").symlink_to(tmp_path / "outside")
    else:
        (bundle / "workpaper.json").unlink()
    result = verify_workpaper_export(bundle, expected_content_sha256=canonical_sha256(content))
    assert result["ok"] is False
    assert result["bundle_integrity_verified"] is False


@pytest.mark.parametrize("digest", ["", "a" * 63, "g" * 64, "a" * 64 + "\n", " " + "a" * 64])
def test_malformed_pin_fails_explicitly(content, tmp_path, digest):
    export_workpaper(content, tmp_path / "bundle")
    with pytest.raises(ValueError, match="64 hexadecimal"):
        verify_workpaper_export(tmp_path / "bundle", expected_content_sha256=digest)


def test_uppercase_digest_accepted(content, tmp_path):
    export_workpaper(content, tmp_path / "bundle")
    assert verify_workpaper_export(tmp_path / "bundle", expected_content_sha256=canonical_sha256(content).upper())["ok"]


def test_cli_emits_machine_readable_pin_verdict(content, tmp_path, capsys):
    export_workpaper(content, tmp_path / "bundle")
    args = ["assessment", "verify-workpaper", "--dir", str(tmp_path / "bundle"), "--expected-content-sha256"]
    assert main([*args, canonical_sha256(content)]) == 0
    assert json.loads(capsys.readouterr().out)["expected_content_matches"] is True
    assert main([*args, "0" * 64]) == 1
    assert json.loads(capsys.readouterr().out)["expected_content_matches"] is False
    with pytest.raises(SystemExit) as exc:
        main([*args, "invalid"])
    assert exc.value.code == 2
    assert "64 hexadecimal" in capsys.readouterr().err
