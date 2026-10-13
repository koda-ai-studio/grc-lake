"""Public onboarding must bound reads and retain one source revision."""

import io

import pytest

from security_lakehouse import repo_audit
from test_repo_audit import _fixture, _write_json


@pytest.mark.parametrize(
    "value", ["https://evil.test/a/b", "a/..", "../b", "a/b?x=1", "a/b#ref", "a/é", "https://github.com/a/b/extra"]
)
def test_only_supported_repository_identifiers(value):
    with pytest.raises(ValueError):
        repo_audit.parse_repo_spec(value)


def test_repository_case_is_canonical():
    assert repo_audit.parse_repo_spec("https://github.com/Acme/Agent-API.git/").slug == "acme/agent-api"


def test_audit_pins_tree_and_samples_and_records_observation(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    _write_json(fixture / "commit.json", {"sha": "a" * 40, "commit": {"tree": {"sha": "b" * 40}}})
    requested = []
    original_tree = repo_audit.FixtureRepoClient.tree
    original_text = repo_audit.FixtureRepoClient.file_text
    monkeypatch.setattr(
        repo_audit.FixtureRepoClient,
        "tree",
        lambda self, ref: (requested.append(("tree", ref)), original_tree(self, ref))[1],
    )
    monkeypatch.setattr(
        repo_audit.FixtureRepoClient,
        "file_text",
        lambda self, ref, path: (requested.append(("file", ref)), original_text(self, ref, path))[1],
    )
    rows = repo_audit.audit_public_repo("ACME/agent-api", fixture_dir=fixture)
    assert ("tree", "b" * 40) in requested
    assert all(ref == "a" * 40 for kind, ref in requested if kind == "file")
    assert all(row["attributes"]["source_commit"] == "a" * 40 for row in rows)
    assert all(row["attributes"]["synthetic"] is True for row in rows)
    assert len({row["attributes"]["observation_id"] for row in rows}) == 1
    assert all(row["tenant_id"] == "github:acme" for row in rows)


def test_metadata_cannot_rebind_repository(tmp_path):
    fixture = _fixture(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        repo_audit.audit_public_repo("other/agent-api", fixture_dir=fixture)


def test_json_response_is_bounded(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("unguarded transport used"))

    class Response(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= repo_audit.MAX_JSON_BYTES + 1
            return super().read(size)

    monkeypatch.setattr(repo_audit, "MAX_JSON_BYTES", 32, raising=False)
    monkeypatch.setattr("security_lakehouse.netguard.open_guarded", lambda *a, **k: Response(b" " * 33))
    with pytest.raises(ValueError, match="limit"):
        repo_audit.PublicGitHubClient("acme", "agent-api").repo()


def test_redirect_validator_rejects_other_host_and_repository(monkeypatch):
    def open_guarded(request, *, validate, **kwargs):
        validate(request.full_url)
        for url in [
            "http://api.github.com/repos/acme/agent-api",
            "https://127.0.0.1/",
            "https://api.github.com/repos/other/repo",
            "https://api.github.com:444/repos/acme/agent-api",
            "https://user@api.github.com/repos/acme/agent-api",
        ]:
            with pytest.raises(ValueError):
                validate(url)
        return io.BytesIO(b"{}")

    monkeypatch.setattr("security_lakehouse.netguard.open_guarded", open_guarded)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("unguarded transport used"))
    assert repo_audit.PublicGitHubClient("acme", "agent-api").repo() == {}


def test_request_budget_stops_before_network(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("unguarded transport used"))
    monkeypatch.setattr(repo_audit, "MAX_REQUESTS", 1, raising=False)
    calls = []
    monkeypatch.setattr(
        "security_lakehouse.netguard.open_guarded", lambda request, **k: (calls.append(request), io.BytesIO(b"{}"))[1]
    )
    client = repo_audit.PublicGitHubClient("acme", "agent-api")
    client.repo()
    with pytest.raises(ValueError, match="budget"):
        client.languages()
    assert len(calls) == 1


def test_public_and_authenticated_github_use_the_same_canonical_identity():
    from datetime import UTC, datetime

    from security_lakehouse.repo_governance import _event, parse_governance_repo_spec

    spec = parse_governance_repo_spec("https://github.com/ACME/Agent-API.git")
    assert spec.asset_id == repo_audit.parse_repo_spec("acme/agent-api").asset_id
    row = _event(
        spec,
        datetime.now(UTC),
        signal="branch_protection",
        event_type="repository.governance.branch_protection",
        controls=[],
        evidence_ref="https://github.com/acme/agent-api",
        attributes={},
        status="observed",
    )
    assert row["tenant_id"] == "github:acme"


def test_large_file_is_only_a_bounded_sample(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("unguarded transport used"))
    monkeypatch.setattr(repo_audit, "MAX_FILE_BYTES", 8)
    monkeypatch.setattr("security_lakehouse.netguard.open_guarded", lambda *a, **k: io.BytesIO(b"123456789abc"))
    assert repo_audit.PublicGitHubClient("acme", "agent-api").file_text("a" * 40, "package-lock.json") == "12345678"
