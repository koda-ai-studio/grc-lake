"""A successful fixture load tells the user how to inspect the resulting lake."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from security_lakehouse.cli import main


def test_golden_fixture_load_emits_working_next_steps(tmp_path: Path, capsys) -> None:
    lake = tmp_path / "lake with spaces"

    assert main(["fixtures", "load", "--company", "golden", "--out", str(lake), "--no-demo-records"]) == 0

    output = json.loads(capsys.readouterr().out)
    status_step, walkthrough_step = output["next_steps"]
    command = shlex.split(status_step["command"])
    assert status_step["action"] == "review_posture"
    assert command == ["grc-lake", "assessment", "status", "--lake", str(lake), "--format", "summary"]
    assert walkthrough_step == {
        "action": "read_walkthrough",
        "label": "Learn how technical tests, framework results, and human review differ.",
        "path": "docs/AUDITOR_WALKTHROUGH.md",
    }

    assert main(command[1:]) == 0
    summary = capsys.readouterr().out
    assert "Posture" in summary
    assert "Framework" in summary
