"""Direct provider evidence adapted from Agent-Bom's tested Okta NHI cases."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_okta import OktaFixtureClient, collect_okta_evidence
from security_lakehouse.evidence_provenance import contains_synthetic_evidence
from security_lakehouse.io import read_jsonl
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures/okta"
NOW = datetime(2026, 10, 21, tzinfo=UTC)


def collect(client=None):
    return collect_okta_evidence(
        client or OktaFixtureClient(FIXTURE), collected_at=NOW, tenant_id="tenant-a", include_non_human_identities=True
    )


def test_service_filtering_and_metadata_do_not_assert_permissions_or_compliance():
    rows = collect()
    assert validate_raw_events(rows) == []
    nhi = [row for row in rows if row["entity"]["asset_type"] == "non_human_identity"]
    assert len(nhi) == 2
    by_type = {row["attributes"]["identity_type"]: row for row in nhi}
    service = by_type["service_account"]["attributes"]
    assert service["identity_id"] == "service-app-1"
    assert service["grant_types"] == ["client_credentials", "read_file"]
    assert service["scopes"] == []
    assert service["scope_coverage"] == "not_collected"
    assert service["client_authentication"] == "private_key_jwt"
    assert service["dpop_bound_access_tokens"] is True
    token = by_type["api_token"]["attributes"]
    assert token["owner"] == "synthetic-owner-1"
    assert token["credential_expires_at"] == "2026-12-01T00:00:00Z"
    assert all(row["attributes"]["last_used_at"] is None for row in nhi)
    assert all(row["controls"] == [] and row["status"] == "observed" for row in nhi)
    assert "never-export" not in json.dumps(rows)


def test_existing_identity_collection_does_not_request_additional_permissions(monkeypatch):
    client = OktaFixtureClient(FIXTURE)

    def denied():
        raise AssertionError("NHI endpoints must be opt-in")

    monkeypatch.setattr(client, "list_oauth2_service_apps", denied)
    monkeypatch.setattr(client, "list_api_tokens", denied)
    assert len(collect_okta_evidence(client, collected_at=NOW)) == 8


def test_provider_failure_keeps_other_evidence_and_records_static_coverage_gap(monkeypatch):
    client = OktaFixtureClient(FIXTURE)

    def denied():
        raise RuntimeError("secret-token-value https://internal.example/private")

    monkeypatch.setattr(client, "list_api_tokens", denied)
    rows = collect(client)
    assert any(row["attributes"].get("identity_type") == "service_account" for row in rows)
    gaps = [row for row in rows if row["attributes"].get("collection_gap")]
    assert len(gaps) == 1
    assert gaps[0]["attributes"]["permission"] == "okta.apiTokens.read"
    assert gaps[0]["status"] == "not_evaluated"
    assert "secret-token-value" not in json.dumps(rows)
    assert "internal.example" not in json.dumps(rows)


def test_denied_metadata_read_marks_sync_partial_and_keeps_existing_evidence(tmp_path, monkeypatch):
    def denied(self):
        raise PermissionError("credential-must-not-escape")

    monkeypatch.setattr(OktaFixtureClient, "list_api_tokens", denied)
    append_config_event(
        tmp_path,
        connector_id="okta-identity",
        state="enabled",
        actor="test",
        options={"include_non_human_identities": True},
    )
    result = run_connector_sync(tmp_path, connector_id="okta-identity", fixture_dir=FIXTURE)
    assert result.result == "ok"
    assert result.run["metadata"]["partial"] is True
    assert result.coverage_gaps
    rows = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    assert len(rows) == 10
    assert any(row["attributes"].get("identity_type") == "service_account" for row in rows)
    assert any(row["event_type"] == "okta.identity.user_access" for row in rows)
    assert "credential-must-not-escape" not in json.dumps(rows)


@pytest.mark.parametrize("bad", [None, [], {"grant_types": [{"client_secret": "never-export"}]}])
def test_malformed_application_metadata_is_unknown_not_an_empty_complete_inventory(monkeypatch, bad):
    client = OktaFixtureClient(FIXTURE)
    monkeypatch.setattr(client, "list_oauth2_service_apps", lambda: [{"id": "app", "settings": {"oauthClient": bad}}])
    rows = collect(client)
    assert any(row["attributes"].get("collection_gap") for row in rows)
    assert any(row["attributes"].get("identity_type") == "api_token" for row in rows)
    assert "never-export" not in json.dumps(rows)


def test_identical_native_ids_in_different_orgs_have_distinct_identity_and_evidence_ids():
    a = collect()
    b = collect(OktaFixtureClient(FIXTURE, org_url="https://other.okta.com"))

    def identities(rows):
        return [row for row in rows if row["entity"]["asset_type"] == "non_human_identity"]

    assert {row["event_id"] for row in identities(a)}.isdisjoint(row["event_id"] for row in identities(b))
    assert {row["entity"]["asset_id"] for row in identities(a)}.isdisjoint(
        row["entity"]["asset_id"] for row in identities(b)
    )


@pytest.mark.parametrize("native_ids", [("service-App-1", "service-app-1"), ("service/app", "service-app")])
def test_distinct_native_ids_do_not_collide_after_event_id_slugging(monkeypatch, native_ids):
    client = OktaFixtureClient(FIXTURE)
    template = client.list_oauth2_service_apps()[0]
    monkeypatch.setattr(client, "list_oauth2_service_apps", lambda: [{**template, "id": key} for key in native_ids])
    rows = [row for row in collect(client) if row["attributes"].get("identity_type") == "service_account"]
    assert len({row["event_id"] for row in rows}) == 2
    assert len({row["evidence"]["evidence_id"] for row in rows}) == 2


@pytest.mark.parametrize("enabled", [True, "true"])
def test_configured_sync_persists_replays_and_materializes_nhi_evidence(tmp_path, enabled):
    append_config_event(
        tmp_path,
        connector_id="okta-identity",
        state="enabled",
        actor="test",
        options={"include_non_human_identities": enabled},
    )
    first = run_connector_sync(tmp_path, connector_id="okta-identity", fixture_dir=FIXTURE)
    second = run_connector_sync(tmp_path, connector_id="okta-identity", fixture_dir=FIXTURE, materialize=False)
    assert first.evidence_count == second.evidence_count == 10
    assert len(read_jsonl(tmp_path / CONNECTOR_RAW_FILE)) == 10
    assert first.materialized
    normalized = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    nhi = [row for row in normalized if row["asset_type"] == "non_human_identity"]
    assert len(nhi) == 2
    assert all(row["control_ids"] == [] for row in nhi)
    assert contains_synthetic_evidence(tmp_path)


def test_invalid_opt_in_is_rejected_before_collection(tmp_path):
    append_config_event(
        tmp_path,
        connector_id="okta-identity",
        state="enabled",
        actor="test",
        options={"include_non_human_identities": "maybe"},
    )
    with pytest.raises(ConnectorSyncError, match="include_non_human_identities"):
        run_connector_sync(tmp_path, connector_id="okta-identity", fixture_dir=FIXTURE)


@pytest.mark.parametrize("disabled", [False, "false"])
def test_disabled_option_keeps_existing_evidence_count(tmp_path, disabled):
    append_config_event(
        tmp_path,
        connector_id="okta-identity",
        state="enabled",
        actor="test",
        options={"include_non_human_identities": disabled},
    )
    result = run_connector_sync(tmp_path, connector_id="okta-identity", fixture_dir=FIXTURE, materialize=False)
    assert result.evidence_count == 8


def test_missing_metadata_fixtures_are_coverage_gaps_not_empty_lists(tmp_path):
    client = OktaFixtureClient(FIXTURE)
    client.fixture = tmp_path
    rows = collect(client)
    assert len(rows) == 2
    assert all(row["attributes"].get("collection_gap") is True for row in rows)
