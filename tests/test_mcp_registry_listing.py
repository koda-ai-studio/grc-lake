"""The MCP Registry entry launches the real MCP server and stays in step with the release."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from security_lakehouse import cli, mcp_server

ROOT = Path(__file__).resolve().parents[1]
SERVER_NAME = "io.github.koda-ai-studio/grc-lake"


def _server() -> dict:
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_grc_lake_mcp_subcommand_runs_the_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(mcp_server, "main", lambda: calls.append(True))

    assert cli.main(["mcp"]) == 0
    assert calls == [True]


def test_server_json_matches_the_package_release_and_registry_limits() -> None:
    server = _server()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

    assert server["name"] == SERVER_NAME
    assert len(server["description"]) <= 100
    assert server["version"] == version
    [package] = server["packages"]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == "grc-lake"
    assert package["version"] == version
    assert package["transport"] == {"type": "stdio"}
    assert package["runtimeHint"] == "uvx"
    assert [arg.get("value") for arg in package["runtimeArguments"]] == [f"grc-lake[mcp]=={version}"]
    assert [arg.get("value") for arg in package["packageArguments"]] == ["mcp"]


def test_pypi_readme_carries_the_registry_ownership_marker() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"<!-- mcp-name: {SERVER_NAME} -->" in readme
