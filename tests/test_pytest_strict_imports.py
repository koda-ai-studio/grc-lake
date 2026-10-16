"""CI must fail, not skip, when an optional dependency it installs is missing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_pytest(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=directory,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_ADDOPTS": ""},
        text=True,
        capture_output=True,
        check=False,
    )


def _write_suite(directory: Path) -> None:
    (directory / "test_module_level.py").write_text(
        "import pytest\npytest.importorskip('grc_lake_absent_module')\ndef test_never():\n    pass\n"
    )
    (directory / "test_in_function.py").write_text(
        "import pytest\ndef test_import():\n    pytest.importorskip('grc_lake_absent_module.sub')\n"
        "def test_ordinary_skip():\n    pytest.skip('not an import')\n"
    )


def test_import_skips_stay_skips_without_the_plugin(tmp_path: Path) -> None:
    _write_suite(tmp_path)
    result = run_pytest(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 skipped" in result.stdout


def test_strict_imports_turns_import_skips_into_failures(tmp_path: Path) -> None:
    _write_suite(tmp_path)
    result = run_pytest(tmp_path, "-p", "tools.pytest_strict_imports", "--continue-on-collection-errors", "-rA")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 failed" in result.stdout
    assert "1 skipped" in result.stdout
    assert "1 error" in result.stdout
    assert "grc_lake_absent_module" in result.stdout


def test_strict_imports_honours_explicit_allowances(tmp_path: Path) -> None:
    _write_suite(tmp_path)
    result = run_pytest(tmp_path, "-p", "tools.pytest_strict_imports", "--allow-import-skip=grc_lake_absent_module")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 skipped" in result.stdout
