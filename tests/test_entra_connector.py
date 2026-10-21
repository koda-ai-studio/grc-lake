"""Entra metadata reuse: independent GRC evidence, failures and tenant boundaries."""

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from security_lakehouse import connector_runner
from security_lakehouse.connector_errors import ConnectorConfigError
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_entra import EntraClient, EntraFixtureClient, collect_entra_evidence
from security_lakehouse.evidence_provenance import contains_synthetic_evidence
from security_lakehouse.execution_mode import server_execution
from security_lakehouse.io import read_jsonl
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures/entra"
TENANT = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 10, 21, tzinfo=UTC)


def collect(client=None):
    return collect_entra_evidence(client or EntraFixtureClient(FIXTURE, tenant_id=TENANT), collected_at=NOW)


def test_joined_service_principal_managed_identity_and_orphan_are_metadata_only():
    rows = collect()
    assert validate_raw_events(rows) == []
    assert len(rows) == 3
    by_id = {r["attributes"]["identity_id"]: r for r in rows}
    service = by_id["sp-1"]["attributes"]
    assert service["credential_expires_at"] == "2026-11-01T00:00:00Z"
    assert service["credential_metadata_coverage"] == "complete"
    assert service["has_backing_app"] is True
    assert service["lifecycle_status"] == "active"
    assert by_id["managed-1"]["attributes"]["lifecycle_status"] == "inactive"
    assert by_id["orphan-1"]["attributes"]["orphan_app_registration"] is True
    assert all(r["controls"] == [] and r["status"] == "observed" for r in rows)
    assert all(r["attributes"]["last_used_at"] is None and r["attributes"]["scopes"] == [] for r in rows)
    assert "never-export" not in json.dumps(rows)


@pytest.mark.parametrize("endpoint", ["applications", "service_principals"])
def test_denied_listing_keeps_other_population_and_marks_join_uncertainty(monkeypatch, endpoint):
    client = EntraFixtureClient(FIXTURE, tenant_id=TENANT)

    def denied():
        raise PermissionError("secret-token https://private.invalid")

    monkeypatch.setattr(client, endpoint, denied)
    rows = collect(client)
    assert len([r for r in rows if r["attributes"].get("collection_gap")]) == 1
    identities = [r for r in rows if r["entity"]["asset_type"] == "non_human_identity"]
    assert identities
    if endpoint == "applications":
        assert all(r["attributes"]["has_backing_app"] is None for r in identities)
    else:
        assert all(r["attributes"]["orphan_app_registration"] is None for r in identities)
    assert "secret-token" not in json.dumps(rows)


@pytest.mark.parametrize("credentials", [[{"endDateTime": "bad-date"}], [{"endDateTime": "2026-01-01"}], None])
def test_unknown_expiry_is_not_invented_from_other_readable_dates(monkeypatch, credentials):
    client = EntraFixtureClient(FIXTURE, tenant_id=TENANT)
    apps = client.applications()
    apps[0]["passwordCredentials"] = credentials
    monkeypatch.setattr(client, "applications", lambda: apps)
    row = next(r for r in collect(client) if r["attributes"].get("identity_id") == "sp-1")
    assert row["attributes"]["credential_expires_at"] is None
    assert row["attributes"]["credential_metadata_coverage"] == "unknown"


def test_expiry_compares_instants_instead_of_lexical_offsets(monkeypatch):
    client = EntraFixtureClient(FIXTURE, tenant_id=TENANT)
    apps = client.applications()
    apps[0]["passwordCredentials"] = [{"endDateTime": "2026-11-01T00:30:00+02:00"}]
    monkeypatch.setattr(client, "applications", lambda: apps)
    row = next(r for r in collect(client) if r["attributes"].get("identity_id") == "sp-1")
    assert row["attributes"]["credential_expires_at"] == "2026-10-31T22:30:00Z"


def test_excluded_principal_still_establishes_that_an_application_is_not_orphaned(monkeypatch):
    client = EntraFixtureClient(FIXTURE, tenant_id=TENANT)
    principals = client.service_principals() + [
        {"id": "legacy-2", "appId": "orphan-client", "servicePrincipalType": "Legacy"}
    ]
    monkeypatch.setattr(client, "service_principals", lambda: principals)
    assert not any(r["attributes"].get("identity_id") == "orphan-1" for r in collect(client))


def test_missing_join_key_does_not_establish_missing_backing_app_or_orphan(monkeypatch):
    client = EntraFixtureClient(FIXTURE, tenant_id=TENANT)
    principals = client.service_principals()
    principals[0].pop("appId")
    monkeypatch.setattr(client, "service_principals", lambda: principals)
    rows = collect(client)
    service = next(r["attributes"] for r in rows if r["attributes"].get("identity_id") == "sp-1")
    app = next(r["attributes"] for r in rows if r["attributes"].get("identity_id") == "app-1")
    assert service["has_backing_app"] is None
    assert service["credential_metadata_coverage"] == "partial"
    assert app["orphan_app_registration"] is None


