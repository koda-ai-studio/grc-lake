"""Run complete Playwright files in measured-time shards; keep normal local runs unchanged."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.pytest_shard import assign_shards, duration_weights

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app/web"


def collected_tests(report: dict[str, Any]) -> dict[str, set[tuple[str, str, int]]]:
    if report.get("errors"):
        raise ValueError("Playwright collection reported errors")
    files: dict[str, set[tuple[str, str, int]]] = defaultdict(set)

    def visit(suite: dict[str, Any]) -> None:
        for spec in suite.get("specs", []):
            for index, test in enumerate(spec.get("tests", [])):
                key = (spec["id"], test.get("projectId", test.get("projectName", "")), index)
                if key in files[spec["file"]]:
                    raise ValueError("duplicate test in Playwright collection")
                files[spec["file"]].add(key)
        for child in suite.get("suites", []):
            visit(child)

    visit(report)
    if not files:
        raise ValueError("empty Playwright collection")
    return dict(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", required=True)
    parser.add_argument("--durations", type=Path, default=ROOT / "tools/ci_e2e_durations.json")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        index, count = map(int, args.shard.split("/"))
        if not 1 <= index <= count:
            raise ValueError("shard must be index/count with 1 <= index <= count")
        out = (args.out or ROOT / f"build/e2e-shard-{index}").resolve()
        out.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        for key in ("PLAYWRIGHT_JSON_OUTPUT_FILE", "PLAYWRIGHT_JSON_OUTPUT_NAME", "PLAYWRIGHT_JSON_OUTPUT_DIR"):
            env.pop(key, None)
        command = ["node", str(WEB / "node_modules/@playwright/test/cli.js"), "test"]

        def collect(filters: list[str]) -> dict[str, set[tuple[str, str, int]]]:
            result = subprocess.run(
                [*command, "--list", "--reporter=json", *filters],
                cwd=WEB,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise ValueError(f"Playwright collection failed ({result.returncode}): {result.stderr}")
            return collected_tests(json.loads(result.stdout))

        files = collect([])
        weights = duration_weights(
            {name: float(len(tests)) for name, tests in files.items()}, json.loads(args.durations.read_text())
        )
        owners = assign_shards(weights, count)
        selected = sorted(name for name in files if owners[name] == index - 1)
        if not selected:
            raise ValueError("empty shard; refusing a passing no-test run")
        filters = [r"(?:^|/)" + re.escape(name) + "$" for name in selected]
        expected = {name: files[name] for name in selected}
        if collect(filters) != expected:
            raise ValueError("selected Playwright collection does not match the planned tests")
        plan = {
            "shard": args.shard,
            "selected_files": selected,
            "selected_tests": sum(map(len, expected.values())),
            "total_tests": sum(map(len, files.values())),
            "estimated_seconds": sum(weights[name] for name in selected),
            "owners": owners,
        }
        (out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
        print(json.dumps(plan), flush=True)
        execution_env = {**env, "PLAYWRIGHT_JSON_OUTPUT_FILE": str(out / "results.json")}
        reporter = "github,json" if env.get("CI") else "list,json"
        return subprocess.run(
            [*command, f"--reporter={reporter}", *filters], cwd=WEB, env=execution_env, check=False
        ).returncode
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"E2E shard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
