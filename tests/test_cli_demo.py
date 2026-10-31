"""`grc-lake demo` serves a throwaway golden lake on loopback only."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from security_lakehouse import cli


def _args(*extra: str) -> Any:
    return cli._parser().parse_args(["demo", "--no-browser", *extra])


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_demo_loads_golden_and_serves_unauthenticated_on_loopback_then_cleans_up(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("uvicorn")
    from security_lakehouse import server_app

    seen: dict[str, Any] = {}

    def build(lake: Any, *, require_auth: bool) -> Any:
        seen["lake"] = Path(lake)
        seen["require_auth"] = require_auth
        seen["populated"] = any(Path(lake).iterdir())
        return SimpleNamespace()

    def run(_app: Any, *, host: str, port: int, log_level: str) -> None:
        seen["bind"] = (host, port)

    port = _free_port()
    monkeypatch.setattr(server_app, "create_app", build)
    monkeypatch.setattr("uvicorn.run", run)

    assert cli._demo(_args("--port", str(port))) == 0

    assert seen["require_auth"] is False
    assert seen["bind"] == ("127.0.0.1", port)
    assert seen["populated"]
    assert not seen["lake"].exists()
    assert f"http://127.0.0.1:{port}/console/dashboard/" in capsys.readouterr().out


def test_demo_falls_back_to_local_mode_without_server_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from security_lakehouse import server

    served: list[tuple[str, int]] = []
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    monkeypatch.setattr(cli, "_load_fixture", lambda *a, **k: {})
    monkeypatch.setattr(server, "serve", lambda _lake, *, host, port: served.append((host, port)))

    port = _free_port()
    assert cli._demo(_args("--port", str(port))) == 0

    assert served == [("127.0.0.1", port)]
    assert "local mode" in capsys.readouterr().out


def test_demo_refuses_a_busy_port_before_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[Any] = []
    monkeypatch.setattr(cli, "_load_fixture", lambda *a, **k: loaded.append(a))

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        with pytest.raises(SystemExit, match="already in use"):
            cli._demo(_args("--port", str(port)))

    assert loaded == []


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM is POSIX process termination")
def test_demo_deletes_its_temporary_lake_on_sigterm(tmp_path: Path) -> None:
    import os
    import signal
    import subprocess
    import time

    scratch = tmp_path / "tmp"
    scratch.mkdir()
    port = _free_port()
    script = "import sys; from security_lakehouse.cli import main; raise SystemExit(main(sys.argv[1:]))"
    process = subprocess.Popen(
        [sys.executable, "-c", script, "demo", "--no-browser", "--port", str(port)],
        env={**os.environ, "TMPDIR": str(scratch)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert process.poll() is None, "demo exited before listening"
            with socket.socket() as probe:
                probe.settimeout(0.5)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.2)
        else:
            pytest.fail("demo never listened")
        lakes = list(scratch.glob("grc-lake-demo-*"))
        assert len(lakes) == 1 and any(lakes[0].iterdir())

        process.send_signal(signal.SIGTERM)
        process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    assert not lakes[0].exists()


def test_ai_demo_opens_inventory_with_real_fixture_assets_and_cleans_up(monkeypatch, capsys):
    pytest.importorskip("uvicorn")
    from security_lakehouse import api_v1, server_app
    from security_lakehouse.io import read_json

    seen = {}

    def build(lake, *, require_auth):
        seen["lake"] = Path(lake)
        assert require_auth is False
        status, body = api_v1.handle_get("/api/v1/platform/ai-governance/inventory", {}, Path(lake))
        assert status == 200
        seen["inventory"] = body["data"]
        seen["assessment"] = read_json(Path(lake) / "gold/ccf_assessment.json")
        return SimpleNamespace()

    port = _free_port()
    monkeypatch.setattr(server_app, "create_app", build)
    monkeypatch.setattr("uvicorn.run", lambda _app, **kwargs: seen.update(bind=kwargs))
    monkeypatch.setattr(cli, "_open_when_listening", lambda host, port, url: seen.update(url=url))
    args = cli._parser().parse_args(["demo", "--company", "ai_lab", "--port", str(port)])
    assert cli._demo(args) == 0
    assert seen["url"] == f"http://127.0.0.1:{port}/console/ai-governance/"
    assert seen["bind"]["host"] == "127.0.0.1"
    assert len(seen["inventory"]) == 3
    assert {row["asset_type"] for row in seen["inventory"]} == {"model", "agent"}
    assert seen["assessment"]["population_completeness"] == "not_established"
    assert not seen["lake"].exists()
    output = capsys.readouterr().out
    assert "synthetic ai_lab company" in output
    assert "Start with the discovered models and agents" in output


def test_demo_company_is_an_allowlisted_fixture_not_a_file_path():
    with pytest.raises(SystemExit):
        _args("--company", "../../private")


def test_demo_keeps_the_lake_when_a_directory_is_given(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The README's first task continues in the CLI, so the demo lake must be keepable."""
    pytest.importorskip("uvicorn")
    from security_lakehouse import server_app

    seen: dict[str, Any] = {}
    monkeypatch.setattr(server_app, "create_app", lambda lake, *, require_auth: seen.update(lake=Path(lake)))
    monkeypatch.setattr("uvicorn.run", lambda _app, **kwargs: None)
    kept = tmp_path / "lake"

    assert cli._demo(_args("--port", str(_free_port()), "--lake", str(kept))) == 0

    assert seen["lake"] == kept.resolve()
    assert (kept / "gold" / "ccf_assessment.json").exists()
    out = capsys.readouterr().out
    assert f"lake kept at {kept.resolve()}" in out
    assert "deleted on exit" not in out


def test_demo_refuses_a_populated_lake_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loaded: list[Any] = []
    monkeypatch.setattr(cli, "_load_fixture", lambda *a, **k: loaded.append(a))
    (tmp_path / "existing.txt").write_text("keep me")

    with pytest.raises(SystemExit, match="empty or new directory"):
        cli._demo(_args("--port", str(_free_port()), "--lake", str(tmp_path)))

    assert loaded == []
    assert (tmp_path / "existing.txt").read_text() == "keep me"
