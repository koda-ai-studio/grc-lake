"""Refresh tools/ci_test_durations.json from CI JUnit reports.

Download the ``pytest-*`` artifacts of a passing CI run, then:

    python tools/update_test_durations.py build/junit/*/pytest-results.xml

Only module totals are kept; the shard plugin estimates modules missing from
the file, so a stale file degrades balance, never correctness.
"""

from __future__ import annotations

import argparse
import json
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    durations = module_durations(args.reports)
    if not durations:
        parser.error("no test cases found in the given reports")
    args.out.write_text(json.dumps(durations, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(durations)} module durations, {sum(durations.values()) / 60:.1f} test-minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
