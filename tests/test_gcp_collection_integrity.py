"""Incomplete GCP reads cannot silently replace retained evidence."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from security_lakehouse import connector_runner
from security_lakehouse.connector_errors import ConnectorAccessError
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.connectors_gcp import GCPClient, GCPFixtureClient, collect_gcp_evidence

FIXTURE = Path(__file__).parent / "fixtures/gcp"
METHODS = ("iam_bindings", "org_policies", "assets")
VALID = {
    "iam_bindings": {"role": "roles/viewer", "members": ["user:reader@example.test"]},
    "org_policies": {"constraint": "compute.requireOsLogin", "enforced": True},
    "assets": {"name": "//storage.googleapis.com/example"},
}


def fixture_copy(tmp_path):
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURE, fixture)
    return fixture


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("payload", [None, {}, "private-value", [None], [7], [{}]])
def test_malformed_fixture_is_rejected(tmp_path, method, payload):
    fixture = fixture_copy(tmp_path)
    (fixture / f"{method}.json").write_text(json.dumps(payload))
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete") as exc:
        collect_gcp_evidence(GCPFixtureClient(fixture))
    assert "private-value" not in str(exc.value)


@pytest.mark.parametrize("method", METHODS)
def test_missing_fixture_is_not_empty_success(tmp_path, method):
    fixture = fixture_copy(tmp_path)
    (fixture / f"{method}.json").unlink()
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete"):
        collect_gcp_evidence(GCPFixtureClient(fixture))


@pytest.mark.parametrize("method", METHODS)
def test_mixed_valid_and_invalid_records_are_not_filtered(tmp_path, method):
    fixture = fixture_copy(tmp_path)
    (fixture / f"{method}.json").write_text(json.dumps([VALID[method], {}]))
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete"):
        collect_gcp_evidence(GCPFixtureClient(fixture))


@pytest.mark.parametrize("members", [None, "user:private-value", [1], [None], [" "]])
def test_iam_members_cannot_be_coerced_to_principals(tmp_path, members):
    fixture = fixture_copy(tmp_path)
    (fixture / "iam_bindings.json").write_text(json.dumps([{**VALID["iam_bindings"], "members": members}]))
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete"):
        collect_gcp_evidence(GCPFixtureClient(fixture))


def test_explicit_empty_collections_remain_valid(tmp_path):
    for method in METHODS:
        (tmp_path / f"{method}.json").write_text("[]")
    rows = collect_gcp_evidence(GCPFixtureClient(tmp_path))
    # No project policies: each expected constraint's enforcement is unestablished.
    assert [(row["event_type"], row["status"], row["attributes"]["set_on_project"]) for row in rows] == [
        ("gcp.cloud.org_policy", "not_evaluated", False)
    ] * 2


@pytest.mark.parametrize("method,key", [("iam_bindings", "bindings"), ("assets", "assets")])
def test_fixture_cannot_claim_completion_with_another_page(tmp_path, method, key):
    fixture = fixture_copy(tmp_path)
    (fixture / f"{method}.json").write_text(json.dumps({key: [], "nextPageToken": "private-value"}))
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete") as exc:
        collect_gcp_evidence(GCPFixtureClient(fixture))
    assert "private-value" not in str(exc.value)


def sdk_client(method, response):
    client = object.__new__(GCPClient)
    client.project_id = "test-project"
    attr, call = {
        "iam_bindings": ("_projects", "get_iam_policy"),
        "org_policies": ("_org_policies", "list_policies"),
        "assets": ("_assets", "list_assets"),
    }[method]
    setattr(client, attr, SimpleNamespace(**{call: lambda **kwargs: response}))
    return client


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("response", [None, {}, "private-value", [SimpleNamespace()]])
def test_malformed_sdk_response_is_rejected(method, response):
    client = sdk_client(method, response)
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete") as exc:
        getattr(client, method)()
    assert "private-value" not in str(exc.value)


@pytest.mark.parametrize("method", ["assets", "org_policies"])
def test_sdk_pager_failure_after_a_record_rejects_collection(method):
    def pages():
        yield SimpleNamespace(name="projects/test/policies/compute.requireOsLogin", asset_type="example")
        raise RuntimeError("private-value")

    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete") as exc:
        getattr(sdk_client(method, pages()), method)()
    assert "private-value" not in str(exc.value)


@pytest.mark.parametrize("method", METHODS)
def test_failed_sync_preserves_retained_evidence(tmp_path, monkeypatch, method):
    append_config_event(tmp_path, connector_id="gcp-posture", state="enabled", actor="test")
    connector_runner.run_connector_sync(tmp_path, connector_id="gcp-posture", fixture_dir=FIXTURE)
    retained = [tmp_path / connector_runner.CONNECTOR_RAW_FILE, tmp_path / "gold/current_posture.json"]
    previous = [path.read_bytes() for path in retained]
    client = GCPFixtureClient(FIXTURE)
    monkeypatch.setattr(client, method, lambda: [VALID[method], {}])
    monkeypatch.setattr(connector_runner, "GCPClient", lambda *a, **k: client)
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    with pytest.raises(connector_runner.ConnectorSyncError):
        connector_runner.run_connector_sync(tmp_path, connector_id="gcp-posture")
    assert [path.read_bytes() for path in retained] == previous
    assert latest_run(tmp_path, "gcp-posture", kind="sync")["result"] == "error"


@pytest.mark.parametrize("condition", ["private-value", 1, {"title": "missing expression"}, {"expression": 1}])
def test_malformed_iam_condition_is_not_coerced(tmp_path, condition):
    fixture = fixture_copy(tmp_path)
    (fixture / "iam_bindings.json").write_text(json.dumps([{**VALID["iam_bindings"], "condition": condition}]))
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete"):
        collect_gcp_evidence(GCPFixtureClient(fixture))


def test_real_sdk_empty_policy_and_repeated_members_are_supported():
    policy_pb2 = pytest.importorskip("google.iam.v1.policy_pb2")
    assert sdk_client("iam_bindings", policy_pb2.Policy()).iam_bindings() == []
    policy = policy_pb2.Policy(bindings=[VALID["iam_bindings"]])
    assert sdk_client("iam_bindings", policy).iam_bindings() == [VALID["iam_bindings"]]


@pytest.mark.parametrize("method", ["assets", "org_policies"])
def test_successful_sdk_iterator_is_exhausted(method):
    def pages():
        for index in range(3):
            yield SimpleNamespace(name=f"projects/test/policies/example{index}", asset_type="example")

    records = getattr(sdk_client(method, pages()), method)()
    assert [record["name"] for record in records] == [f"projects/test/policies/example{i}" for i in range(3)]
    assert getattr(sdk_client(method, iter([])), method)() == []


@pytest.mark.parametrize("condition", [{}, "private-value", SimpleNamespace(expression=0)])
def test_sdk_cannot_discard_a_malformed_condition(condition):
    binding = SimpleNamespace(**VALID["iam_bindings"], condition=condition)
    with pytest.raises(ConnectorAccessError, match="GCP collection incomplete"):
        sdk_client("iam_bindings", SimpleNamespace(bindings=[binding])).iam_bindings()
