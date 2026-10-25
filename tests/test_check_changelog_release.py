"""A release tag must carry every changelog entry in its own section."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from check_changelog_release import main, problems

ROOT = Path(__file__).resolve().parents[1]

HEADER = "# Changelog\n\nIntro.\n\n"


def test_a_released_section_with_entries_passes() -> None:
    assert (
        problems(HEADER + "## 1.2.3 - 2026-10-25\n\n- Fix a thing.\n\n## 1.2.2 - 2026-10-24\n\n- Old.\n", "1.2.3") == []
    )


def test_an_empty_unreleased_heading_is_allowed() -> None:
    text = HEADER + "## Unreleased\n\n## 1.2.3 - 2026-10-25\n\n- Fix a thing.\n"
    assert problems(text, "1.2.3") == []


def test_entries_left_under_unreleased_block_the_tag() -> None:
    text = HEADER + "## Unreleased\n\n- Shipped but not moved.\n\n## 1.2.3 - 2026-10-25\n\n- Fix a thing.\n"
    found = problems(text, "1.2.3")
    assert len(found) == 1 and "Unreleased" in found[0] and "1 entry" in found[0]


def test_a_missing_version_section_blocks_the_tag() -> None:
    found = problems(HEADER + "## 1.2.2 - 2026-10-24\n\n- Old.\n", "1.2.3")
    assert found == ["CHANGELOG.md has no '## 1.2.3' section"]


def test_an_empty_version_section_blocks_the_tag() -> None:
    found = problems(HEADER + "## 1.2.3 - 2026-10-25\n\n## 1.2.2 - 2026-10-24\n\n- Old.\n", "1.2.3")
    assert found == ["CHANGELOG.md section '## 1.2.3' has no entries"]


def test_main_reports_and_fails(tmp_path: Path, capsys) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(HEADER + "## Unreleased\n\n- a\n- b\n\n## 1.2.3 - 2026-10-25\n\n- c\n")
    assert main(["1.2.3", "--changelog", str(changelog)]) == 1
    assert "2 entries" in capsys.readouterr().out
    changelog.write_text(HEADER + "## 1.2.3 - 2026-10-25\n\n- c\n")
    assert main(["1.2.3", "--changelog", str(changelog)]) == 0


def test_the_release_version_gate_runs_the_check() -> None:
    gate = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]["verify-version"]
    commands = "\n".join(step.get("run", "") for step in gate["steps"])
    assert 'tools/check_changelog_release.py "${project_version}" --changelog CHANGELOG.md' in commands


def test_the_published_image_is_rescanned_daily() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/image-watch.yml").read_text())
    triggers = workflow[True]  # PyYAML reads the bare `on:` key as boolean True
    assert triggers["schedule"] and "workflow_dispatch" in triggers
    assert workflow["permissions"] in ("read-all", {"contents": "read"})
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    scans = [step for step in steps if "trivy-action" in step.get("uses", "")]
    assert {scan["with"]["image-ref"] for scan in scans} == {"ghcr.io/koda-ai-studio/grc-lake:latest"}
    assert {scan["env"]["TRIVY_PLATFORM"] for scan in scans} == {"linux/amd64", "linux/arm64"}
    policy = [step["run"] for step in steps if "check_image_vulnerabilities.py" in step.get("run", "")]
    assert len(policy) == 2
