"""The local pipeline must remain usable without optional server dependencies."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_core_pipeline_without_site_packages(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GRC_LAKE_", "TRUSTOPS_"))}
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-S", str(ROOT / "tools/smoke_core_package.py"), str(ROOT)],
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
