"""A release cannot publish Python before both image architectures qualify."""

import shlex
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
    commands = [shlex.split(step.get("run", "")) for step in preflight if not step.get("continue-on-error")]
    assert any("tools/check_image_dependencies.sh" in args and image in args for args in commands)
    assert any("tools/authenticated_smoke.py" in args and image in args and platform in args for args in commands), (
        f"{platform} has no authenticated runtime qualification"
    )
    scans = [
        step
        for step in preflight
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
        and step.get("with", {}).get("image-ref") == image
    ]
    reports = [scan["with"]["output"] for scan in scans if scan["with"].get("format") == "json"]
    assert len(reports) == 1
    assert any("tools/check_image_vulnerabilities.py" in args and reports[0] in args for args in commands), (
        f"{platform} is not gated against unfixed high vulnerabilities"
    )


def test_docker_console_builder_uses_the_ci_node_major():
    import re

    dockerfile = (ROOT / "Dockerfile").read_text()
    major = re.search(r"FROM --platform=\$BUILDPLATFORM node:(\d+)-slim@sha256:", dockerfile).group(1)
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for steps in (ci["web"]["steps"], _jobs()["build"]["steps"]):
        setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-node@"))
        assert str(setup["with"]["node-version"]) == major, "Docker builds a different Node major than CI qualifies"


@pytest.mark.parametrize(
    ("workflow", "job", "image", "platform"),
    [
        ("ci.yml", "docker-build", "grc-lake:ci", "linux/amd64"),
        ("release.yml", "image", "grc-lake:scan", "linux/amd64"),
        ("release.yml", "image", "grc-lake:scan-arm64", "linux/arm64"),
    ],
)
def test_unfiltered_image_evidence_is_retained_even_when_policy_scan_fails(workflow, job, image, platform):
    steps = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"][job]["steps"]
    scans = [
        (i, step)
        for i, step in enumerate(steps)
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
        and step.get("with", {}).get("image-ref") == image
    ]
    full = [(i, step) for i, step in scans if step["with"].get("format") == "json"]
    assert len(full) == 1, f"{image} lacks an unfiltered vulnerability report"
    report_index, report = full[0]
    options = report["with"]
    assert options["ignore-unfixed"] is False
    assert set(options["severity"].split(",")) == {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert options["scanners"] == "vuln"
    assert options["exit-code"] == "0", "Unfixed findings are evidence, not a replacement release policy"
    assert not report.get("continue-on-error"), "Scanner errors must not look like complete evidence"
    assert report.get("env", {}).get("TRIVY_PLATFORM") == platform
    gate_index, gate = next(
        (i, step)
        for i, step in enumerate(steps)
        if "tools/check_image_vulnerabilities.py" in shlex.split(step.get("run", ""))
        and options["output"] in shlex.split(step.get("run", ""))
    )
    assert report_index < gate_index, "A failing policy gate would prevent evidence collection"
    assert not gate.get("continue-on-error")
    upload_index, upload = next(
        (i, step)
        for i, step in enumerate(steps)
        if step.get("uses", "").startswith("actions/upload-artifact@")
        and options["output"] in step.get("with", {}).get("path", "").splitlines()
    )
    assert upload_index > gate_index
    assert upload["if"] == "always()", "Failed gates must retain the full report"
    assert upload["with"]["retention-days"] >= 14


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
