"""Refuse a release tag whose changelog section is missing, empty, or incomplete.

The GitHub release body is the version's CHANGELOG section. Entries still under
`## Unreleased` when the tag is pushed ship in the release but are missing from
its notes, so they must be moved into the version section first.

    python tools/check_changelog_release.py 0.3.12
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        heading = re.match(r"^## (\S+)", line)
        if heading:
            current = sections.setdefault(heading.group(1), [])
        elif current is not None and line.startswith("- "):
            current.append(line)
    return sections


def problems(text: str, version: str) -> list[str]:
    sections = _sections(text)
    found: list[str] = []
    if version not in sections:
        found.append(f"CHANGELOG.md has no '## {version}' section")
    elif not sections[version]:
        found.append(f"CHANGELOG.md section '## {version}' has no entries")
    unreleased = len(sections.get("Unreleased", []))
    if unreleased:
        noun = "entry" if unreleased == 1 else "entries"
        found.append(
            f"CHANGELOG.md has {unreleased} {noun} under '## Unreleased'; "
            f"move shipped entries into '## {version}' before tagging"
        )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    args = parser.parse_args(argv)
    found = problems(args.changelog.read_text(encoding="utf-8"), args.version)
    for problem in found:
        print(f"::error::{problem}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
