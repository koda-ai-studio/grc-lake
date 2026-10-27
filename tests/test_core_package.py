"""The local pipeline must remain usable without optional server dependencies."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_core_pipeline_without_site_packages(tmp_path):
    # Source tests isolate the HTTP serving contract; wheel-smoke exercises the
    # actual Next.js bundle with this same probe on three Python versions.
    dist = tmp_path / "web-dist"
    (dist / "dashboard").mkdir(parents=True)
    for entry in (dist / "index.html", dist / "dashboard/index.html"):
        entry.write_text("<!doctype html><title>Core package fixture</title>")
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GRC_LAKE_", "TRUSTOPS_"))}
    env["PYTHONPATH"] = os.pathsep.join(str(ROOT / directory) for directory in ("src", "tools"))
    probe = (
        "import sys; from pathlib import Path; from security_lakehouse import web; "
        "web.web_dist_dir = lambda: Path(sys.argv[2]); "
        "from smoke_core_package import main; main()"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            probe,
            str(ROOT),
            str(dist),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "core_package": "ok",
        "fixtures": "ok",
        "replay": "ok",
        "integrity": "ok",
        "snapshots": "ok",
        "console": "ok",
    }
