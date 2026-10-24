"""Fail a pull request that changes product code without changing any test."""

from __future__ import annotations

import argparse
import subprocess
import sys

SOURCE_PREFIXES = ("src/", "app/web/src/", "tools/")
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".mjs", ".js")
TEST_PREFIXES = ("tests/", "app/web/e2e/", "app/web/e2e-demo/")
FIXTURE_PREFIXES = ("tests/fixtures/",)


def _is_source(path: str) -> bool:
    return path.startswith(SOURCE_PREFIXES) and path.endswith(SOURCE_SUFFIXES)


def _is_test(path: str) -> bool:
    return path.startswith(TEST_PREFIXES) and not path.startswith(FIXTURE_PREFIXES)


def untested_source_changes(changed: list[str]) -> list[str]:
    if any(_is_test(path) for path in changed):
        return []
    return [path for path in changed if _is_source(path)]


def _changed_files(repo: str, base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", "--diff-filter=ACMR", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--skip", action="store_true", help="the pull request carries the no-test-needed label")
    args = parser.parse_args(argv)

    if args.skip:
        print("no-test-needed label present; skipping the test-change check")
        return 0
    untested = untested_source_changes(_changed_files(args.repo, args.base, args.head))
    if not untested:
        return 0
    print("Product code changed without a test change:")
    for path in untested:
        print(f"  {path}")
    print(
        "Add or update a test that fails without this change (see AGENTS.md, Test-driven changes). "
        "For a pure refactor or docs-only code move, a maintainer can add the no-test-needed label and re-run this job."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
