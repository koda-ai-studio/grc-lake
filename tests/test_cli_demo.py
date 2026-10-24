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
