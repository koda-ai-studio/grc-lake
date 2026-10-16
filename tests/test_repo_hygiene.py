from __future__ import annotations

from pathlib import Path

from repo_files import ROOT, repo_files

# Source roots that must stay free of editor / Finder copy artifacts.
_SOURCE_ROOTS = ("src/security_lakehouse", "tests", "app/web/src")


def _is_copy_artifact(path: Path) -> bool:
    name = path.name
    stem = path.stem
    return " copy" in name or path.suffix in {".bak", ".orig"} or any(f" {i}" in stem for i in range(2, 10))


def test_source_tree_has_no_editor_copy_artifacts() -> None:
    offenders = [path.relative_to(ROOT).as_posix() for path in repo_files(*_SOURCE_ROOTS) if _is_copy_artifact(path)]
    assert offenders == [], f"editor/Finder copy artifacts found: {offenders}"
