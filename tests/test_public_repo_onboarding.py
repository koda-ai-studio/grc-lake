"""Console audit uses the scoped pipeline and durable authorized operations."""

import json
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from security_lakehouse import api_v1, repo_audit, server_app
from security_lakehouse.db import repository
from security_lakehouse.io import read_jsonl
from test_repo_audit import _fixture

PATH = "/api/v1/repositories/public-audit"


def fixture_collector(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    original = repo_audit.audit_public_repo
    calls = []

    def collect(repo):
        calls.append(repo)
        return original(repo, fixture_dir=fixture)

    monkeypatch.setattr(repo_audit, "audit_public_repo", collect)
    return calls


def test_collection_publishes_graph_and_replay_preserves_other_sources(tmp_path, monkeypatch):
    fixture_collector(tmp_path, monkeypatch)
    lake = tmp_path / "lake"
    for index, value in enumerate(["https://github.com/Acme/agent-api", "acme/agent-api.git"]):
        status, response = api_v1.handle_post(PATH, {"repo": value}, lake)
        assert status == 201, response
        data = response["data"]
        assert data["repo"] == "acme/agent-api"
        assert data["source_commit"] == "a" * 40
        assert data["source_account_id"] == "github:acme"
        assert "root=" in data["investigate_href"]
        if index == 0:
            from copy import deepcopy

            from security_lakehouse.connector_runner import _upsert_raw_events

            other = deepcopy(read_jsonl(lake / "raw/connector_events.jsonl")[0])
            other["tenant_id"] = "another-source-account"
            _upsert_raw_events(lake / "raw/connector_events.jsonl", [other], connector_id="other", write_mode="append")
    rows = read_jsonl(lake / "raw/connector_events.jsonl")
    assert len(rows) == data["evidence_count"] + 1
    assert len({(row["tenant_id"], row["event_id"]) for row in rows}) == len(rows)
    from security_lakehouse.investigation_graph import investigation_graph

    graph = investigation_graph(lake, root=data["graph_root"], view="investigation")
    assert graph["root_missing"] is False
    assert any(node["kind"] == "repository" for node in graph["nodes"])
    assert all(row["status"] in {"observed", "requires_authenticated_connector"} for row in rows)


@pytest.mark.parametrize(
    "body",
    [
        {"repo": "https://evil.test/a/b"},
        {"repo": "acme/agent-api", "fixture_dir": "/private"},
        {"repo": "acme/agent-api", "token": "secret"},
        {"repo": 3},
    ],
)
def test_bad_input_cannot_call_provider(tmp_path, monkeypatch, body):
    monkeypatch.setattr(repo_audit, "audit_public_repo", lambda *a, **k: pytest.fail("provider called"))
    assert api_v1.handle_post(PATH, body, tmp_path)[0] == 400


@pytest.mark.parametrize(("code", "expected"), [(429, 429), (403, 403), (404, 404)])
def test_provider_failure_is_actionable_and_does_not_publish(tmp_path, monkeypatch, code, expected):
    def fail(*a, **k):
        raise HTTPError("https://provider/private-marker", code, "private-marker", {}, None)

    monkeypatch.setattr(repo_audit, "audit_public_repo", fail)
    status, body = api_v1.handle_post(PATH, {"repo": "acme/agent-api"}, tmp_path)
    assert status == expected
    assert "private-marker" not in json.dumps(body)
    assert not (tmp_path / "raw/connector_events.jsonl").exists()


def test_hosted_scope_queue_and_tenant_isolation(tmp_path, monkeypatch):
    calls = fixture_collector(tmp_path, monkeypatch)
    root = tmp_path / "server"
    app = server_app.create_app(root)
    tokens = {}
    with app.state.sessionmaker.begin() as session:
        for slug, role in [("first", "admin"), ("second", "admin"), ("reader", "read_only")]:
            tenant = repository.create_tenant(session, slug=slug, name=slug)
            user = repository.create_user(session, tenant_id=tenant.id, email=slug + "@example.test", role=role)
            _, token = repository.create_api_key(session, tenant_id=tenant.id, user_id=user.id)
            tokens[slug] = (tenant.id, token)
    client = TestClient(app)

    def post(who, key="same"):
        return client.post(
            PATH,
            json={"repo": "acme/agent-api"},
            headers={"Authorization": "Bearer " + tokens[who][1], "Prefer": "respond-async", "Idempotency-Key": key},
        )

    assert post("reader").status_code == 403
    response = post("first")
    assert response.status_code == 202, response.text
    assert calls == []
    assert post("first").json()["data"]["id"] == response.json()["data"]["id"]
    row = app.state.operation_queue.claim()
    code, result = app.state.operation_worker.subprocess_execute(root, row)
    assert code == 201, result
    assert (root / "tenants" / tokens["first"][0] / "raw/connector_events.jsonl").exists()
    assert not (root / "tenants" / tokens["second"][0] / "raw/connector_events.jsonl").exists()
    url = response.json()["data"]["status_url"]
    assert client.get(url, headers={"Authorization": "Bearer " + tokens["second"][1]}).status_code == 404


def test_first_console_audit_preserves_a_previously_imported_lake(tmp_path, monkeypatch):
    from security_lakehouse.io import write_jsonl
    from security_lakehouse.pipeline import normalize_raw_events

    fixture = _fixture(tmp_path)
    prior = repo_audit.audit_public_repo("acme/agent-api", fixture_dir=fixture)[0]
    prior["tenant_id"] = "existing-source-account"
    original = tmp_path / "import.jsonl"
    write_jsonl(original, [prior])
    lake = tmp_path / "imported-lake"
    normalize_raw_events(original, lake)
    fixture_collector(tmp_path / "next-fixture", monkeypatch)
    code, result = api_v1.handle_post(PATH, {"repo": "acme/agent-api"}, lake)
    assert code == 201
    raw = read_jsonl(lake / "raw/connector_events.jsonl")
    assert prior in raw
    assert len(raw) == result["data"]["evidence_count"] + 1


def test_failed_collection_leaves_existing_raw_and_generation(tmp_path, monkeypatch):
    fixture_collector(tmp_path, monkeypatch)
    lake = tmp_path / "lake"
    assert api_v1.handle_post(PATH, {"repo": "acme/agent-api"}, lake)[0] == 201
    raw = lake / "raw/connector_events.jsonl"
    before = raw.read_bytes()
    from security_lakehouse.generations import generation_identity

    generation = generation_identity(lake)

    def fail(*args, **kwargs):
        raise ValueError("tree is truncated")

    monkeypatch.setattr(repo_audit, "audit_public_repo", fail)
    assert api_v1.handle_post(PATH, {"repo": "acme/agent-api"}, lake)[0] == 502
    assert raw.read_bytes() == before
    assert generation_identity(lake) == generation


def test_authenticated_upgrade_adds_evidence_to_the_same_repository(tmp_path):
    from datetime import UTC, datetime

    from security_lakehouse.investigation_graph import _id, investigation_graph
    from security_lakehouse.io import write_jsonl
    from security_lakehouse.pipeline import normalize_raw_events
    from security_lakehouse.repo_governance import _event, parse_governance_repo_spec

    public = repo_audit.audit_public_repo("acme/agent-api", fixture_dir=_fixture(tmp_path))
    governance = _event(
        parse_governance_repo_spec("ACME/Agent-API"),
        datetime.now(UTC),
        signal="branch_protection",
        event_type="repository.governance.branch_protection",
        controls=[],
        evidence_ref="https://github.com/acme/agent-api",
        attributes={"governance": {"protected": True}},
        status="observed",
    )
    raw = tmp_path / "all.jsonl"
    write_jsonl(raw, [*public, governance])
    lake = tmp_path / "lake"
    normalize_raw_events(raw, lake)
    graph = investigation_graph(
        lake, root=_id("asset", "github:acme", "github:repo:acme/agent-api"), view="investigation"
    )
    assert len([node for node in graph["nodes"] if node["kind"] == "repository"]) == 1
    retained = [row["raw"] for row in read_jsonl(lake / "bronze/raw_events.jsonl")]
    assert {row["source"] for row in retained} == {"github-public-repo", "github-repo-governance"}
