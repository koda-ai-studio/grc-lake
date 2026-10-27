"""Refresh tools/ci_test_durations.json from CI JUnit reports.

Download the ``pytest-*`` artifacts of a passing CI run, then:

    python tools/update_test_durations.py build/junit/*/pytest-results.xml

Only module totals are kept; the shard plugin estimates modules missing from
the file, so a stale file degrades balance, never correctness.
"""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tools/ci_test_durations.json"


def module_durations(reports: list[Path]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for report in reports:
        for case in ET.parse(report).iter("testcase"):
            parts = (case.get("classname") or "").split(".")
            module = next((index for index, part in enumerate(parts) if part.startswith("test_")), None)
            if module is None:
                continue
            totals["/".join(parts[: module + 1]) + ".py"] += float(case.get("time") or 0)
    return {name: round(seconds, 2) for name, seconds in sorted(totals.items())}


def playwright_durations(reports: list[Path]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    seen: set[tuple[str, str, int]] = set()
    for report in reports:
        payload = json.loads(report.read_text())
        if (
            payload.get("errors")
            or payload.get("stats", {}).get("unexpected", 1)
            or payload.get("stats", {}).get("interrupted", 0)
        ):
            raise ValueError("unsuccessful or incomplete Playwright report")
        suites = [payload]
        while suites:
            suite = suites.pop()
            suites.extend(suite.get("suites", []))
            for spec in suite.get("specs", []):
                for index, test in enumerate(spec.get("tests", [])):
                    key = (spec["id"], test.get("projectId", test.get("projectName", "")), index)
                    if key in seen:
                        raise ValueError("duplicate test across Playwright reports")
                    seen.add(key)
                    results = test.get("results", [])
                    if not results:
                        raise ValueError("incomplete Playwright execution")
                    for result in results:
                        duration = result.get("duration")
                        if (
                            isinstance(duration, bool)
                            or not isinstance(duration, int | float)
                            or not math.isfinite(duration)
                            or duration < 0
                        ):
                            raise ValueError("invalid Playwright duration")
                        totals[spec["file"]] += duration / 1000
    if not seen:
        raise ValueError("empty Playwright reports")
    return {name: round(seconds, 3) for name, seconds in sorted(totals.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--format", choices=("junit", "playwright"), default="junit")
    args = parser.parse_args(argv)
    durations = playwright_durations(args.reports) if args.format == "playwright" else module_durations(args.reports)
    output = args.out or (ROOT / "tools/ci_e2e_durations.json" if args.format == "playwright" else DEFAULT_OUTPUT)
    if not durations:
        parser.error("no test cases found in the given reports")
    output.write_text(json.dumps(durations, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(durations)} module durations, {sum(durations.values()) / 60:.1f} test-minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
