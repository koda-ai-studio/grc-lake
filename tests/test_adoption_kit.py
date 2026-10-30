"""Contracts for the adoption kit: compose quickstart, CI gate docs, community files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from repo_files import repo_files

ROOT = Path(__file__).resolve().parents[1]
ACTION = yaml.safe_load((ROOT / ".github" / "actions" / "posture-gate" / "action.yml").read_text(encoding="utf-8"))
EXAMPLES = sorted((ROOT / "examples" / "github-actions").glob("*.yml"))


def _compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))


def _command(service: dict[str, Any]) -> str:
    command = service.get("command", "")
    return " ".join(command) if isinstance(command, list) else str(command)


# --- compose quickstart -------------------------------------------------------


@pytest.mark.parametrize("doc", ["docs/SHAREABLE_POC_HOSTING.md", "deploy/README.md"])
def test_current_hosting_guides_use_the_chart_image_repository(doc: str) -> None:
    chart = yaml.safe_load((ROOT / "deploy/helm/grc-lake/values.yaml").read_text())
    references = re.findall(r"ghcr\.io/[\w-]+/grc-lake\b", (ROOT / doc).read_text())
    assert references, f"{doc} must identify the published image"
    assert set(references) == {chart["image"]["repository"]}, (doc, references)


def test_tutorial_installs_the_same_published_release_for_pip_and_compose():
    tutorial = (ROOT / "docs/TUTORIAL_5_MIN.md").read_text()
    readme = (ROOT / "README.md").read_text()
    versions = re.findall(r"git clone --branch v([\d.]+)", tutorial)
    versions += re.findall(r"grc-lake\[server\]==([\d.]+)", tutorial)
    versions += re.findall(r"published \*\*v([\d.]+)\*\*", tutorial)
    assert len(versions) == 3
    assert set(versions) == set(re.findall(r"git clone --branch v([\d.]+)", readme))


def test_demo_service_is_localhost_only_seeds_the_golden_fixture_and_says_auth_is_off() -> None:
    demo = _compose()["services"]["grc-lake"]
    command = _command(demo)

    assert "profiles" not in demo, "the demo must start with a bare `docker compose up`"
    assert demo["ports"] and all(str(port).startswith("127.0.0.1:") for port in demo["ports"])
    assert "fixtures load --company golden" in command
    assert "--allow-insecure-no-auth" in command
    assert "NO AUTHENTICATION" in command
    assert any(str(volume).endswith(":/lake") for volume in demo["volumes"])


@pytest.mark.parametrize("marker", [None, ".grc-lake-demo-seeded", ".trustops-demo-seeded"])
def test_demo_bootstrap_runs_without_shell_and_preserves_seed_markers(tmp_path, monkeypatch, marker) -> None:
    import os
    import subprocess

    command = _compose()["services"]["grc-lake"]["command"]
    assert command[:2] == ["python", "-c"]
    if marker:
        (tmp_path / marker).touch()
    loads = []
    servers = []
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: loads.append((args, kwargs)))
    monkeypatch.setattr(os, "execvp", lambda executable, args: servers.append((executable, args)))
    exec(command[2].replace("/lake", str(tmp_path)), {})
    assert len(loads) == (0 if marker else 1)
    if loads:
        assert loads[0][0][:5] == ["grc-lake", "fixtures", "load", "--company", "golden"]
        assert loads[0][1] == {"check": True}
        assert (tmp_path / ".grc-lake-demo-seeded").exists()
    assert len(servers) == 1 and servers[0][0] == "grc-lake"
    assert "--allow-insecure-no-auth" in servers[0][1]


def test_demo_bootstrap_does_not_mark_or_serve_a_failed_seed(tmp_path, monkeypatch) -> None:
    import os
    import subprocess

    command = _compose()["services"]["grc-lake"]["command"]
    assert command[:2] == ["python", "-c"]

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(subprocess, "run", fail)
    monkeypatch.setattr(os, "execvp", lambda *_: pytest.fail("must not serve after failed seeding"))
    with pytest.raises(subprocess.CalledProcessError):
        exec(command[2].replace("/lake", str(tmp_path)), {})
    assert not (tmp_path / ".grc-lake-demo-seeded").exists()


def test_server_profile_requires_auth_secrets_and_ships_no_demo_data() -> None:
    compose = _compose()
    server = compose["services"]["grc-lake-server"]
    command = _command(server)

    assert server["profiles"] == ["server"]
    assert "--allow-insecure-no-auth" not in command
    assert "fixtures" not in command
    assert server["environment"]["GRC_LAKE_ENV"] == "production"
    assert "GRC_LAKE_ALLOW_INSECURE_NO_AUTH" not in server["environment"]
    assert server["env_file"] == ["grc-lake.env"]
    demo_volumes = set(compose["services"]["grc-lake"]["volumes"])
    assert not demo_volumes & set(server["volumes"]), "real lake must never share the demo volume"


def test_server_env_example_lists_the_signing_key_without_a_value() -> None:
    example = (ROOT / "deploy" / "compose" / "grc-lake.env.example").read_text(encoding="utf-8")
    assert re.search(r"^GRC_LAKE_COOKIE_SIGNING_KEY=$", example, re.MULTILINE)
    assert "ALLOW_INSECURE" not in example
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^/?trustops\.env$", gitignore, re.MULTILINE)


# --- posture gate CI docs and examples ---------------------------------------


def _gate_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        step
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "posture-gate" in str(step.get("uses", ""))
    ]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_workflows_only_use_declared_action_inputs_and_outputs(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    steps = _gate_steps(workflow)
    assert steps, f"{path.name} never calls the posture gate"
    required = {name for name, spec in ACTION["inputs"].items() if spec.get("required")}
    for step in steps:
        assert set(step["with"]) <= set(ACTION["inputs"]), set(step["with"]) - set(ACTION["inputs"])
        assert required <= set(step["with"])
    gate_ids = {step["id"] for step in steps if "id" in step}
    for step_id, output in re.findall(r"steps\.([\w-]+)\.outputs\.([\w-]+)", text):
        if step_id in gate_ids:
            assert output in ACTION["outputs"], output


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_workflows_pin_third_party_actions_to_a_commit(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(?:-\s+)?uses:\s*(\S+)", line)
        if not match or "posture-gate" in match.group(1):
            continue
        assert re.search(r"@[0-9a-f]{40} # v\d+(\.\d+){2}$", line), line


def test_ci_gate_doc_covers_every_action_input_and_output() -> None:
    doc = (ROOT / "docs" / "CI_GATE.md").read_text(encoding="utf-8")
    for name in [*ACTION["inputs"], *ACTION["outputs"]]:
        assert f"`{name}`" in doc, name
    for block in re.findall(r"```yaml\n(.*?)```", doc, re.DOTALL):
        parsed = yaml.safe_load(block)
        workflows = [parsed] if isinstance(parsed, dict) and "jobs" in parsed else []
        for workflow in workflows:
            for step in _gate_steps(workflow):
                assert set(step["with"]) <= set(ACTION["inputs"])


# --- community files ----------------------------------------------------------


def test_community_health_files_exist() -> None:
    for name in ("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md"):
        assert (ROOT / name).is_file(), name
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "security/advisories/new" in security
    assert "Contributor Covenant" in (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")


def test_issue_forms_are_valid_and_security_reports_go_private() -> None:
    template_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
    forms = sorted(p for p in template_dir.glob("*.yml") if p.name != "config.yml")
    assert len(forms) >= 4
    for form in forms:
        data = yaml.safe_load(form.read_text(encoding="utf-8"))
        assert {"name", "description", "body"} <= set(data), form.name
        ids = [item["id"] for item in data["body"] if "id" in item]
        assert len(ids) == len(set(ids)), form.name
        assert any(item.get("validations", {}).get("required") for item in data["body"]), form.name
    config = yaml.safe_load((template_dir / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    assert any("security/advisories/new" in link["url"] for link in config["contact_links"])


def _make_targets() -> set[str]:
    return set(re.findall(r"^([A-Za-z0-9_-]+):", (ROOT / "Makefile").read_text(encoding="utf-8"), re.MULTILINE))


@pytest.mark.parametrize("doc", ["CONTRIBUTING.md", "docs/CI_GATE.md", "docs/TUTORIAL_5_MIN.md"])
def test_documented_make_targets_exist(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    documented = set(re.findall(r"(?:`|^)make ((?:[a-z][\w-]*)(?: [a-z][\w-]*)*)", text, re.MULTILINE))
    assert documented or doc != "CONTRIBUTING.md"
    targets = {target for group in documented for target in group.split()}
    missing = targets - _make_targets()
    assert not missing, missing


# --- markdown links -----------------------------------------------------------


def _markdown_files() -> list[Path]:
    return [p for p in repo_files() if p.suffix == ".md"]


def test_relative_markdown_links_resolve() -> None:
    link = re.compile(r"\]\(([^)\s]+)\)|(?:href|src|srcset)=\"([^\"]+)\"")
    broken = []
    for md in _markdown_files():
        text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8", errors="ignore"), flags=re.DOTALL)
        for match in link.finditer(text):
            target = (match.group(1) or match.group(2)).split("#", 1)[0]
            if not target or re.match(r"^(https?:|mailto:|data:)", target):
                continue
            if not (md.parent / target).exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    assert not broken, broken


def test_built_image_is_exercised_by_compose_before_ci_passes() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["docker-build"]
    steps = job["steps"]
    runtime = next((step for step in steps if "tools/compose_smoke.py" in step.get("run", "")), None)
    assert runtime is not None, "the built PR image must pass the documented Compose startup and restart checks"
    assert "--image grc-lake:ci" in runtime["run"]
    assert not runtime.get("continue-on-error", False)
    assert job["timeout-minutes"] <= 30
    cleanup = next(step for step in steps if "down --volumes" in step.get("run", ""))
    assert cleanup["if"] == "always()"
    assert any(step.get("if") == "always()" and step.get("with", {}).get("name") == "compose-smoke" for step in steps)
