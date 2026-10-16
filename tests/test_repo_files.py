"""Repo-walking tests see what CI sees: tracked files, never local caches."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from repo_files import repo_files


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _tree(root: Path) -> None:
    for relative in (
        "README.md",
        "docs/guide.md",
        "docs/gone.md",
        "docs/new.md",
        "deploy/.terraform/modules/vpc/README.md",
        "node_modules/pkg/README.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x\n")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_checkout_lists_only_existing_tracked_files(tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / ".gitignore").write_text(".terraform/\nnode_modules/\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".gitignore", "README.md", "docs/guide.md", "docs/gone.md")
    (tmp_path / "docs/gone.md").unlink()

    assert repo_files(root=tmp_path) == [tmp_path / p for p in (".gitignore", "README.md", "docs/guide.md")]
    assert repo_files("docs", root=tmp_path) == [tmp_path / "docs/guide.md"]


def test_outside_git_falls_back_to_walking_without_generated_trees(tmp_path: Path, monkeypatch) -> None:
    _tree(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))

    assert repo_files(root=tmp_path) == [
        tmp_path / p for p in ("README.md", "docs/gone.md", "docs/guide.md", "docs/new.md")
    ]
    assert repo_files("missing", root=tmp_path) == []
