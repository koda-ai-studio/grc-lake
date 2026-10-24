"""Exercise the base package with no optional dependencies, outside the checkout."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    import security_lakehouse
    from security_lakehouse.catalog import _data_root
    from security_lakehouse.cli import main as cli

    expected = Path(sys.argv[1]).resolve()
    assert Path(security_lakehouse.__file__).resolve().is_relative_to(expected)
    assert _data_root().resolve().is_relative_to(expected)
    assert importlib.util.find_spec("sqlalchemy") is None, "core smoke must run without server dependencies"

    def run(*arguments: str, parse_json: bool = True) -> dict:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli(list(arguments))
        assert status == 0, (arguments, status, output.getvalue())
        return json.loads(output.getvalue()) if parse_json else {}

    with tempfile.TemporaryDirectory() as directory:
        lake = str(Path(directory) / "lake")
        loaded = run("fixtures", "load", "--company", "golden", "--out", lake, "--rebase-times")
        assert loaded["raw_count"] == loaded["silver_count"] > 0
        assert loaded["demo_records"]["seeded"] is False
        assert not (Path(lake) / "server/app.db").exists()
        before = run("pipeline", "verify-integrity", "--lake", lake)
        assert before["ok"] is True
        replay = run(
            "pipeline", "run", "--raw", str(Path(lake) / "_fixture_rebased/security_events.jsonl"), "--out", lake
        )
        after = run("pipeline", "verify-integrity", "--lake", lake)
        assert replay["silver_count"] == loaded["silver_count"]
        assert after["ok"] is True
        assert before["evidence_set_sha256"] == after["evidence_set_sha256"]
        run("assessment", "snapshot", "--lake", lake, "--reason", "Base installation smoke", parse_json=False)
        assert run("assessment", "verify-snapshots", "--lake", lake)["ok"] is True
        _smoke_local_console(lake)
    print(
        json.dumps(
            {
                "core_package": "ok",
                "fixtures": "ok",
                "replay": "ok",
                "integrity": "ok",
                "snapshots": "ok",
                "console": "ok",
            }
        )
    )


def _smoke_local_console(lake: str) -> None:
    from security_lakehouse.server import serve

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    threading.Thread(target=serve, args=(lake,), kwargs={"port": port}, daemon=True).start()
    for path in ("/console/dashboard/", "/api/v1/controls", "/api/v1/frameworks", "/api/v1/graph"):
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                    assert response.status == 200, (path, response.status)
                break
            except urllib.error.URLError as exc:
                if not isinstance(exc.reason, ConnectionRefusedError):
                    raise
                time.sleep(0.1)
        else:
            raise AssertionError(f"local console did not answer {path}")


if __name__ == "__main__":
    main()
