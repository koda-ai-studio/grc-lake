"""Chart publication is gated, reproducible, and retains signed provenance."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_chart_is_qualified_before_python_publication_and_included_in_release():
    jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]
    chart = jobs["chart"]
    assert set(chart["needs"]) == {"verify-version", "image"}
    assert "chart" in jobs["pypi"]["needs"]
    assert "chart" in jobs["github-release"]["needs"]
    steps = chart["steps"]
    assert any(s.get("uses", "").startswith("docker/login-action@") for s in steps)
    scripts = "\n".join(s.get("run", "") for s in steps)
    assert "helm lint" in scripts and "helm template" in scripts and "helm package" in scripts
    push = next(s for s in steps if s.get("id") == "push")
    assert push["if"] == "env.PUBLISH == 'true'"
    assert push["shell"] == "bash"
    assert "oci://ghcr.io/${OWNER}/charts" in push["run"]
    assert "helm pull" in push["run"] and "cmp " in push["run"]
    assert "github.ref_type == 'tag'" in chart["env"]["PUBLISH"]
    attestations = [s for s in steps if s.get("uses", "").startswith("actions/attest@")]
    assert any(s["with"].get("subject-path") == "charts/*.tgz" for s in attestations)
    assert any(s["with"].get("push-to-registry") is True for s in attestations)
    release = next(s for s in jobs["github-release"]["steps"] if s.get("uses", "").startswith("softprops/"))
    assert "charts/*.tgz" in release["with"]["files"].splitlines()
    assert "charts/chart-provenance.sigstore.json" in release["with"]["files"].splitlines()


def test_chart_metadata_uses_current_repository_and_explains_verification():
    chart = yaml.safe_load((ROOT / "deploy/helm/grc-lake/Chart.yaml").read_text())
    assert chart["home"] == "https://github.com/koda-ai-studio/grc-lake"
    readme = (ROOT / "deploy/helm/grc-lake/README.md").read_text()
    assert "oci://ghcr.io/koda-ai-studio/charts/grc-lake" in readme
    assert "gh attestation verify" in readme
    assert "Artifact Hub" in readme


@pytest.mark.parametrize("mode", ["ok", "wrong-bytes", "bad-digest", "failed-push"])
def test_chart_push_rejects_failed_publication_or_changed_download(tmp_path, mode):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    step = next(s for s in workflow["jobs"]["chart"]["steps"] if s.get("id") == "push")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    helm = bindir / "helm"
    helm.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = push ]; then\n'
        '  if [ "$MODE" = bad-digest ]; then echo "Digest: invalid"; else\n'
        '    echo "Digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; fi\n'
        '  if [ "$MODE" = failed-push ]; then exit 1; fi\n'
        'elif [ "$1" = pull ]; then\n'
        '  if [ "$MODE" = wrong-bytes ]; then printf changed > "$RUNNER_TEMP/pulled-chart/grc-lake-1.2.3.tgz";\n'
        '  else cp charts/grc-lake-1.2.3.tgz "$RUNNER_TEMP/pulled-chart/"; fi\n'
        "else exit 2; fi\n"
    )
    helm.chmod(0o755)
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts/grc-lake-1.2.3.tgz").write_bytes(b"synthetic chart bytes")
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
            "MODE": mode,
            "OWNER": "fixture-owner",
            "VERSION": "1.2.3",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        },
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) == (mode == "ok"), result.stderr
