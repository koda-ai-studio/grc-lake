"""Evidence lineage stays exact, generation-scoped and read-only."""

import pytest

from security_lakehouse import api_v1, pipeline
from security_lakehouse.event_identity import event_identity
from security_lakehouse.generations import active_generation, generation_identity
from security_lakehouse.io import write_jsonl
from test_assurance_truth import event


@pytest.fixture
def sample(tmp_path):
    rows = [
        {**event(), "connector_id": connector, "safeguard_ids": ["SG-IDENTITY-001"]}
        for connector in ("first", "second")
    ]
    raw = tmp_path / "raw.jsonl"
    lake = tmp_path / "lake"
    write_jsonl(raw, rows)
    pipeline.run_pipeline(raw, lake, tenant_id="platform")
    return lake, raw, rows


def request(lake, identity, **params):
    return api_v1.handle_get(
        f"/api/v1/evidence/{identity}/lineage", {key: [str(value)] for key, value in params.items()}, lake
    )


def test_exact_connector_identity_and_minimal_provenance(sample):
    lake, _, rows = sample
    identity = event_identity(rows[0])
    status, body = request(lake, identity)
    assert status == 200
    data = body["data"]
    assert data["event_id"] == identity
    assert data["source"]["source_event_id"] == rows[0]["event_id"]
    assert data["source"]["connector_id"] == "first"
    assert data["source"]["source_account_id"] == "audit"
    assert data["integrity"]["verified"] is True
    assert data["integrity"]["external_authenticity"] == "not_established"
    assert len(data["raw_sha256"]) == 64
    assert data["links"]
    assert any(link["kind"] == "safeguard_result" for link in data["links"])
    assert body["meta"]["generation"] == generation_identity(lake)
    assert "fixture://" not in str(body) and str(lake) not in str(body)
    assert "raw" not in data
    assert request(lake, rows[0]["event_id"])[0] == 404


def test_result_paging_and_generation_precondition(sample):
    lake, raw, rows = sample
    identity = event_identity(rows[0])
    generation = generation_identity(lake)["generation_id"]
    status, first = request(lake, identity, limit=1, generation_id=generation)
    assert status == 200
    assert len(first["data"]["links"]) == 1
    assert first["meta"]["count"] >= 2
    second = request(lake, identity, limit=1, offset=1, generation_id=generation)[1]
    assert first["data"]["links"] != second["data"]["links"]
    write_jsonl(raw, [{**rows[0], "status": "fail"}])
    pipeline.run_pipeline(raw, lake, tenant_id="platform")
    assert request(lake, identity, generation_id=generation)[0] == 409


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"unknown": "field"}])
def test_invalid_bounds(sample, params):
    lake, _, rows = sample
    assert request(lake, event_identity(rows[0]), **params)[0] == 400


def test_corruption_and_unsealed_lakes_fail_closed(sample, tmp_path):
    lake, _, rows = sample
    identity = event_identity(rows[0])
    (active_generation(lake) / "bronze/raw_events.jsonl").write_text("{}\n")
    status, body = request(lake, identity)
    assert status == 409
    assert body["errors"][0]["code"] == "lineage_unavailable"
    assert request(tmp_path / "empty", identity)[0] == 409


def test_lineage_read_is_pinned_during_concurrent_publication(sample, monkeypatch):
    from security_lakehouse import evidence_lineage

    lake, raw, rows = sample
    before = generation_identity(lake)
    original = evidence_lineage._unique_event

    def interleaved(generation, identity):
        write_jsonl(raw, [{**rows[0], "status": "fail"}])
        pipeline.run_pipeline(raw, lake, tenant_id="platform")
        return original(generation, identity)

    monkeypatch.setattr(evidence_lineage, "_unique_event", interleaved)
    status, body = request(lake, event_identity(rows[0]))
    assert status == 200
    assert body["data"]["status"] == "pass"
    assert body["meta"]["generation"] == body["data"]["generation"] == before
    assert generation_identity(lake) != before


def test_authenticated_reader_cannot_select_another_tenants_lineage(tmp_path):
    from fastapi.testclient import TestClient

    from security_lakehouse import tenancy
    from security_lakehouse.server_app import create_app
    from test_tenant_isolation import _bearer, _provision_tenant

    app = create_app(tmp_path)
    first, token = _provision_tenant(app, "first")
    _, other = _provision_tenant(app, "other")
    raw = tmp_path / "raw.jsonl"
    identity = "source:record%2Fpart"
    write_jsonl(raw, [{**event(), "event_id": identity}])
    lake = tmp_path / tenancy.TENANTS_DIRNAME / first
    pipeline.run_pipeline(raw, lake, tenant_id=first)
    from urllib.parse import quote

    path = f"/api/v1/evidence/{quote(identity, safe='')}/lineage"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        response = client.get(path, headers=_bearer(token))
        assert response.status_code == 200, response.text
        assert response.json()["data"]["event_id"] == identity
        denied = client.get(path, headers=_bearer(other))
        assert denied.status_code == 409
        assert "raw_sha256" not in denied.text
        assert client.get(path + f"?tenant_id={first}", headers=_bearer(other)).status_code == 400


def test_mcp_preserves_generation_and_paging(sample):
    from test_mcp_hardening import _call

    lake, _, rows = sample
    from security_lakehouse.mcp_server import build_server

    result, _ = _call(build_server(lake), "get_evidence_lineage", event_id=event_identity(rows[0]), limit=1)
    assert result["meta"]["generation"] == generation_identity(lake)
    assert len(result["data"]["links"]) == 1


@pytest.mark.parametrize("duplicate_layer", ["bronze", "silver"])
def test_ambiguous_event_identity_fails_closed(sample, tmp_path, duplicate_layer):
    from security_lakehouse.evidence_lineage import LineageUnavailable, _unique_event
    from security_lakehouse.io import read_jsonl

    lake, _, rows = sample
    target = tmp_path / "invalid"
    for layer, name in (("bronze", "raw_events"), ("silver", "normalized_events")):
        records = read_jsonl(lake / layer / f"{name}.jsonl")
        if layer == duplicate_layer:
            records.append(records[0])
        write_jsonl(target / layer / f"{name}.jsonl", records)
    with pytest.raises(LineageUnavailable, match="ambiguous"):
        _unique_event(target, event_identity(rows[0]))


def test_remote_mcp_quotes_event_identity_and_keeps_generation_precondition(sample, monkeypatch):
    from security_lakehouse import mcp_server
    from test_mcp_hardening import _call

    lake, _, _ = sample
    monkeypatch.setattr(mcp_server, "_remote_api_configured", lambda: True)
    seen = []

    def remote(method, path, body=None, **params):
        seen.append((method, path, params))
        return {"data": {}, "meta": {"generation": {"generation_id": "saved"}}, "errors": []}

    monkeypatch.setattr(mcp_server, "_server_api_request", remote)
    result, _ = _call(mcp_server.build_server(lake), "get_evidence_lineage", event_id="a/%2F", generation_id="saved")
    assert seen == [
        ("GET", "/api/v1/evidence/a%2F%252F/lineage", {"limit": "25", "offset": "0", "generation_id": "saved"})
    ]
    assert result["meta"]["generation"]["generation_id"] == "saved"
