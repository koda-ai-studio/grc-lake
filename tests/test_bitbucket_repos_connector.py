"""Synthetic Bitbucket repository governance and failure contracts."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import netguard
from security_lakehouse.connector_errors import ConnectorConfigError
from security_lakehouse.connectors_bitbucket_repos import (
    BitbucketReposClient,
    BitbucketReposFixtureClient,
    collect_bitbucket_repos_evidence,
)
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures/bitbucket_repos"
BASE = "https://api.bitbucket.org/2.0/repositories/example"
RULES = BASE + "/demo/branch-restrictions?pagelen=100"
TOKEN = "synthetic-bitbucket-token"


def client() -> BitbucketReposFixtureClient:
    return BitbucketReposFixtureClient(FIXTURE, workspace="example")


def verdict(c: Any) -> dict[str, Any]:
    rows = collect_bitbucket_repos_evidence(c)
    assert validate_raw_events(rows) == []
    return next(r for r in rows if r["event_type"] == "repository.governance.change_approval")


def test_complete_restrictions_bind_change_approval() -> None:
    row = verdict(client())
    assert row["status"] == "pass"
    assert row["entity"]["asset_type"] == "repo"
    assert row["safeguard_ids"] == ["SG-CHANGEAPPROVAL-001"]
    assert row["attributes"]["required_approving_review_count"] == 2


@pytest.mark.parametrize("kind", ["force", "delete", "enforce_merge_checks", "require_approvals_to_merge", "push"])
def test_missing_required_restriction_is_open(kind: str) -> None:
    c = client()
    c.responses[RULES]["values"] = [r for r in c.responses[RULES]["values"] if r["kind"] != kind]
    c.responses[RULES]["size"] = 4
    assert verdict(c)["status"] == "open"


@pytest.mark.parametrize("value", [True, "2", None, -1])
def test_invalid_approval_values_never_pass(value: Any) -> None:
    c = client()
    c.responses[RULES]["values"][0]["value"] = value
    assert verdict(c)["status"] == "not_evaluated"


def test_branch_model_and_overlapping_rules_remain_unknown() -> None:
    c = client()
    rule = dict(c.responses[RULES]["values"][0], id=99, pattern="*", value=1)
    c.responses[RULES]["values"].append(rule)
    c.responses[RULES]["size"] = 6
    assert "overlapping_restrictions" in verdict(c)["attributes"]["unknown_requirements"]
    c = client()
    c.responses[RULES]["values"][0].update(branch_match_kind="branching_model", branch_type="production")
    assert verdict(c)["status"] == "not_evaluated"


def test_push_exceptions_do_not_pass() -> None:
    c = client()
    c.responses[RULES]["values"][-1]["users"] = [{"uuid": "synthetic"}]
    assert verdict(c)["status"] == "open"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/next",
        "http://api.bitbucket.org/2.0/repositories/example?page=2",
        "https://api.bitbucket.org@evil.example/path",
        "https://api.bitbucket.org/2.0/repositories/other",
        BASE + "/../other",
        BASE + "%2fother",
    ],
)
def test_unsafe_next_url_is_a_gap(url: str) -> None:
    c = client()
    c.responses[BASE + "?pagelen=100"]["next"] = url
    rows = collect_bitbucket_repos_evidence(c)
    assert rows and all(r["status"] == "not_evaluated" for r in rows)
    assert rows[0]["attributes"]["collection_gap"] is True


@pytest.mark.parametrize("payload", [{}, {"values": []}, {"values": [None]}, {"values": [{"slug": "../evil"}]}])
def test_invalid_or_empty_scope_is_a_gap(payload: Any) -> None:
    c = client()
    c.responses[BASE + "?pagelen=100"] = payload
    assert collect_bitbucket_repos_evidence(c)[0]["attributes"]["collection_gap"] is True


@pytest.mark.parametrize("code", [401, 403, 429])
def test_denied_rules_preserve_visibility_and_never_leak_token(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    c = client()

    def read(request: Any, **kwargs: Any) -> Any:
        assert request.get_method() == "GET"
        if request.full_url == RULES:
            raise urllib.error.HTTPError(RULES, code, TOKEN, {"Retry-After": "301"}, None)
        return io.BytesIO(json.dumps(c.responses[request.full_url]).encode())

    monkeypatch.setattr(netguard, "open_public", read)
    rows = collect_bitbucket_repos_evidence(BitbucketReposClient(token=TOKEN, workspace="example"))
    assert any(r["event_type"] == "repository.governance.visibility" and r["status"] == "observed" for r in rows)
    assert next(r for r in rows if r["event_type"].endswith("change_approval"))["status"] == "not_evaluated"
    assert TOKEN not in json.dumps(rows)


@pytest.mark.parametrize("workspace", ["../evil", "x/y", "x@evil", "https://evil", "a%2fb"])
def test_workspace_injection_rejected(workspace: str) -> None:
    with pytest.raises(ConnectorConfigError):
        BitbucketReposClient(token=TOKEN, workspace=workspace)


def test_runner_to_ccf_and_denied_scope_is_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
    from security_lakehouse.connector_state import append_config_event, latest_run
    from security_lakehouse.io import read_json
    from security_lakehouse.pipeline import run_pipeline

    append_config_event(
        tmp_path, connector_id="bitbucket-repos", state="enabled", actor="test", credentials={"workspace": "example"}
    )
    result = run_connector_sync(tmp_path, connector_id="bitbucket-repos", fixture_dir=FIXTURE, materialize=False)
    assert not result.coverage_gaps
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="bitbucket-test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    row = next(r for r in assessment["safeguards"] if r["safeguard_id"] == "SG-CHANGEAPPROVAL-001")
    assert row["assessed_asset_count"] == 1 and row["invalid_binding_count"] == 0
    broken = tmp_path / "fixture"
    broken.mkdir()
    responses = client().responses
    del responses[RULES]
    (broken / "responses.json").write_text(json.dumps(responses))
    result = run_connector_sync(tmp_path, connector_id="bitbucket-repos", fixture_dir=broken, materialize=False)
    assert result.coverage_gaps
    assert latest_run(tmp_path, "bitbucket-repos", kind="sync")["metadata"]["partial"] is True


def test_pagination_retry_and_stable_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    c = client()
    rules = c.responses[RULES]["values"]
    second = BASE + "/demo/branch-restrictions?page=2"
    c.responses[RULES] = {"values": rules[:2], "next": second, "size": 5}
    c.responses[second] = {"values": rules[2:], "size": 5}
    attempts = 0
    sleeps: list[float] = []

    def read(request: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        assert request.get_method() == "GET"
        assert request.full_url.startswith(BASE)
        if attempts == 1:
            raise urllib.error.HTTPError(BASE, 429, "rate limit", {"Retry-After": "2"}, None)
        return io.BytesIO(json.dumps(c.responses[request.full_url]).encode())

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", sleeps.append)
    row = verdict(BitbucketReposClient(token=TOKEN, workspace="example"))
    assert row["status"] == "pass" and sleeps == [2.0]
    assert row["event_id"] == verdict(client())["event_id"]


def test_page_budget_repeat_and_malformed_restrictions_are_gaps() -> None:
    c = client()
    c.max_pages = 1
    c.responses[RULES]["next"] = BASE + "/demo/branch-restrictions?page=2"
    assert verdict(c)["status"] == "not_evaluated"
    c = client()
    c.responses[RULES]["next"] = RULES
    assert verdict(c)["status"] == "not_evaluated"
    c = client()
    c.responses[RULES] = {"values": [False]}
    assert verdict(c)["status"] == "not_evaluated"


@pytest.mark.parametrize(
    ("pattern", "branch", "matches"),
    [
        ("m*", "main", True),
        ("*", "main", True),
        ("ma?n", "main", False),
        ("m[ai]*", "main", False),
        ("main*main", "main", False),
        ("a*b*c", "abbbc", True),
        ("a*b*c", "abbbd", False),
    ],
)
def test_documented_glob_semantics(pattern: str, branch: str, matches: bool) -> None:
    from security_lakehouse.connectors_bitbucket_repos import _matches

    assert _matches(pattern, branch) is matches


def test_missing_reference_never_uses_ambient_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connector_runner import ConnectorSyncError, run_connector_sync
    from security_lakehouse.connector_state import append_config_event

    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", TOKEN)
    append_config_event(
        tmp_path, connector_id="bitbucket-repos", state="enabled", actor="test", credentials={"workspace": "example"}
    )
    with pytest.raises(ConnectorSyncError, match="credential_ref"):
        run_connector_sync(tmp_path, connector_id="bitbucket-repos", materialize=False)


def test_unresolved_reference_does_not_fall_back_to_another_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from security_lakehouse.connector_runner import ConnectorSyncError, run_connector_sync
    from security_lakehouse.connector_state import append_config_event

    monkeypatch.setenv("BITBUCKET_ACCESS_TOKEN", TOKEN)
    monkeypatch.delenv("BITBUCKET_MISSING_REF", raising=False)

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Unresolved reference attempted a network request")

    monkeypatch.setattr(netguard, "open_public", unexpected)
    append_config_event(
        tmp_path,
        connector_id="bitbucket-repos",
        state="enabled",
        actor="test",
        credentials={"workspace": "example", "credential_ref": "BITBUCKET_MISSING_REF"},
    )
    with pytest.raises(ConnectorSyncError, match="could not be resolved"):
        run_connector_sync(tmp_path, connector_id="bitbucket-repos", materialize=False)
