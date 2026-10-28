"""Public summaries preserve qualification scope and distinguish adapter counts."""

import json
from pathlib import Path

from tools.render_readme_header import render_readme_glance

ROOT = Path(__file__).resolve().parents[1]


def test_readme_counts_executable_adapters_and_configuration_boundaries_separately():
    catalog = json.loads((ROOT / "connectors/catalog.json").read_text())["connectors"]
    executable = [row for row in catalog if row.get("is_implemented")]
    preview = sum(row.get("release_stage") == "preview" for row in executable)
    summary = render_readme_glance()
    assert f"{len(executable)} executable adapters" in summary
    assert f"{len(executable) - preview} implemented, {preview} preview" in summary
    assert f"{len(catalog) - len(executable)} configuration boundaries" in summary


def test_current_databricks_summary_links_the_populated_multichunk_scope():
    current = (ROOT / "docs/CURRENT_STATE.md").read_text()
    assert "2026-10-25-databricks.md#databricks-multichunk" in current
    assert "77,036" in current and "75,000 synthetic" in current
    assert "Databricks remains Preview" in current
    assert "eight synthetic rows and an empty audit window" not in current


def test_readme_safeguard_count_uses_thousands_separators():
    count = len(json.loads((ROOT / "controls/safeguards.json").read_text())["safeguards"])
    assert f"linked through {count:,} safeguards" in render_readme_glance()
