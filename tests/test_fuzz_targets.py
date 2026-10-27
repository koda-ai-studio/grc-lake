"""Replay the fuzz targets' seed corpora so their invariants run in every test pass.

The coverage-guided runs live in ClusterFuzzLite; this keeps the targets
importable, their seeds meaningful, and fixed crashes fixed without atheris.
"""

from __future__ import annotations

import importlib
import random
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FUZZ = ROOT / "fuzz"
TARGETS = sorted(path.stem for path in FUZZ.glob("fuzz_*.py"))


@pytest.mark.parametrize("target_name", TARGETS)
def test_fuzzer_replays_production_code_without_optional_dependencies(target_name):
    import os
    import subprocess

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, (ROOT / "src", FUZZ)))}
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys, importlib; from pathlib import Path; target = importlib.import_module(sys.argv[2]); "
            "[target.TestOneInput(p.read_bytes()) for p in Path(sys.argv[1]).iterdir()]; "
            "assert 'sqlalchemy' not in sys.modules",
            str(FUZZ / "corpus" / target_name),
            target_name,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_billing_and_fuzzer_share_the_same_signature_verifier():
    from security_lakehouse.commercial import billing, stripe_signature

    assert billing.verify_stripe_signature is stripe_signature.verify_stripe_signature
    assert billing.SIGNATURE_TOLERANCE_SECONDS == stripe_signature.SIGNATURE_TOLERANCE_SECONDS


@pytest.fixture
def target(request: pytest.FixtureRequest) -> Iterator[Callable[[bytes], None]]:
    sys.path.insert(0, str(FUZZ))
    try:
        yield importlib.import_module(request.param).TestOneInput
    finally:
        sys.path.remove(str(FUZZ))


def test_every_target_has_a_seed_corpus() -> None:
    assert TARGETS == ["fuzz_aibom_import", "fuzz_raw_evidence", "fuzz_strict_json", "fuzz_webhook_signatures"]
    for name in TARGETS:
        assert any((FUZZ / "corpus" / name).iterdir()), name


@pytest.mark.parametrize("target", TARGETS, indirect=True)
def test_seed_corpus_and_random_inputs_hold_invariants(target: Callable[[bytes], None]) -> None:
    name = target.__module__
    for seed in sorted((FUZZ / "corpus" / name).iterdir()):
        target(seed.read_bytes())
    rng = random.Random(name)
    for _ in range(300):
        target(rng.randbytes(rng.randrange(0, 256)))


@pytest.mark.parametrize(
    ("target", "data"),
    [
        # Stripe header "t=²,v1=00": str.isdigit() accepted, int() raised.
        ("fuzz_webhook_signatures", b"\x01\x00\x00\x00" + bytes([18]) + "t=²,v1=00".encode("utf-16-le")),
        # Receiver signature "é": hmac.compare_digest() raised TypeError.
        ("fuzz_webhook_signatures", b"\x00\x00\x00\x02" + "é".encode("utf-16-le")),
        (
            "fuzz_aibom_import",
            b'\x01{"bomFormat":"CycloneDX","specVersion":"1.6",'
            b'"components":[{"type":"library","name":"x","externalReferences":5}]}',
        ),
        (
            "fuzz_aibom_import",
            b'\x01{"@context":"spdx","@graph":[{"type":"software_Package","name":"p","spdxId":"spdx:a"},'
            b'{"type":"Relationship","relationshipType":["x"]}]}',
        ),
    ],
    indirect=["target"],
)
def test_fixed_crashes_stay_fixed(target: Callable[[bytes], None], data: bytes) -> None:
    target(data)


def test_clusterfuzzlite_builds_every_target_with_its_seed_corpus() -> None:
    project = yaml.safe_load((ROOT / ".clusterfuzzlite/project.yaml").read_text())
    assert project == {"language": "python"}
    dockerfile = (ROOT / ".clusterfuzzlite/Dockerfile").read_text()
    assert "FROM gcr.io/oss-fuzz-base/base-builder-python:v1@sha256:" in dockerfile
    build = (ROOT / ".clusterfuzzlite/build.sh").read_text()
    assert "compile_python_fuzzer" in build and "fuzz/fuzz_*.py" in build and "_seed_corpus.zip" in build


