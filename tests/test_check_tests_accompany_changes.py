"""Pull requests that change product code must change tests too."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml
from tools.check_tests_accompany_changes import main, untested_source_changes

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "changed",
    [
        ["src/security_lakehouse/connectors_aws.py", "tests/test_aws_posture.py"],
        ["app/web/src/lib/format.ts", "app/web/e2e/format.spec.ts"],
        ["app/web/src/components/QueryState.tsx", "app/web/e2e-demo/live-demo.spec.ts"],
        ["tools/render_readme_header.py", "tests/test_readme_visual_contract.py"],
        ["README.md", "docs/CONNECTORS.md", "CHANGELOG.md"],
        ["uv.lock", "app/web/package-lock.json"],
        ["connectors/catalog.json", "controls/safeguards.json"],
        [],
    ],
)
def test_changes_with_tests_or_without_product_code_pass(changed: list[str]) -> None:
    assert untested_source_changes(changed) == []


@pytest.mark.parametrize(
    ("changed", "flagged"),
    [
        (["src/security_lakehouse/connectors_aws.py"], ["src/security_lakehouse/connectors_aws.py"]),
        (["app/web/src/lib/format.ts", "README.md"], ["app/web/src/lib/format.ts"]),
        (["tools/render_readme_header.py", "docs/README.md"], ["tools/render_readme_header.py"]),
    ],
)
def test_product_code_without_tests_is_flagged(changed: list[str], flagged: list[str]) -> None:
    assert untested_source_changes(changed) == flagged


def test_test_fixtures_alone_do_not_count_as_tests() -> None:
    changed = ["src/security_lakehouse/connectors_snyk.py", "tests/fixtures/snyk/orgs.json"]
    assert untested_source_changes(changed) == ["src/security_lakehouse/connectors_snyk.py"]


def test_cli_fails_with_guidance_and_honours_the_skip_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "ci@example.com")
    git("config", "user.name", "CI")
    (tmp_path / "README.md").write_text("base\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-qm", "change")
    head = git("rev-parse", "HEAD")

    assert main([base, head, "--repo", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "src/module.py" in out
    assert "no-test-needed" in out
    assert main([base, head, "--repo", str(tmp_path), "--skip"]) == 0


def test_ci_runs_the_gate_on_pull_requests_only() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
    gate = jobs["tests-accompany-changes"]
    assert gate["if"] == "github.event_name == 'pull_request'"
    run = " ".join(step.get("run", "") for step in gate["steps"])
    assert "tools/check_tests_accompany_changes.py" in run
    assert "no-test-needed" in str(gate)
