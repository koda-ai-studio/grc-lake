"""Malformed Azure collections must fail before replacing retained evidence."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from security_lakehouse import connector_runner
from security_lakehouse.connector_errors import ConnectorAccessError
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.connectors_azure import AzureCliClient, AzureClient
from security_lakehouse.io import read_jsonl


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr("security_lakehouse.connectors_azure.shutil.which", lambda _: "/test/az")
    return AzureCliClient("test-subscription")


@pytest.mark.parametrize(
    "payload",
    [
        None,
        7,
        "secret-payload",
        {},
        {"value": None},
        [None],
        [{"id": "valid"}, 7],
        {"value": [False]},
        {"value": [], "nextLink": "https://secret.invalid/next"},
    ],
)
@pytest.mark.parametrize("method", ["role_assignments", "role_definitions", "policy_assignments", "resources"])
def test_cli_rejects_incomplete_or_malformed_collections(cli, monkeypatch, payload, method):
    monkeypatch.setattr(
        "security_lakehouse.connectors_azure.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)),
    )
    with pytest.raises(ValueError, match="Azure collection") as exc:
        getattr(cli, method)()
    assert "secret" not in str(exc.value)


def test_cli_rejects_empty_stdout(cli, monkeypatch):
    monkeypatch.setattr(
        "security_lakehouse.connectors_azure.subprocess.run", lambda *a, **k: SimpleNamespace(stdout="")
    )
    with pytest.raises(ConnectorAccessError, match="invalid JSON"):
        cli.resources()


@pytest.mark.parametrize("payload", [[], {"value": []}, [{"id": "resource"}], {"value": [{"id": "resource"}]}])
def test_cli_preserves_valid_empty_and_nonempty_collections(cli, monkeypatch, payload):
    monkeypatch.setattr(
        "security_lakehouse.connectors_azure.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)),
    )
    assert cli.resources() == (payload["value"] if isinstance(payload, dict) else payload)


@pytest.mark.parametrize("payload", [[], None, {}, {"value": []}])
def test_subscription_probe_requires_an_object_with_identity(cli, monkeypatch, payload):
    monkeypatch.setattr(
        "security_lakehouse.connectors_azure.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)),
    )
    with pytest.raises(ValueError, match="Azure subscription"):
        cli.subscription()


def test_subscription_object_remains_supported(cli, monkeypatch):
    payload = {"id": "test-subscription", "state": "Enabled"}
    monkeypatch.setattr(
        "security_lakehouse.connectors_azure.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload)),
    )
    assert cli.subscription() == payload


@pytest.mark.parametrize("item", [None, 7, SimpleNamespace(as_dict=lambda: []), SimpleNamespace()])
def test_sdk_cannot_replace_unserializable_rows_with_empty_objects(item):
    with pytest.raises(ValueError, match="Azure SDK"):
        AzureClient._as_dict(item)


def test_sdk_preserves_serialized_objects():
    assert AzureClient._as_dict(SimpleNamespace(as_dict=lambda: {"id": "r"})) == {"id": "r"}


def test_failed_live_collection_preserves_last_successful_inventory(tmp_path, monkeypatch, cli):
    append_config_event(tmp_path, connector_id="azure-posture", state="enabled", actor="test")
    fixture = Path(__file__).parent / "fixtures/azure"
    connector_runner.run_connector_sync(tmp_path, connector_id="azure-posture", fixture_dir=fixture)
    raw = tmp_path / connector_runner.CONNECTOR_RAW_FILE
    previous = raw.read_bytes()
    posture = tmp_path / "gold/current_posture.json"
    previous_posture = posture.read_bytes()
    assert len(read_jsonl(raw)) == 7
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "test-subscription")
    monkeypatch.setattr("security_lakehouse.connectors_azure.build_azure_client", lambda *a, **k: cli)
    monkeypatch.setattr(
        "security_lakehouse.connectors_azure.subprocess.run", lambda *a, **k: SimpleNamespace(stdout="null")
    )
    with pytest.raises(connector_runner.ConnectorSyncError):
        connector_runner.run_connector_sync(tmp_path, connector_id="azure-posture", materialize=False)
    assert raw.read_bytes() == previous
    assert posture.read_bytes() == previous_posture
    run = latest_run(tmp_path, "azure-posture", kind="sync")
    assert run["result"] == "error"
    assert "secret" not in json.dumps(run)
