"""Duration balancing must preserve every Playwright test and its exit status."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _report():
    return {
        "suites": [
            {
                "suites": [
                    {
                        "specs": [
                            {"file": file, "id": file, "tests": [{"projectName": "chromium"}]}
                            for file in ["a.spec.ts", "slow[1].spec.ts", "new.spec.ts"]
                        ]
                    }
                ]
            }
        ]
    }


def test_duration_plan_is_complete_stable_and_balanced():
    from tools.pytest_shard import assign_shards, duration_weights

    counts = {"slow": 2, "a": 6, "b": 6, "c": 6, "new": 4}
    weights = duration_weights(counts, {"slow": 100.0, "a": 6.0, "b": 6.0, "c": 6.0})
    owners = assign_shards(weights, 2)
    assert set(owners) == set(counts)
    assert owners == assign_shards(dict(reversed(list(weights.items()))), 2)
    assert [name for name in counts if owners[name] == owners["slow"]] == ["slow"]


@pytest.mark.parametrize("seconds", [-1, True, float("inf"), float("nan"), "10"])
def test_invalid_timing_weights_fail_closed(seconds):
    from tools.pytest_shard import duration_weights

    with pytest.raises(ValueError, match="finite non-negative"):
        duration_weights({"a": 1}, {"a": seconds})


def test_playwright_collection_preserves_projects_and_rejects_errors():
    from tools.run_e2e_shard import collected_tests

    report = _report()
    report["suites"][0]["suites"][0]["specs"][0]["tests"].append({"projectName": "mobile"})
    tests = collected_tests(report)
    assert sum(len(v) for v in tests.values()) == 4
    assert len(tests["a.spec.ts"]) == 2
    with pytest.raises(ValueError, match="collection"):
        collected_tests({"errors": [{"message": "broken test import"}], "suites": []})
    with pytest.raises(ValueError, match="empty"):
        collected_tests({"suites": []})


@pytest.mark.parametrize("exit_code", [0, 1, 130])
def test_runner_verifies_selection_and_preserves_test_exit(tmp_path: Path, monkeypatch, exit_code):
    from tools import run_e2e_shard as runner

    weights = tmp_path / "weights.json"
    weights.write_text(json.dumps({"slow[1].spec.ts": 100, "a.spec.ts": 1, "new.spec.ts": 1}))
    calls = []
    selected = {"suites": [{"specs": [_report()["suites"][0]["suites"][0]["specs"][1]]}]}

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "--list" in command:
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(_report() if len(calls) == 1 else selected), stderr=""
            )
        return SimpleNamespace(returncode=exit_code)

    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setenv("PLAYWRIGHT_JSON_OUTPUT_FILE", "previous-run.json")
    assert runner.main(["--shard", "1/2", "--durations", str(weights), "--out", str(tmp_path)]) == exit_code
    assert len(calls) == 3
    output_file_removed = "PLAYWRIGHT_JSON_OUTPUT_FILE" not in calls[0][1]["env"]
    assert output_file_removed
    assert any(r"slow\[1\]\.spec\.ts$" in arg for arg in calls[-1][0])
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["selected_files"] == ["slow[1].spec.ts"]
    assert plan["selected_tests"] == 1 and plan["total_tests"] == 3


def test_runner_does_not_run_when_selection_is_incomplete(tmp_path: Path, monkeypatch):
    from tools import run_e2e_shard as runner

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert "--list" in command
        return SimpleNamespace(returncode=0, stdout=json.dumps(_report()), stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)
    weights = tmp_path / "weights.json"
    weights.write_text("{}")
    assert runner.main(["--shard", "1/2", "--durations", str(weights), "--out", str(tmp_path)]) != 0
    assert len(calls) == 2


@pytest.mark.parametrize("shard", ["0/2", "3/2", "1/0", "bad"])
def test_invalid_shard_does_not_start_playwright(tmp_path: Path, monkeypatch, shard):
    from tools import run_e2e_shard as runner

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: pytest.fail("invalid shard executed"))
    assert runner.main(["--shard", shard, "--out", str(tmp_path)]) != 0


def test_refresh_uses_measured_file_totals_and_includes_retries(tmp_path: Path):
    from tools.update_test_durations import playwright_durations

    report = _report()
    for spec in report["suites"][0]["suites"][0]["specs"]:
        spec["tests"][0]["results"] = [{"duration": 200, "status": "failed"}, {"duration": 300, "status": "passed"}]
    report["stats"] = {"unexpected": 0}
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report))
    assert playwright_durations([path]) == {"a.spec.ts": 0.5, "new.spec.ts": 0.5, "slow[1].spec.ts": 0.5}
    with pytest.raises(ValueError, match="duplicate"):
        playwright_durations([path, path])
    report["stats"]["unexpected"] = 1
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="unsuccessful"):
        playwright_durations([path])


@pytest.mark.parametrize("duration", [-1, True, float("inf"), float("nan"), None])
def test_refresh_rejects_invalid_durations(tmp_path: Path, duration):
    from tools.update_test_durations import playwright_durations

    report = _report()
    report["stats"] = {"unexpected": 0}
    for spec in report["suites"][0]["suites"][0]["specs"]:
        spec["tests"][0]["results"] = [{"duration": duration}]
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="invalid Playwright duration"):
        playwright_durations([path])


def test_refresh_rejects_interrupted_execution(tmp_path: Path):
    from tools.update_test_durations import playwright_durations

    report = _report()
    report["stats"] = {"unexpected": 0, "interrupted": 1}
    for spec in report["suites"][0]["suites"][0]["specs"]:
        spec["tests"][0]["results"] = [{"duration": 100, "status": "interrupted"}]
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="unsuccessful or incomplete"):
        playwright_durations([path])
