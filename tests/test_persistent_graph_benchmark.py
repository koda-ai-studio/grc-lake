"""Large graph fixtures distinguish evidence records, scoped assets and findings."""

import pytest


def test_scale_fixture_has_independent_cardinalities_and_platform_scope():
    from tools.benchmark_persistent_graph import records

    from security_lakehouse.io import canonical_sha256

    a = list(records(12, assets=4, findings=7, tenant="a"))
    b = list(records(12, assets=4, findings=7, tenant="b"))
    assert len(a) == 12
    assert len({(r["tenant_id"], r["asset_id"]) for r in a}) == 4
    assert sum(r["status"] == "fail" for r in a) == 7
    assert {(r["tenant_id"], r["asset_id"]) for r in a} == {(r["tenant_id"], r["asset_id"]) for r in b}
    assert not ({canonical_sha256(r) for r in a} & {canonical_sha256(r) for r in b})


@pytest.mark.parametrize("count,assets,findings", [(0, 1, 0), (2, 3, 1), (2, 1, 3), (2, 0, 0)])
def test_scale_fixture_rejects_impossible_cardinality(count, assets, findings):
    from tools.benchmark_persistent_graph import records

    with pytest.raises(ValueError):
        list(records(count, assets=assets, findings=findings, tenant="a"))


def test_benchmark_script_runs_from_clean_process(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    receipt = tmp_path / "receipt.json"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/benchmark_persistent_graph.py",
            "--records",
            "10",
            "--assets",
            "4",
            "--findings",
            "7",
            "--repeats",
            "1",
            "--timeout",
            "45",
            "--out",
            str(receipt),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(receipt.read_text())["result"]["correctness_ok"]


@pytest.mark.parametrize("timeout", ["nan", "inf", "-1"])
def test_benchmark_requires_finite_deadline(monkeypatch, timeout):
    from tools.benchmark_persistent_graph import main

    monkeypatch.setattr("sys.argv", ["benchmark", "--timeout", timeout, "--out", "/unused"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2
