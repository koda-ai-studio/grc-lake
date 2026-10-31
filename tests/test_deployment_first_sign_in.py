"""The self-hosted guide must show how to create the first tenant, user and key."""

from __future__ import annotations

import re
from pathlib import Path

from security_lakehouse import cli

ROOT = Path(__file__).resolve().parents[1]


def _section() -> str:
    text = (ROOT / "docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "### First sign-in without an identity provider" in text
    return text.split("### First sign-in without an identity provider", 1)[1].split("\n### ", 1)[0]


def test_first_sign_in_runbook_uses_real_cli_commands() -> None:
    section = _section()
    commands = re.findall(r"^grc-lake (auth \S+|platform \S+)(.*)$", section, re.MULTILINE)
    names = [name for name, _ in commands]
    assert names[:3] == ["auth create-tenant", "auth create-user", "auth issue-key"]
    parser = cli._parser()
    for name, rest in commands:
        parser.parse_args([*name.split(), *rest.replace("\\", "").split()])


def test_first_sign_in_runbook_explains_where_the_key_lands() -> None:
    section = _section()
    assert "server/credentials/" in section
    assert ".token" in section
    assert "session-from-key" in section


def test_examples_use_current_environment_names() -> None:
    legacy = [
        f"{path.relative_to(ROOT)}:{line_no}"
        for path in sorted((ROOT / "deploy" / "examples").glob("*.yaml"))
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "TRUSTOPS_" in line
    ]
    assert legacy == [], legacy
