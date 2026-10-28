"""CI sharding must run every collected test once and preserve failures."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_pytest(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tools.pytest_shard", "-q", *args],
        cwd=directory,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_ADDOPTS": ""},
        text=True,
        capture_output=True,
        check=False,
    )


def test_shards_partition_parametrized_tests_without_splitting_modules(tmp_path: Path) -> None:
    for name, size in [("a", 13), ("b", 7), ("c", 5), ("d", 2), ("new_module", 3)]:
        (tmp_path / f"test_{name}.py").write_text(
            f"import pytest\n@pytest.mark.parametrize('value', range({size}))\n"
            "def test_value(value):\n    assert value >= 0\n"
        )
    full = run_pytest(tmp_path, "--collect-only")
    assert full.returncode == 0, full.stderr + full.stdout
    expected = {line for line in full.stdout.splitlines() if "::" in line}
    seen: set[str] = set()
    module_owner: dict[str, int] = {}
    for index in range(1, 5):
        result = run_pytest(tmp_path, "--collect-only", f"--ci-shard={index}/4")
        assert result.returncode == 0, result.stderr + result.stdout
        selected = {line for line in result.stdout.splitlines() if "::" in line}
        assert selected
        assert not seen & selected
        seen.update(selected)
        for node in selected:
            module = node.split("::", 1)[0]
            assert module_owner.setdefault(module, index) == index
        executed = run_pytest(tmp_path, f"--ci-shard={index}/4")
        assert executed.returncode == 0, executed.stderr + executed.stdout
        assert f"{len(selected)} passed" in executed.stdout
    assert seen == expected
    assert len(seen) == 30


@pytest.mark.parametrize("shard", ["0/4", "5/4", "1/0", "1", "one/four"])
def test_invalid_shard_fails_closed(tmp_path: Path, shard: str) -> None:
    result = run_pytest(tmp_path, f"--ci-shard={shard}")
    assert result.returncode == 4
    assert "--ci-shard" in result.stderr


def test_shard_preserves_test_failures_and_empty_collection(tmp_path: Path) -> None:
    (tmp_path / "test_failure.py").write_text("def test_failure():\n    assert False\n")
    failed = run_pytest(tmp_path, "--ci-shard=1/1")
    assert failed.returncode == 1
    assert "1 failed" in failed.stdout
    empty = run_pytest(tmp_path, "--ci-shard=2/2")
    assert empty.returncode == 5


def test_recorded_durations_balance_shards_by_time_not_count(tmp_path: Path) -> None:
    import json

    for name, size in [("slow", 2), ("a", 6), ("b", 6), ("c", 6), ("new_module", 4)]:
        (tmp_path / f"test_{name}.py").write_text(
            f"import pytest\n@pytest.mark.parametrize('value', range({size}))\n"
            "def test_value(value):\n    assert value >= 0\n"
        )
    durations = tmp_path / "durations.json"
    durations.write_text(json.dumps({"test_slow.py": 100.0, "test_a.py": 6.0, "test_b.py": 6.0, "test_c.py": 6.0}))
    owners: dict[str, int] = {}
    seen: set[str] = set()
    for index in range(1, 3):
        result = run_pytest(tmp_path, "--collect-only", f"--ci-shard={index}/2", f"--ci-shard-durations={durations}")
        assert result.returncode == 0, result.stderr + result.stdout
        for node in (line for line in result.stdout.splitlines() if "::" in line):
            seen.add(node)
            owners[node.split("::", 1)[0]] = index
    assert len(seen) == 24
    # Two slow tests outweigh twenty-two fast ones, so they get a shard to themselves.
    assert [module for module, owner in owners.items() if owner == owners["test_slow.py"]] == ["test_slow.py"]


def _junit_report(path: Path, *, duration="1.5", result="", tests="1", failures="0", errors="0") -> Path:
    path.write_text(
        f'<testsuites><testsuite tests="{tests}" failures="{failures}" errors="{errors}">'
        f'<testcase classname="tests.test_example" name="test_case" time="{duration}">'
        f"{result}</testcase></testsuite></testsuites>"
    )
    return path


def test_junit_refresh_keeps_successful_and_explicitly_skipped_cases(tmp_path: Path) -> None:
    from tools.update_test_durations import module_durations

    path = _junit_report(tmp_path / "results.xml", result='<skipped message="optional environment"/>')
    assert module_durations([path]) == {"tests/test_example.py": 1.5}


@pytest.mark.parametrize(
    "kwargs",
    [{"result": "<failure/>"}, {"result": "<error/>"}, {"failures": "1"}, {"errors": "1"}, {"tests": "2"}],
)
def test_junit_refresh_rejects_failed_or_incomplete_reports(tmp_path: Path, kwargs) -> None:
    from tools.update_test_durations import module_durations

    with pytest.raises(ValueError, match="unsuccessful or incomplete"):
        module_durations([_junit_report(tmp_path / "results.xml", **kwargs)])


@pytest.mark.parametrize("duration", ["-1", "nan", "inf", "not-a-number", ""])
def test_junit_refresh_rejects_invalid_timings(tmp_path: Path, duration: str) -> None:
    from tools.update_test_durations import module_durations

    with pytest.raises(ValueError, match="invalid JUnit duration"):
        module_durations([_junit_report(tmp_path / "results.xml", duration=duration)])


def test_junit_refresh_rejects_duplicate_cases_across_shards(tmp_path: Path) -> None:
    from tools.update_test_durations import module_durations

    with pytest.raises(ValueError, match="duplicate"):
        module_durations([_junit_report(tmp_path / "first.xml"), _junit_report(tmp_path / "second.xml")])


def test_refresh_missing_shard_does_not_replace_recorded_weights(tmp_path: Path) -> None:
    from tools.update_test_durations import main

    output = tmp_path / "weights.json"
    output.write_text('{"tests/test_example.py": 9.0}\n')
    report = _junit_report(tmp_path / "results.xml")
    with pytest.raises(SystemExit) as failure:
        main([str(report), "--expected-reports", "6", "--out", str(output)])
    assert failure.value.code == 2
    assert output.read_text() == '{"tests/test_example.py": 9.0}\n'
    assert main([str(report), "--expected-reports", "1", "--out", str(output)]) == 0


def test_refresh_averages_complete_runs_without_treating_replays_as_duplicates(tmp_path: Path) -> None:
    from tools.update_test_durations import main

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _junit_report(first / "pytest-results.xml", duration="1.0")
    _junit_report(second / "pytest-results.xml", duration="5.0")
    output = tmp_path / "weights.json"
    assert (
        main(["--run-dir", str(first), "--run-dir", str(second), "--expected-reports", "1", "--out", str(output)]) == 0
    )
    import json

    assert json.loads(output.read_text()) == {"tests/test_example.py": 3.0}


@pytest.mark.parametrize("mismatch", ["missing_shard", "changed_case", "changed_module"])
def test_multi_run_refresh_preserves_weights_when_runs_are_not_comparable(tmp_path: Path, mismatch: str) -> None:
    from tools.update_test_durations import main

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    _junit_report(first / "pytest-results.xml")
    if mismatch != "missing_shard":
        report = _junit_report(second / "pytest-results.xml")
        old, new = ("test_case", "test_other") if mismatch == "changed_case" else ("test_example", "test_different")
        report.write_text(report.read_text().replace(old, new))
    output = tmp_path / "weights.json"
    output.write_text('{"existing": 7.0}\n')
    with pytest.raises((SystemExit, ValueError)):
        main(["--run-dir", str(first), "--run-dir", str(second), "--expected-reports", "1", "--out", str(output)])
    assert output.read_text() == '{"existing": 7.0}\n'


@pytest.mark.parametrize("invalid", ["no_count", "playwright", "duplicate_run", "mixed_inputs"])
def test_multi_run_refresh_rejects_ambiguous_inputs(tmp_path: Path, invalid: str) -> None:
    from tools.update_test_durations import main

    report = _junit_report(tmp_path / "pytest-results.xml")
    output = tmp_path / "weights.json"
    output.write_text('{"existing": 7.0}\n')
    args = ["--run-dir", str(tmp_path), "--out", str(output)]
    if invalid != "no_count":
        args += ["--expected-reports", "1"]
    if invalid == "playwright":
        args += ["--format", "playwright"]
    elif invalid == "duplicate_run":
        args += ["--run-dir", str(tmp_path)]
    elif invalid == "mixed_inputs":
        args += [str(report)]
    with pytest.raises(SystemExit) as failure:
        main(args)
    assert failure.value.code == 2
    assert output.read_text() == '{"existing": 7.0}\n'
