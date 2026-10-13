"""Offline GitHub collection contracts; no provider credentials or network calls."""

import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from security_lakehouse import repo_governance as governance
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run, run_probe
from security_lakehouse.validation import validate_raw_events


def client():
    return governance.GitHubGovernanceClient(
        governance.GovernanceRepoSpec("github", "acme", "model-service"), token="synthetic-token"
    )


def page_rows(page):
    return [{"id": (page - 1) * 100 + index, "state": "open"} for index in range(100)]


@pytest.mark.parametrize("signal", ["collaborators", "teams"])
def test_access_inventory_collects_beyond_first_page(monkeypatch, signal):
    adapter = client()
    requested = []

    def request(url):
        requested.append(url)
        page = int(parse_qs(urlsplit(url).query).get("page", ["1"])[0])
        return page_rows(1) if page == 1 else [{"id": 100}]

    monkeypatch.setattr(adapter, "_request", request)
    assert len(getattr(adapter, signal)()) == 101
    assert [parse_qs(urlsplit(url).query)["page"] for url in requested] == [["1"], ["2"]]


def test_page_budget_cannot_turn_an_incomplete_list_into_success(monkeypatch):
    adapter = client()
    monkeypatch.setattr(adapter, "_request", lambda url: page_rows(int(parse_qs(urlsplit(url).query)["page"][0])))
    with pytest.raises(ValueError, match="page limit"):
        adapter._json_list_paginated("https://api.github.com/repos/acme/model-service/collaborators", max_pages=2)


def test_repeated_page_cannot_be_counted_as_new_evidence(monkeypatch):
    adapter = client()
    monkeypatch.setattr(adapter, "_request", lambda url: page_rows(1))
    with pytest.raises(ValueError, match="repeated page"):
        adapter._json_list_paginated("https://api.github.com/repos/acme/model-service/teams", max_pages=2)


def test_malformed_items_cannot_be_silently_dropped(monkeypatch):
    adapter = client()
    monkeypatch.setattr(adapter, "_request", lambda url: [{"id": 1}, "invalid-item"])
    with pytest.raises(ValueError, match="non-object"):
        adapter._json_list_paginated("https://api.github.com/repos/acme/model-service/teams")


@pytest.mark.parametrize("status", [429, 503])
def test_exhausted_http_failure_is_not_reported_as_permission_evidence(monkeypatch, status):
    adapter = client()

    def request(url):
        raise urllib.error.HTTPError(url, status, "synthetic failure", {}, None)

    monkeypatch.setattr(adapter, "_request", request)
    with pytest.raises(urllib.error.HTTPError) as exc:
        adapter.security_findings()
    assert exc.value.code == status


def test_rate_limit_wait_is_honored_and_request_remains_read_only(monkeypatch):
    waits, requests = [], []
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", waits.append)
    response = MagicMock()
    response.status = 200
    response.read.return_value = b"[]"
    response.__enter__.return_value = response

    def open_public(request, **kwargs):
        requests.append(request)
        if len(requests) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "slow", {"Retry-After": "3"}, None)
        return response

    monkeypatch.setattr(governance.netguard, "open_public", open_public)
    assert client().collaborators() == []
    assert waits == [3]
    assert len(requests) == 2
    assert all(request.get_method() == "GET" and request.data is None for request in requests)
    assert requests[0].full_url == requests[1].full_url


def test_probe_only_validates_configuration_not_github_access(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a configuration probe must not collect GitHub evidence")

    monkeypatch.setattr(governance.netguard, "open_public", forbidden)
    result = run_probe(
        tmp_path,
        connector_id="github-security",
        credentials={"token": "synthetic-token"},
        options={"repo": "acme/model-service"},
    )
    assert result["result"] == "ok"
    assert not (tmp_path / CONNECTOR_RAW_FILE).exists()


def test_incomplete_live_path_preserves_prior_materialization(tmp_path, monkeypatch):
    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="fixture")
    run_connector_sync(
        tmp_path,
        connector_id="github-security",
        repo="acme/model-service",
        fixture_dir=Path(__file__).parent / "fixtures/github-governance",
    )
    before = (tmp_path / CONNECTOR_RAW_FILE).read_bytes()
    posture = (tmp_path / "gold/current_posture.json").read_bytes()
    monkeypatch.setenv("GRC_LAKE_GITHUB_APP_INSTALLATION_TOKEN", "synthetic-token")
    paginate = governance.GitHubGovernanceClient._json_list_paginated
    monkeypatch.setattr(
        governance.GitHubGovernanceClient, "_json_list_paginated", lambda self, url: paginate(self, url, max_pages=2)
    )

    def request(self, url):
        if "collaborators" in url:
            return page_rows(int(parse_qs(urlsplit(url).query).get("page", ["1"])[0]))
        if "teams" in url or "/alerts" in url:
            return []
        return {"default_branch": "main", "full_name": "acme/model-service"}

    monkeypatch.setattr(governance.GitHubGovernanceClient, "_request", request)
    with pytest.raises(ConnectorSyncError):
        run_connector_sync(tmp_path, connector_id="github-security", repo="acme/model-service")
    assert latest_run(tmp_path, "github-security", kind="sync")["result"] == "error"
    assert (tmp_path / CONNECTOR_RAW_FILE).read_bytes() == before
    assert (tmp_path / "gold/current_posture.json").read_bytes() == posture


def test_fixture_replay_preserves_identity_and_evidence_hashes():
    kwargs = dict(
        fixture_dir=Path(__file__).parent / "fixtures/github-governance",
        collected_at=datetime(2026, 10, 12, tzinfo=UTC),
        token="synthetic-token",
    )
    first = governance.sync_repo_governance("acme/model-service", **kwargs)
    assert first == governance.sync_repo_governance("acme/model-service", **kwargs)
    assert validate_raw_events(first) == []
    assert all(row["entity"]["asset_id"] == "github:repo:acme/model-service" for row in first)
    assert all(row["evidence"]["raw_sha256"] for row in first)
    assert "synthetic-token" not in json.dumps(first)
