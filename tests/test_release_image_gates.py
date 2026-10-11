"""A release cannot publish Python before both image architectures qualify."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _jobs():
    return yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]


def _ancestors(jobs, name):
    needs = jobs[name].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    return set(needs).union(*(_ancestors(jobs, parent) for parent in needs))


def test_python_publication_waits_for_container_qualification():
    jobs = _jobs()
    assert "image" in _ancestors(jobs, "pypi"), "PyPI can publish before the image gate fails"


@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
def test_each_published_architecture_is_loaded_checked_and_scanned_first(platform):
    steps = _jobs()["image"]["steps"]
    publish_index = next(i for i, step in enumerate(steps) if step.get("id") == "push")
    publish = steps[publish_index]
    assert platform in publish["with"]["platforms"].split(",")
    builds = [
        (i, step)
        for i, step in enumerate(steps[:publish_index])
        if step.get("uses", "").startswith("docker/build-push-action@")
        and step.get("with", {}).get("load") is True
        and step["with"].get("platforms") == platform
    ]
    assert len(builds) == 1, f"{platform} has no explicit loaded preflight build"
    build_index, build = builds[0]
    image = build["with"]["tags"]
    preflight = steps[build_index + 1 : publish_index]
    assert any("check_image_dependencies.sh " + image in step.get("run", "") for step in preflight)
    assert any("authenticated_smoke.py" in step.get("run", "") and image in step["run"] for step in preflight), (
        f"{platform} has no authenticated runtime qualification"
    )
    scans = [
        step
        for step in preflight
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
        and step.get("with", {}).get("image-ref") == image
    ]
    assert any(
        scan["with"].get("exit-code") == "1"
        and {"MEDIUM", "HIGH", "CRITICAL"} <= set(scan["with"].get("severity", "").split(","))
        and not scan.get("continue-on-error")
        for scan in scans
    ), f"{platform} is not release-gated"


def test_docker_console_builder_uses_the_ci_node_major():
    import re

    dockerfile = (ROOT / "Dockerfile").read_text()
    major = re.search(r"FROM --platform=\$BUILDPLATFORM node:(\d+)-slim@sha256:", dockerfile).group(1)
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for steps in (ci["web"]["steps"], _jobs()["build"]["steps"]):
        setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-node@"))
        assert str(setup["with"]["node-version"]) == major, "Docker builds a different Node major than CI qualifies"


@pytest.mark.parametrize(
    ("runs", "allowed"),
    [
        ([(2, "push", "main", "completed", "failure"), (1, "push", "main", "completed", "success")], False),
        ([(2, "push", "main", "in_progress", None), (1, "push", "main", "completed", "success")], False),
        ([(2, "pull_request", "feature", "completed", "success")], False),
        ([(2, "push", "main", "completed", "success"), (1, "push", "main", "completed", "failure")], True),
        ([], False),
    ],
)
def test_tag_gate_requires_latest_successful_main_push(tmp_path, runs, allowed):
    import json
    import os
    import subprocess

    fixture = tmp_path / "runs.json"
    fixture.write_text(
        json.dumps(
            {
                "workflow_runs": [
                    dict(run_number=n, event=event, head_branch=branch, status=status, conclusion=conclusion)
                    for n, event, branch, status, conclusion in runs
                ]
            }
        )
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Exercise the actual release shell, replacing only GitHub/Git/network waits.
    for name, script in {
        "git": "#!/bin/sh\nexit 0\n",
        "gh": '#!/bin/sh\nexec jq "$4" "$CI_FIXTURE"\n',
        "sleep": "#!/bin/sh\nexit 23\n",
    }.items():
        path = bindir / name
        path.write_text(script)
        path.chmod(0o700)
    step = next(step for step in _jobs()["verify-tested-commit"]["steps"] if "run" in step)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        env={
            **os.environ,
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "CI_FIXTURE": str(fixture),
            "REPO": "example/repository",
            "SHA": "candidate",
            "GITHUB_REF_NAME": "v0.3.3",
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert (result.returncode == 0) == allowed, result.stdout + result.stderr