def test_ids_are_tenant_scoped_and_replay_materializes_synthetic_evidence(tmp_path):
    a, b = collect(), collect(EntraFixtureClient(FIXTURE, tenant_id="other-tenant"))
    assert {r["event_id"] for r in a}.isdisjoint(r["event_id"] for r in b)
    assert {r["entity"]["asset_id"] for r in a}.isdisjoint(r["entity"]["asset_id"] for r in b)
    append_config_event(
        tmp_path, connector_id="entra-identity", state="enabled", actor="test", credentials={"tenant_id": TENANT}
    )
    first = run_connector_sync(tmp_path, connector_id="entra-identity", fixture_dir=FIXTURE)
    second = run_connector_sync(tmp_path, connector_id="entra-identity", fixture_dir=FIXTURE, materialize=False)
    assert first.evidence_count == second.evidence_count == 3
    assert len(read_jsonl(tmp_path / CONNECTOR_RAW_FILE)) == 3
    assert contains_synthetic_evidence(tmp_path)


@pytest.mark.parametrize("payload", [None, {}, [{"id": ""}], [{"id": "x"}, {"id": "x"}]])
def test_malformed_listing_becomes_gap_not_empty_success(monkeypatch, payload):
    client = EntraFixtureClient(FIXTURE, tenant_id=TENANT)
    monkeypatch.setattr(client, "applications", lambda: payload)
    rows = collect(client)
    assert any(r["attributes"].get("collection_gap") for r in rows)


@pytest.mark.parametrize(
    "next_link",
    [
        "https://attacker.invalid/steal",
        "https://graph.microsoft.com:444/v1.0/apps",
        "https://user@graph.microsoft.com/v1.0/apps",
        23,
    ],
)
def test_graph_pagination_rejects_foreign_or_malformed_links_before_auth(monkeypatch, next_link):
    client = EntraClient(TENANT, token_provider=lambda: "must-not-escape")
    seen = []

    def page(url):
        seen.append(url)
        return {"value": [], "@odata.nextLink": next_link}

    monkeypatch.setattr(client, "_get_json", page)
    with pytest.raises(ValueError):
        client.applications()
    assert len(seen) == 1


def test_graph_v1_service_principal_select_uses_documented_properties(monkeypatch):
    client = EntraClient(TENANT, token_provider=lambda: "test-token")
    allowed = {
        "id",
        "appId",
        "displayName",
        "passwordCredentials",
        "keyCredentials",
        "servicePrincipalType",
        "accountEnabled",
    }

    def graph(url):
        selected = set(parse_qs(urlsplit(url).query)["$select"][0].split(","))
        assert selected <= allowed
        assert {"passwordCredentials", "keyCredentials", "appId"} <= selected
        return {"value": []}

    monkeypatch.setattr(client, "_get_json", graph)
    assert client.service_principals() == []


def test_hosted_sync_refuses_ambient_credentials_before_provider_access():
    with server_execution("tenant-a"), pytest.raises(ConnectorConfigError, match="client_id"):
        connector_runner._build_entra(
            connector_runner.SyncInputs(
                repo=None, fixture_dir=None, token_env="GRC_LAKE_TOKEN", env={}, credentials={"tenant_id": TENANT}
            )
        )


def test_hosted_sync_uses_configured_tenant_and_delegated_credential(monkeypatch):
    delegated = object()
    observed = []
    credentials = {"tenant_id": TENANT, "client_id": "app", "client_secret_ref": "GRC_LAKE_TENANT_A__AZURE_SECRET"}

    def credential(creds, env, *, label):
        assert creds == credentials and label == "entra-identity"
        return delegated

    def client(scope, **kwargs):
        observed.append((scope, kwargs["credential"]))
        return EntraFixtureClient(FIXTURE, tenant_id=scope)

    monkeypatch.setattr(connector_runner, "azure_credential", credential)
    monkeypatch.setattr(connector_runner, "EntraClient", client)
    with server_execution("tenant-a"):
        assert (
            len(
                connector_runner._build_entra(
                    connector_runner.SyncInputs(
                        repo=None, fixture_dir=None, token_env="GRC_LAKE_TOKEN", env={}, credentials=credentials
                    )
                )
            )
            == 3
        )
    assert observed == [(TENANT, delegated)]


def test_missing_fixture_populations_are_partial_not_empty_success(tmp_path):
    append_config_event(tmp_path, connector_id="entra-identity", state="enabled", actor="test")
    result = run_connector_sync(tmp_path, connector_id="entra-identity", fixture_dir=tmp_path, materialize=False)
    assert result.run["metadata"]["partial"] is True
    assert len(result.coverage_gaps) == 2
