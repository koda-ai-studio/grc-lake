"""Contracts for the root GRC Lake Readiness action and its summary script."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION_FILE = ROOT / "action.yml"
SCRIPT = ROOT / ".github" / "actions" / "readiness" / "readiness-summary.sh"
GATE_SCRIPT = ROOT / ".github" / "actions" / "posture-gate" / "posture-gate.sh"
GATE_ACTION = yaml.safe_load((ROOT / ".github" / "actions" / "posture-gate" / "action.yml").read_text())
TOKEN = "ghs_example-token-never-printed"
MARKER = "<!-- grc-lake-readiness -->"


def _posture(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "synthetic_fixture": True,
        "evaluated_at": "2026-11-01T00:00:00Z",
        "collection_gaps": {"sources": ["okta"], "affected_control_ids": ["SOC2-CC6.1"]},
        "posture": {
            "score": 41.5,
            "state": "critical",
            "open_violation_count": 7,
            "critical_violation_count": 1,
            "failed_control_test_count": 2,
            "not_evaluated_control_count": 2,
            "stale_evidence_count": 3,
            "collection_gap_count": 1,
        },
        "frameworks": [
            {
                "framework": "SOC 2",
                "score": 50.0,
                "state": "attention_required",
                "control_count": 4,
                "passing_control_count": 2,
                "failing_control_count": 1,
                "not_evaluated_control_count": 0,
                "stale_control_count": 0,
                "collection_gap_control_count": 1,
            },
            {
                "framework": "ISO 27001:2022",
                "score": 100.0,
                "state": "ready",
                "control_count": 3,
                "passing_control_count": 3,
                "failing_control_count": 0,
                "not_evaluated_control_count": 0,
                "stale_control_count": 0,
                "collection_gap_control_count": 0,
            },
            {
                # A state that disagrees with its own counts must never read as ready.
                "framework": "Pipe | Program",
                "score": 100.0,
                "state": "ready",
                "control_count": 2,
                "passing_control_count": 2,
                "failing_control_count": 0,
                "not_evaluated_control_count": 2,
                "stale_control_count": 0,
                "collection_gap_control_count": 0,
            },
        ],
    }
    data.update(overrides)
    return {"data": data}


class _Stub:
    """A loopback HTTP stub that records every request it receives."""

    def __init__(self, routes: dict[tuple[str, str], tuple[int, Any]]) -> None:
        self.routes = routes
        self.requests: list[dict[str, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else ""
                stub.requests.append(
                    {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
                )
                path = self.path.split("?", 1)[0]
                status, payload = stub.routes.get((self.command, path), (404, {"errors": [{"detail": "not found"}]}))
                if callable(payload):
                    payload = payload(self.path)
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = do_PATCH = _handle

            def log_message(self, *args: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        host, port = self.server.server_address[:2]
        self.url = f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stubs() -> Iterator[list[_Stub]]:
    created: list[_Stub] = []
    yield created
    for stub in created:
        stub.close()


def _lake(stubs: list[_Stub], posture: dict[str, Any] | None = None) -> _Stub:
    stub = _Stub(
        {
            ("GET", "/api/v1/posture/current"): (200, posture or _posture()),
            ("GET", "/api/v1/control-tests"): (200, {"data": [{"control_id": "SOC2-CC6.1"}]}),
        }
    )
    stubs.append(stub)
    return stub


def _github(stubs: list[_Stub], comments: list[dict[str, Any]]) -> _Stub:
    def page(path: str) -> list[dict[str, Any]]:
        return comments if "page=1" in path or "page=" not in path else []

    stub = _Stub(
        {
            ("GET", "/repos/octo/app/issues/7/comments"): (200, page),
            ("POST", "/repos/octo/app/issues/7/comments"): (201, {"id": 501}),
            ("PATCH", "/repos/octo/app/issues/comments/99"): (200, {"id": 99}),
        }
    )
    stubs.append(stub)
    return stub


def _run(tmp_path: Path, lake_url: str, **env: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    outputs = tmp_path / "github_output"
    base = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(outputs),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "step_summary.md"),
        "GRC_LAKE_URL": lake_url,
        "GRC_LAKE_API_TOKEN": "",
        "CORRELATION_ID": "corr-1",
        "SUMMARY": "true",
        "COMMENT_ON_PR": "false",
        "ENFORCE": "true",
        "MIN_SCORE": "0",
        "MAX_CRITICAL_VIOLATIONS": "5",
        "MAX_OPEN_VIOLATIONS": "-1",
        "MAX_FAILING_CONTROL_TESTS": "-1",
        "ALLOWED_FAILING_CONTROLS": "",
        "FRAMEWORK": "",
        "FAIL_ON_STALE_EVIDENCE": "false",
        "POSTURE_GATE_SCRIPT": str(GATE_SCRIPT),
        "GITHUB_EVENT_NAME": "push",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, check=False, env={**base, **env}, timeout=60
    )
    parsed: dict[str, str] = {}
    if outputs.exists():
        for line in outputs.read_text().splitlines():
            key, _, value = line.partition("=")
            parsed[key] = value
    return result, parsed


# --- metadata -----------------------------------------------------------------


def test_root_action_declares_marketplace_metadata_inputs_and_outputs() -> None:
    action = yaml.safe_load(ACTION_FILE.read_text(encoding="utf-8"))
    assert action["name"] == "GRC Lake Readiness"
    assert action["description"]
    assert action["branding"]["icon"] and action["branding"]["color"]
    assert action["runs"]["using"] == "composite"
    inputs = action["inputs"]
    assert inputs["grc-lake-url"]["required"] is True
    for name in ("api-token", "correlation-id", "summary", "comment-on-pr", "github-token", "framework", "enforce"):
        assert name in inputs, name
    assert inputs["summary"]["default"] == "true"
    assert inputs["comment-on-pr"]["default"] == "false"
    assert inputs["enforce"]["default"] == "true"
    for name in (
        "min-score",
        "max-critical-violations",
        "max-open-violations",
        "max-failing-control-tests",
        "allowed-failing-controls",
        "fail-on-stale-evidence",
    ):
        assert inputs[name]["default"] == GATE_ACTION["inputs"][name]["default"], name
    outputs = action["outputs"]
    assert set(GATE_ACTION["outputs"]) | {
        "summary-path",
        "frameworks-ready-count",
        "frameworks-evaluated-count",
    } <= set(outputs)


def test_root_action_runs_the_summary_script_with_the_shared_gate() -> None:
    action = yaml.safe_load(ACTION_FILE.read_text(encoding="utf-8"))
    step = action["runs"]["steps"][-1]
    assert "readiness-summary.sh" in step["run"]
    assert step["env"]["POSTURE_GATE_SCRIPT"] == (
        "${{ github.action_path }}/.github/actions/posture-gate/posture-gate.sh"
    )
    # The GitHub token reaches the script only when a comment was requested.
    assert "comment-on-pr" in step["env"]["GITHUB_TOKEN"]


def test_scripts_are_executable() -> None:
    for script in (SCRIPT, GATE_SCRIPT):
        assert os.access(script, os.X_OK), script


def test_scripts_are_shellcheck_clean() -> None:
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not installed")
    result = subprocess.run(["shellcheck", str(SCRIPT), str(GATE_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


# --- summary --------------------------------------------------------------------


def test_summary_renders_the_table_and_honesty_lines_without_calling_github(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    github = _github(stubs, [])
    result, outputs = _run(tmp_path, lake.url, GITHUB_API_URL=github.url, GITHUB_TOKEN=TOKEN)

    assert result.returncode == 0, result.stdout + result.stderr
    assert github.requests == []
    posture_reads = [r for r in lake.requests if r["path"] == "/api/v1/posture/current"]
    assert posture_reads and posture_reads[0]["headers"].get("X-Correlation-ID") == "corr-1"

    summary = Path(outputs["summary-path"]).read_text()
    assert summary == (tmp_path / "step_summary.md").read_text()
    assert summary.startswith(MARKER)
    assert "Synthetic sample data" in summary
    assert "| SOC 2 | 50.0 | attention required | 2 / 4 | 1 | 0 | 1 |" in summary
    assert "| ISO 27001:2022 | 100.0 | ready | 3 / 3 | 0 | 0 | 0 |" in summary
    assert "| Pipe \\| Program | 100.0 | not ready (2 not evaluated) | 2 / 2 | 0 | 2 | 0 |" in summary
    assert "Collection gaps" in summary and "`okta`" in summary
    assert "2 controls not evaluated" in summary
    assert "Gate: passed" in summary
    assert outputs["frameworks-ready-count"] == "1"
    assert outputs["frameworks-evaluated-count"] == "3"
    assert outputs["posture_score"] == "41.5"
    assert outputs["posture_state"] == "critical"
    assert TOKEN not in result.stdout + result.stderr


def test_summary_without_synthetic_data_or_gaps_omits_those_lines(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(
        stubs,
        _posture(synthetic_fixture=False, collection_gaps={"sources": [], "affected_control_ids": []}),
    )
    result, outputs = _run(tmp_path, lake.url)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = Path(outputs["summary-path"]).read_text()
    assert "Synthetic sample data" not in summary
    assert "Collection gaps" not in summary


def test_each_run_writes_its_own_summary_file(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    _, first = _run(tmp_path, lake.url, ENFORCE="false", MIN_SCORE="90")
    (tmp_path / "github_output").unlink()
    _, second = _run(tmp_path, lake.url)
    assert first["summary-path"] != second["summary-path"]
    assert "Gate: not enforced" in Path(first["summary-path"]).read_text()
    assert "Gate: passed" in Path(second["summary-path"]).read_text()


def test_summary_input_false_skips_the_job_summary_but_keeps_the_file(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    result, outputs = _run(tmp_path, lake.url, SUMMARY="false")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "step_summary.md").exists()
    assert Path(outputs["summary-path"]).read_text().startswith(MARKER)


def test_zero_frameworks_is_reported_not_hidden(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs, _posture(frameworks=[]))
    result, outputs = _run(tmp_path, lake.url)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No frameworks were evaluated" in Path(outputs["summary-path"]).read_text()
    assert outputs["frameworks-evaluated-count"] == "0"
    assert outputs["frameworks-ready-count"] == "0"


def test_framework_filter_limits_rows_and_counts(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    result, outputs = _run(tmp_path, lake.url, FRAMEWORK="SOC 2")
    assert result.returncode == 0, result.stdout + result.stderr
    summary = Path(outputs["summary-path"]).read_text()
    assert "| SOC 2 |" in summary and "ISO 27001" not in summary
    assert outputs["frameworks-evaluated-count"] == "1"
    assert outputs["frameworks-ready-count"] == "0"


def test_framework_filter_that_matches_nothing_says_so(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    result, outputs = _run(tmp_path, lake.url, FRAMEWORK="soc2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No framework named `soc2`" in Path(outputs["summary-path"]).read_text()
    assert outputs["frameworks-evaluated-count"] == "0"


@pytest.mark.parametrize(
    "posture",
    [{"errors": [{"detail": "unauthorized"}]}, {"data": {"posture": {"score": 1}}}, "not json"],
    ids=["error-envelope", "missing-frameworks", "not-json"],
)
def test_malformed_posture_fails_closed(tmp_path: Path, stubs: list[_Stub], posture: Any) -> None:
    lake = _Stub({("GET", "/api/v1/posture/current"): (200, posture)})
    stubs.append(lake)
    result, outputs = _run(tmp_path, lake.url)
    assert result.returncode == 1
    assert "::error" in result.stdout
    assert "frameworks-ready-count" not in outputs
    assert not (tmp_path / "step_summary.md").exists()


def test_unreachable_deployment_fails_closed(tmp_path: Path) -> None:
    result, outputs = _run(tmp_path, "http://127.0.0.1:9")
    assert result.returncode == 1
    assert "::error" in result.stdout
    assert outputs == {}


# --- enforcement ------------------------------------------------------------------


def test_enforced_threshold_failure_fails_after_writing_the_summary(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    result, outputs = _run(tmp_path, lake.url, MIN_SCORE="90")
    assert result.returncode == 1
    summary = Path(outputs["summary-path"]).read_text()
    assert "Gate: failed" in summary
    assert "posture score 41.5 is below minimum 90" in summary
    assert "::error title=GRC Lake posture gate::" in result.stdout


def test_enforce_false_reports_but_never_fails_on_thresholds(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    result, outputs = _run(tmp_path, lake.url, MIN_SCORE="90", ENFORCE="false")
    assert result.returncode == 0, result.stdout + result.stderr
    summary = Path(outputs["summary-path"]).read_text()
    assert "Gate: not enforced" in summary
    assert "posture score 41.5 is below minimum 90" in summary
    assert "::error" not in result.stdout
    assert "::warning title=GRC Lake posture gate::" in result.stdout


def test_invalid_enforce_value_is_rejected(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    result, _ = _run(tmp_path, lake.url, ENFORCE="yes")
    assert result.returncode == 1
    assert "enforce must be true or false" in result.stdout


# --- pull request comment ---------------------------------------------------------


def _pr_env(tmp_path: Path, github: _Stub, token: str = TOKEN) -> dict[str, str]:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 7}}))
    return {
        "COMMENT_ON_PR": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": "octo/app",
        "GITHUB_API_URL": github.url,
        "GITHUB_TOKEN": token,
    }


def test_comment_updates_the_existing_marker_comment_in_place(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    github = _github(
        stubs,
        [{"id": 12, "body": "looks good"}, {"id": 99, "body": f"{MARKER}\n### old summary"}],
    )
    result, _ = _run(tmp_path, lake.url, **_pr_env(tmp_path, github))
    assert result.returncode == 0, result.stdout + result.stderr
    methods = [(r["method"], r["path"].split("?", 1)[0]) for r in github.requests]
    assert ("PATCH", "/repos/octo/app/issues/comments/99") in methods
    assert all(method != "POST" for method, _ in methods)
    patch = next(r for r in github.requests if r["method"] == "PATCH")
    assert json.loads(patch["body"])["body"].startswith(MARKER)
    assert patch["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in result.stdout + result.stderr
    assert all(r["path"].startswith("/api/v1/") for r in lake.requests)


def test_comment_is_created_when_no_marker_comment_exists(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    github = _github(stubs, [{"id": 12, "body": "unrelated"}])
    result, _ = _run(tmp_path, lake.url, **_pr_env(tmp_path, github))
    assert result.returncode == 0, result.stdout + result.stderr
    posts = [r for r in github.requests if r["method"] == "POST"]
    assert len(posts) == 1 and posts[0]["path"] == "/repos/octo/app/issues/7/comments"
    assert "| SOC 2 |" in json.loads(posts[0]["body"])["body"]
    assert not [r for r in github.requests if r["method"] == "PATCH"]


def test_comment_is_skipped_with_a_notice_outside_pull_requests(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    github = _github(stubs, [])
    env = {**_pr_env(tmp_path, github), "GITHUB_EVENT_NAME": "push"}
    result, _ = _run(tmp_path, lake.url, **env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::notice" in result.stdout and "pull request" in result.stdout
    assert github.requests == []


def test_comment_without_a_token_is_a_configuration_error(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    github = _github(stubs, [])
    result, _ = _run(tmp_path, lake.url, **_pr_env(tmp_path, github, token=""))
    assert result.returncode == 1
    assert "github-token" in result.stdout
    assert github.requests == []


def test_comment_api_failure_warns_without_failing_the_summary(tmp_path: Path, stubs: list[_Stub]) -> None:
    lake = _lake(stubs)
    github = _Stub({})
    stubs.append(github)
    result, outputs = _run(tmp_path, lake.url, **_pr_env(tmp_path, github))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::warning" in result.stdout
    assert Path(outputs["summary-path"]).is_file()
    assert TOKEN not in result.stdout + result.stderr


# --- docs, example, and CI wiring ---------------------------------------------------


def test_ci_gate_doc_covers_every_readiness_input_and_output() -> None:
    action = yaml.safe_load(ACTION_FILE.read_text(encoding="utf-8"))
    doc = (ROOT / "docs" / "CI_GATE.md").read_text(encoding="utf-8")
    section = doc.split("## Readiness summary action", 1)[1]
    for name in [*action["inputs"], *action["outputs"]]:
        assert f"`{name}`" in section, name
    assert "pull-requests: write" in section
    assert MARKER in section


def test_readme_points_ci_users_at_the_readiness_action() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    at = readme.index("uses: koda-ai-studio/grc-lake@v")
    assert "docs/CI_GATE.md#readiness-summary-action" in readme[max(0, at - 400) : at + 400]
    assert readme.index("## Quick start") < at < readme.index("## Product tour")


def test_release_readiness_names_marketplace_publication_as_a_manual_step() -> None:
    text = (ROOT / "docs" / "RELEASE_READINESS.md").read_text(encoding="utf-8")
    assert "Marketplace" in text and "manual" in text


def test_example_uses_the_root_action_on_the_sample_lake() -> None:
    path = ROOT / "examples" / "github-actions" / "grc-lake-readiness-summary.yml"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Targets v")
    workflow = yaml.safe_load(text)
    steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
    assert any(str(step.get("uses", "")).startswith("koda-ai-studio/grc-lake@v") for step in steps)
    assert any("fixtures load --company golden" in str(step.get("run", "")) for step in steps)
    assert all(job.get("timeout-minutes") for job in workflow["jobs"].values())


def _ci_readiness_jobs() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    jobs = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in workflow.get("jobs", {}).values():
            if any(step.get("uses") == "./" for step in job.get("steps", [])):
                jobs.append((workflow, job))
    return jobs


def test_ci_runs_the_root_action_against_the_loopback_sample_without_secrets() -> None:
    jobs = _ci_readiness_jobs()
    assert jobs, "no workflow job runs the root action with uses: ./"
    for workflow, job in jobs:
        triggers = workflow.get(True) or workflow.get("on")
        assert "pull_request" in triggers
        assert job["timeout-minutes"] <= 20
        assert (job.get("permissions") or workflow.get("permissions")) == {"contents": "read"}
        text = yaml.safe_dump(job)
        assert "secrets." not in text
        assert "127.0.0.1" in text
        local = [step for step in job["steps"] if step.get("uses") == "./"]
        assert any(step["with"].get("enforce") == "false" for step in local)