@pytest.mark.parametrize("selected", [None, *TARGETS, "unknown", "../fuzz_raw_evidence"])
def test_fuzzer_build_selection_keeps_target_corpora_and_rejects_unknowns(tmp_path, selected):
    import os
    import subprocess

    source = tmp_path / "src"
    fuzz = source / "grc-lake/fuzz"
    out = tmp_path / "out"
    out.mkdir()
    for name in TARGETS:
        corpus = fuzz / "corpus" / name
        corpus.mkdir(parents=True)
        (corpus / "seed").write_text("{}")
        (fuzz / f"{name}.py").write_text("")
    compiler = tmp_path / "compile_python_fuzzer"
    compiler.write_text('#!/bin/sh\nbasename "$1" .py >> "$OUT/compiled"\n')
    compiler.chmod(0o755)
    env = {**os.environ, "SRC": str(source), "OUT": str(out), "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]}
    env.pop("CFL_EXTRA_FUZZ_TARGET", None)
    if selected is not None:
        env["CFL_EXTRA_FUZZ_TARGET"] = selected
    result = subprocess.run(["bash", str(ROOT / ".clusterfuzzlite/build.sh")], env=env, capture_output=True)
    if selected is not None and selected not in TARGETS:
        assert result.returncode != 0
        assert not (out / "compiled").exists()
    else:
        assert result.returncode == 0, result.stderr
        expected = TARGETS if selected is None else [selected]
        assert (out / "compiled").read_text().splitlines() == expected
        assert sorted(p.name for p in out.glob("*_seed_corpus.zip")) == [f"{name}_seed_corpus.zip" for name in expected]


def test_pr_fuzz_matrix_preserves_every_target_budget_and_required_gate():
    import os
    import subprocess

    jobs = yaml.safe_load((ROOT / ".github/workflows/cflite_pr.yml").read_text())["jobs"]
    targets = jobs["targets"]
    assert targets["strategy"]["matrix"]["target"] == TARGETS
    assert targets["strategy"]["fail-fast"] is False
    steps = targets["steps"]
    build = next(s for s in steps if s.get("id") == "build")
    assert build["env"]["CFL_EXTRA_FUZZ_TARGET"] == "${{ matrix.target }}"
    assert build["with"]["keep-unaffected-fuzz-targets"] is True
    run = next(s for s in steps if s.get("id") == "run")
    assert run["with"]["fuzz-seconds"] >= 75
    assert run["with"]["fuzz-seconds"] * len(TARGETS) >= 300
    gate = jobs["fuzz"]
    assert gate["name"] == "Fuzz pull request (address)"
    assert gate["if"] == "always()" and gate["needs"] == "targets"
    step = gate["steps"][0]
    assert step["env"] == {"FUZZ_RESULT": "${{ needs.targets.result }}"}
    for result in ("success", "failure", "cancelled", "skipped"):
        completed = subprocess.run(["bash", "-c", step["run"]], env={**os.environ, "FUZZ_RESULT": result})
        assert (completed.returncode == 0) == (result == "success")


@pytest.mark.parametrize(("workflow", "mode"), [("cflite_pr.yml", "code-change"), ("cflite_batch.yml", "batch")])
def test_clusterfuzzlite_workflows_are_pinned_and_least_privilege(workflow: str, mode: str) -> None:
    text = (ROOT / ".github/workflows" / workflow).read_text()
    parsed = yaml.safe_load(text)
    assert parsed["permissions"] == "read-all"
    steps = [step for job in parsed["jobs"].values() for step in job["steps"]]
    uses = [step["uses"] for step in steps if "uses" in step]
    assert any(use.startswith("google/clusterfuzzlite/actions/build_fuzzers@") for use in uses)
    for use in uses:
        _, _, ref = use.partition("@")
        assert len(ref) == 40 and all(char in "0123456789abcdef" for char in ref), use
    run = next(step for step in steps if step.get("uses", "").startswith("google/clusterfuzzlite/actions/run_fuzzers"))
    assert run["with"]["language"] == "python" and run["with"]["mode"] == mode
    assert "storage-repo" not in run["with"]
    for job in parsed["jobs"].values():
        granted = job.get("permissions", {})
        assert set(granted) <= {"actions", "contents", "security-events"}
        assert all(granted[scope] == "read" for scope in granted if scope != "security-events")
        if "security-events" in granted:
            assert any("upload-sarif" in use for use in uses)
