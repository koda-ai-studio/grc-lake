"""List the repository files that CI would see: tracked files, not local caches."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_GENERATED_DIRS = frozenset(
    {".git", ".venv", ".claude", ".next", ".pytest_cache", ".terraform", "__pycache__", "node_modules", "build", "dist"}
)


def repo_files(*dirs: str, root: Path = ROOT) -> list[Path]:
    """Existing tracked files under ``dirs`` (default: the whole repo), sorted.

    Outside a git checkout, such as an unpacked source archive, walk the tree
    and skip generated directories instead.
    """
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", *dirs], cwd=root, check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        bases = [root / d for d in dirs] if dirs else [root]
        candidates = {
            path
            for base in bases
            for path in base.rglob("*")
            if path.is_file() and not _GENERATED_DIRS & set(path.relative_to(root).parts)
        }
    else:
        candidates = {root / name for name in listed.decode().split("\0") if name}
    return sorted(path for path in candidates if path.is_file())
