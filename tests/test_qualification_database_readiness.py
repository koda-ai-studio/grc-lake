"""Recovery must wait past the image's temporary socket-only bootstrap server."""

from types import SimpleNamespace

import pytest
from tools import qualify_distributed as qualification


def test_restore_waits_for_final_tcp_server(monkeypatch):
    checks = []
    sleeps = []

    def run(command, **kwargs):
        checks.append(command)
        # The bootstrap server already accepts Unix-socket connections.
        # TCP becomes available only after initialization and its restart.
        tcp = "-h" in command and command[command.index("-h") + 1] == "127.0.0.1"
        return SimpleNamespace(returncode=0 if not tcp or len(checks) == 3 else 1)

    monkeypatch.setattr(qualification.subprocess, "run", run)
    monkeypatch.setattr(qualification.time, "sleep", sleeps.append)
    qualification.wait_for_restore_database(["docker", "compose"], {})
    assert len(checks) == 3
    assert sleeps == [1, 1]


def test_restore_readiness_has_a_deadline(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(qualification.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(qualification.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(qualification.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match="readiness deadline exceeded"):
        qualification.wait_for_restore_database(["docker", "compose"], {})
    assert now[0] == 90


@pytest.mark.parametrize("project", ["grc-qualification-0123456789ab", "unrelated-project"])
def test_cleanup_uses_short_grace_only_for_its_own_disposable_project(monkeypatch, tmp_path, project):
    (tmp_path / "project-name.txt").write_text(project)
    commands = []
    monkeypatch.setattr(qualification.subprocess, "run", lambda command, **kwargs: commands.append(command))
    if project == "unrelated-project":
        with pytest.raises(ValueError, match="invalid qualification project"):
            qualification.cleanup(tmp_path)
        assert not commands
    else:
        qualification.cleanup(tmp_path)
        assert commands[0][-5:] == ["down", "--timeout", "1", "--volumes", "--remove-orphans"]
        assert commands[0][commands[0].index("--project-name") + 1] == project
