"""Explain frozen coverage blockers without changing compliance truth."""

from copy import deepcopy

import pytest

from security_lakehouse.ccf_gaps import requirement_gaps
from test_ccf_operational_assessment import assessment, normalized


def only(data):
    before = deepcopy(data)
    rows = requirement_gaps(data)
    assert data == before
    return rows[0]


def test_passing_requirement_has_no_gap_and_does_not_claim_complete_population():
    data = assessment([normalized()])
    row = only(data)
    assert row["status"] == "pass"
    assert row["gap_codes"] == []
    assert row["population_completeness"] == "not_established"


def test_pending_review_is_separate_from_failing_evidence():
    row = only(assessment([normalized()], states=("proposed",)))
    assert row["gap_codes"] == ["mapping_review_pending", "no_reviewed_implementation"]
    assert row["pending_mapping_count"] == 1
    assert row["status"] == "not_evaluated"
    assert "safeguard_failed" not in row["gap_codes"]


def test_all_required_safeguards_and_unassessed_assets_are_explained():
    row = only(assessment([normalized()], states=("maintainer_reviewed", "maintainer_reviewed")))
    assert {"safeguard_not_evaluated", "unassessed_assets"} <= set(row["gap_codes"])
    assert row["blocking_safeguards"] == [
        {"safeguard_id": "SG-1", "status": "not_evaluated", "unassessed_asset_count": 1, "invalid_binding_count": 0}
    ]


@pytest.mark.parametrize("status,code", [("failed", "safeguard_failed"), ("observed", "safeguard_not_evaluated")])
def test_result_blockers_keep_original_verdict(status, code):
    data = assessment([normalized(status=status)])
    row = only(data)
    assert code in row["gap_codes"]
    assert row["status"] == data["requirements"][0]["status"]


def test_unverified_review_log_and_context_only_are_not_approved_coverage():
    row = only(assessment([normalized()], verified=False))
    assert "review_log_unverified" in row["gap_codes"]
    data = assessment([normalized()], states=("rejected",))
    data["requirements"][0]["contextual_mappings"] = [{"safeguard_id": "SG-0", "role": "supporting"}]
    row = only(data)
    assert row["gap_codes"] == ["context_only", "no_reviewed_implementation"]
    assert row["status"] == "unmapped"


def test_stale_requirement_does_not_invent_missing_evidence_types():
    data = assessment([normalized()])
    data["requirements"][0]["status"] = "stale"
    row = only(data)
    assert row["gap_codes"] == ["requirement_stale"]
    assert "missing_evidence_types" not in row


def test_missing_referenced_safeguard_detail_is_explicit():
    data = assessment([normalized()])
    data["safeguards"] = []
    row = only(data)
    assert row["gap_codes"] == ["assessment_detail_missing"]
    assert row["status"] == "pass"  # Diagnostics never rewrite stored results.


@pytest.fixture
def lake(tmp_path):
    from security_lakehouse.io import write_jsonl
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import event

    raw = tmp_path / "events.jsonl"
    write_jsonl(raw, [{**event(), "safeguard_ids": ["SG-IDENTITY-001"]}])
    target = tmp_path / "lake"
    run_pipeline(raw, target)
    return target


def test_api_pages_filter_gaps_and_preserve_generation(lake, monkeypatch):
    from security_lakehouse import api_v1
    from security_lakehouse.generations import generation_identity

    def forbidden(*args):
        raise AssertionError("gap diagnostics must not load all asset evidence")

    monkeypatch.setattr(api_v1, "_ccf_assessment", forbidden)
    status, first = api_v1.handle_get("/api/v1/ccf/requirement-gaps", {"limit": ["2"]}, lake)
    assert status == 200
    assert len(first["data"]) == 2
    assert first["meta"]["count"] > 2
    assert first["meta"]["generation"] == generation_identity(lake)
    assert first["meta"]["population_completeness"] == "not_established"
    status, second = api_v1.handle_get("/api/v1/ccf/requirement-gaps", {"limit": ["2"], "offset": ["2"]}, lake)
    assert status == 200
    assert {r["control_id"] for r in first["data"]}.isdisjoint(r["control_id"] for r in second["data"])
    status, filtered = api_v1.handle_get(
        "/api/v1/ccf/requirement-gaps", {"gap_codes": ["mapping_review_pending"], "framework_id": ["soc2"]}, lake
    )
    assert status == 200
    assert filtered["data"]
    assert all("mapping_review_pending" in r["gap_codes"] and r["framework_id"] == "soc2" for r in filtered["data"])
    assert api_v1.handle_get("/api/v1/ccf/requirement-gaps", {"generation_id": ["old"]}, lake)[0] == 409
    assert api_v1.handle_get("/api/v1/ccf/requirement-gaps", {"unknown": ["x"]}, lake)[0] == 400


def test_missing_projection_and_legacy_lake_do_not_fabricate_gaps(lake, tmp_path):
    from security_lakehouse import api_v1

    assert api_v1.handle_get("/api/v1/ccf/requirement-gaps", {}, tmp_path / "empty")[0] == 409
    (lake / "mart/security_lakehouse.sqlite").write_bytes(b"broken")
    assert api_v1.handle_get("/api/v1/ccf/requirement-gaps", {}, lake)[0] == 409


def test_api_stays_with_pinned_summary_during_publication(lake, tmp_path, monkeypatch):
    from security_lakehouse import api_v1, ccf_queries
    from security_lakehouse.generations import generation_identity
    from security_lakehouse.io import write_jsonl
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import event

    before = generation_identity(lake)
    original = ccf_queries.read_summary
    raw = tmp_path / "next.jsonl"
    write_jsonl(raw, [event("failed")])

    def interleaved(target):
        run_pipeline(raw, target)
        return original(target)

    monkeypatch.setattr(ccf_queries, "read_summary", interleaved)
    assert api_v1.handle_get("/api/v1/ccf/requirement-gaps", {}, lake)[1]["meta"]["generation"] == before
    assert generation_identity(lake) != before


def test_mcp_keeps_gap_page_metadata(lake):
    from security_lakehouse.generations import generation_identity
    from security_lakehouse.mcp_server import build_server
    from test_mcp_hardening import _call

    result, _ = _call(build_server(lake), "list_ccf_requirement_gaps", limit=2)
    assert result["meta"]["generation"] == generation_identity(lake)
    assert len(result["data"]) == 2


def test_server_gap_pages_require_auth_and_stay_in_tenant_scope(tmp_path):
    from fastapi.testclient import TestClient

    from security_lakehouse import tenancy
    from security_lakehouse.io import write_jsonl
    from security_lakehouse.pipeline import run_pipeline
    from security_lakehouse.server_app import create_app
    from test_assurance_truth import event
    from test_tenant_isolation import _bearer, _provision_tenant

    app = create_app(tmp_path)
    owner, token = _provision_tenant(app, "owner")
    _, other = _provision_tenant(app, "other")
    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [event()])
    run_pipeline(raw, tmp_path / tenancy.TENANTS_DIRNAME / owner, tenant_id=owner)
    path = "/api/v1/ccf/requirement-gaps"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_bearer(token)).status_code == 200
        response = client.get(path, headers=_bearer(other))
        assert response.status_code == 409
        assert "SOC2-CC6.1" not in response.text
