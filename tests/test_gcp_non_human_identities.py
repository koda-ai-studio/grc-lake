"""GCP service-account metadata adapted from Agent-Bom's read-only inventory."""

import builtins
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_gcp import GCPClient, GCPFixtureClient, collect_gcp_evidence
from security_lakehouse.evidence_provenance import contains_synthetic_evidence
from security_lakehouse.io import read_jsonl
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures/gcp"
PROJECT = "fixture-project"
NOW = datetime(2026, 10, 21, tzinfo=UTC)


def collect(client=None):
    return collect_gcp_evidence(
        client or GCPFixtureClient(FIXTURE), collected_at=NOW, include_non_human_identities=True
    )


def identities(rows):
    return [r for r in rows if r["entity"]["asset_type"] == "non_human_identity"]


def test_service_account_metadata_preserves_unknown_usage_without_control_claims():
    rows = collect()
    assert validate_raw_events(rows) == []
    assert len(rows) == 9
    records = {r["attributes"]["identity_id"]: r for r in identities(rows)}
    account = records["service-100"]["attributes"]
    assert account["email"] == "ci-deployer@fixture-project.iam.gserviceaccount.com"
    assert account["lifecycle_status"] == "active"
    assert records["service-200"]["attributes"]["lifecycle_status"] == "inactive"
    assert account["project_bindings"] == [{"role": "roles/editor", "condition": None}]
    assert account["binding_coverage"] == "project_policy_observed"
    assert account["last_used_at"] is None and account["usage_coverage"] == "not_collected"
    assert account["permission_coverage"] == "not_collected"
    assert all(r["controls"] == [] and r["status"] == "observed" for r in identities(rows))
    assert "never-export" not in json.dumps(rows)


def test_opt_in_false_does_not_read_service_accounts(monkeypatch):
    client = GCPFixtureClient(FIXTURE)

    def denied():
        raise AssertionError("Optional IAM listing must not be called")

    monkeypatch.setattr(client, "service_accounts", denied)
    assert len(collect_gcp_evidence(client, collected_at=NOW)) == 7


def test_conditional_bindings_remain_conditional_metadata(monkeypatch):
    client = GCPFixtureClient(FIXTURE)
    condition = {"expression": "request.time < timestamp('2027-01-01T00:00:00Z')"}
    monkeypatch.setattr(
        client,
        "iam_bindings",
        lambda: [
            {
                "role": "roles/viewer",
                "members": ["serviceAccount:ci-deployer@fixture-project.iam.gserviceaccount.com"],
                "condition": condition,
            }
        ],
    )
    record = identities(collect(client))[0]["attributes"]
    assert record["project_bindings"] == [{"role": "roles/viewer", "condition": condition}]
    assert "effective_permissions" not in record


def test_binding_projection_is_deduplicated_and_stable_across_provider_order(monkeypatch):
    client = GCPFixtureClient(FIXTURE)
    member = "serviceAccount:ci-deployer@fixture-project.iam.gserviceaccount.com"
    bindings = [{"role": role, "members": [member]} for role in ["roles/editor", "roles/viewer", "roles/editor"]]
    monkeypatch.setattr(client, "iam_bindings", lambda: bindings)
    first = identities(collect(client))[0]["attributes"]["project_bindings"]
    bindings.reverse()
    # Reverse a non-palindromic order after retaining one duplicate.
    bindings.insert(0, bindings.pop(1))
    second = identities(collect(client))[0]["attributes"]["project_bindings"]
    assert len(first) == 2
    assert first == second


def test_denied_iam_policy_does_not_invent_an_unprivileged_service_account(monkeypatch):
    client = GCPFixtureClient(FIXTURE)

    def denied():
        raise CollectionGapError("Policy unavailable", collection="iam_bindings", reason="permission_denied")

    monkeypatch.setattr(client, "iam_bindings", denied)
    rows = collect(client)
    assert len(identities(rows)) == 2
    assert all(r["attributes"]["binding_coverage"] == "unavailable" for r in identities(rows))
    assert all(r["attributes"]["project_bindings"] == [] for r in identities(rows))


def test_denied_metadata_retains_core_evidence_and_static_gap(monkeypatch):
    client = GCPFixtureClient(FIXTURE)

    def denied():
        raise RuntimeError("never-export-token https://private.invalid")

    monkeypatch.setattr(client, "service_accounts", denied)
    rows = collect(client)
    assert len(rows) == 8
    gap = next(r for r in rows if r["attributes"].get("collection_gap"))
    assert gap["attributes"]["permission"] == "iam.serviceAccounts.list"
    assert "never-export" not in json.dumps(rows)


@pytest.mark.parametrize(
    "bad",
    [None, {}, [{"email": ""}], [{"email": "x@wrong-project.iam.gserviceaccount.com", "projectId": "wrong-project"}]],
)
def test_invalid_metadata_is_gap_not_empty_inventory(monkeypatch, bad):
    client = GCPFixtureClient(FIXTURE)
    monkeypatch.setattr(client, "service_accounts", lambda: bad)
    assert any(r["attributes"].get("collection_gap") for r in collect(client))


def test_malformed_display_metadata_cannot_export_nested_credential_fields(monkeypatch):
    client = GCPFixtureClient(FIXTURE)
    monkeypatch.setattr(
        client,
        "service_accounts",
        lambda: [
            {
                "email": "x@fixture-project.iam.gserviceaccount.com",
                "displayName": {"privateKeyData": "never-export-key"},
            }
        ],
    )
    rows = collect(client)
    assert "never-export-key" not in json.dumps(rows)


@pytest.mark.parametrize("enabled", [True, "true"])
def test_option_persists_replays_and_materializes_synthetic_rows(tmp_path, enabled):
    append_config_event(
        tmp_path,
        connector_id="gcp-posture",
        state="enabled",
        actor="test",
        options={"include_non_human_identities": enabled},
    )
    a = run_connector_sync(tmp_path, connector_id="gcp-posture", fixture_dir=FIXTURE)
    b = run_connector_sync(tmp_path, connector_id="gcp-posture", fixture_dir=FIXTURE, materialize=False)
    assert a.evidence_count == b.evidence_count == 9
    assert len(read_jsonl(tmp_path / CONNECTOR_RAW_FILE)) == 9
    assert contains_synthetic_evidence(tmp_path)


def test_invalid_option_fails_before_collection(tmp_path):
    append_config_event(
        tmp_path,
        connector_id="gcp-posture",
        state="enabled",
        actor="test",
        options={"include_non_human_identities": "maybe"},
    )
    with pytest.raises(ConnectorSyncError, match="include_non_human_identities"):
        run_connector_sync(tmp_path, connector_id="gcp-posture", fixture_dir=FIXTURE)


def test_duplicate_native_ids_do_not_silently_upsert_one_identity(monkeypatch):
    client = GCPFixtureClient(FIXTURE)
    accounts = client.service_accounts()
    accounts[1]["uniqueId"] = accounts[0]["uniqueId"]
    monkeypatch.setattr(client, "service_accounts", lambda: accounts)
    rows = collect(client)
    assert not identities(rows)
    assert any(r["attributes"].get("collection_gap") for r in rows)


def test_missing_native_id_falls_back_to_email_and_missing_status_stays_unknown(monkeypatch):
    client = GCPFixtureClient(FIXTURE)
    monkeypatch.setattr(
        client, "service_accounts", lambda: [{"email": "unknown@fixture-project.iam.gserviceaccount.com"}]
    )
    account = identities(collect(client))[0]["attributes"]
    assert account["identity_id"] == account["email"]
    assert account["lifecycle_status"] == "unknown"


def test_missing_optional_iam_sdk_is_a_named_gap(monkeypatch):
    original = builtins.__import__

    def import_module(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google.cloud" and "iam_admin_v1" in fromlist:
            raise ImportError("IAM SDK not installed")
        return original(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", import_module)
    client = object.__new__(GCPClient)
    with pytest.raises(CollectionGapError) as caught:
        client.service_accounts()
    assert caught.value.reason == "client_unavailable"


@pytest.mark.parametrize("repeat", [False, True])
def test_sdk_pages_are_scoped_delegated_and_guarded_against_loops(monkeypatch, repeat):
    iam = pytest.importorskip("google.cloud.iam_admin_v1")
    delegated = object()
    requests = []

    class IAM:
        def __init__(self, *, credentials):
            assert credentials is delegated

        def list_service_accounts(self, *, request):
            requests.append((request.name, request.page_size, request.page_token))
            account = iam.ServiceAccount(
                email=f"sa{len(requests)}@fixture-project.iam.gserviceaccount.com",
                unique_id=str(len(requests)),
                project_id=PROJECT,
            )
            response = iam.ListServiceAccountsResponse(
                accounts=[account], next_page_token="next" if len(requests) == 1 or repeat else ""
            )
            return SimpleNamespace(pages=[response])

    monkeypatch.setattr(iam, "IAMClient", IAM)
    client = object.__new__(GCPClient)
    client.project_id, client._credentials = PROJECT, delegated
    if repeat:
        with pytest.raises(CollectionGapError):
            client.service_accounts()
    else:
        assert len(client.service_accounts()) == 2
    assert requests == [(f"projects/{PROJECT}", 100, ""), (f"projects/{PROJECT}", 100, "next")]
