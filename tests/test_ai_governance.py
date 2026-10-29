"""AI governance platform API and aggregation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from security_lakehouse.ai_governance import build_ai_governance_status, list_ai_inventory
from security_lakehouse.db.repository import create_api_key, create_tenant, create_user
from security_lakehouse.server_app import create_app
from test_api_v1 import _seed_lake, _write_jsonl


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_ai_events(lake: Path) -> None:
    _seed_lake(lake)
    _write_jsonl(
        lake / "silver" / "normalized_events.jsonl",
        [
            {
                "event_id": "evt-ai-001",
                "event_time": "2026-05-20T15:05:00Z",
                "event_type": "ai.model_inventory",
                "control_ids": ["NIST-AI-RMF-MAP-1.5", "ISO42001-8.1", "EU-AI-ACT-Art.10"],
                "asset_id": "model:customer-support-reranker:v3",
                "asset_owner": "ai-security",
                "asset_type": "ai_model",
                "environment": "prod",
                "source": "model-registry",
                "status": "passed",
                "severity": "low",
                "severity_score": 10,
                "evidence_ref": "s3://evidence/model-card.json",
                "raw_sha256": "abc",
                "attributes": {"model_card": True, "lineage_complete": True},
            },
            {
                "event_id": "evt-ai-002",
                "event_time": "2026-05-22T08:30:00Z",
                "event_type": "model.lineage",
                "control_ids": ["NIST-AI-RMF-MAP-1.5"],
                "asset_id": "model:customer-support-reranker:v3",
                "asset_owner": "ai-security",
                "asset_type": "ai_model",
                "environment": "prod",
                "source": "model-registry",
                "status": "passed",
                "severity": "info",
                "severity_score": 5,
                "evidence_ref": "s3://evidence/lineage.json",
                "raw_sha256": "def",
            },
            {
                "event_id": "evt-ai-003",
                "event_time": "2026-05-20T13:11:00Z",
                "event_type": "runtime.tool_call",
                "control_ids": ["NIST-AI-RMF-MANAGE-4.3", "EU-AI-ACT-Art.14"],
                "asset_id": "agent:finance-research",
                "asset_owner": "ai-security",
                "asset_type": "ai_agent",
                "environment": "prod",
                "source": "runtime-gateway",
                "status": "blocked",
                "severity": "high",
                "severity_score": 80,
                "evidence_ref": "s3://evidence/runtime.json",
                "raw_sha256": "ghi",
            },
            {
                "event_id": "evt-ai-004",
                "event_time": "2026-05-20T16:00:00Z",
                "event_type": "repository.ai_artifact",
                "control_ids": ["NIST-AI-RMF-MAP-1.5", "EU-AI-ACT-Art.10", "ISO42001-8.1"],
                "asset_id": "github:repo:acme/ml-platform",
                "asset_owner": "ai-security",
                "asset_type": "repository",
                "environment": "public",
                "source": "github-public-repo",
                "status": "observed",
                "severity": "info",
                "severity_score": 0,
                "evidence_ref": "https://github.com/acme/ml-platform",
                "raw_sha256": "jkl",
                "attributes": {"paths": ["modelcard.md"], "path_count": 1},
            },
        ],
    )


def test_build_ai_governance_status_fixture(tmp_path: Path) -> None:
    _seed_ai_events(tmp_path)
    data = build_ai_governance_status(lake=tmp_path)
    assert data["inventory"]["models"] >= 1
    assert data["inventory"]["agents"] >= 1
    assert data["events"]["model_inventory"] >= 1
    assert data["events"]["model_lineage"] >= 1
    assert data["events"]["agent_runtime"] >= 1
    assert data["events"]["repo_artifacts"] >= 1
    assert data["frameworks_total"] == 3
    assert data["aibom"]["shipped"] is True
    assert data["evidence_loops"]["inventory_events"] is True
    assert data["evidence_loops"]["lineage_events"] is True


def test_list_ai_inventory_fixture(tmp_path: Path) -> None:
    _seed_ai_events(tmp_path)
    rows = list_ai_inventory(lake=tmp_path)
    asset_ids = {row["asset_id"] for row in rows}
    assert "model:customer-support-reranker:v3" in asset_ids
    assert "agent:finance-research" in asset_ids


def test_ai_governance_api(tmp_path: Path) -> None:
    _seed_ai_events(tmp_path)
    app = create_app(tmp_path)
    client = TestClient(app)
    with app.state.sessionmaker() as session:
        tenant = create_tenant(session, slug="ai-gov", name="AI Gov")
        user = create_user(session, tenant_id=tenant.id, email="read@ai-gov.test", role="read_only")
        _key, token = create_api_key(session, tenant_id=tenant.id, user_id=user.id)
        session.commit()
    resp = client.get("/api/v1/platform/ai-governance", headers=_bearer(token))
    assert resp.status_code == HTTPStatus.OK
    body = resp.json()["data"]
    assert body["governance_score"] >= 0
    assert len(body["frameworks"]) == 3

    inv = client.get("/api/v1/platform/ai-governance/inventory", headers=_bearer(token))
    assert inv.status_code == HTTPStatus.OK
    assert len(inv.json()["data"]) >= 2


def test_build_ai_governance_empty_lake_gaps(tmp_path: Path) -> None:
    _seed_lake(tmp_path)
    _write_jsonl(
        tmp_path / "silver" / "normalized_events.jsonl",
        [
            {
                "event_id": "evt-non-ai",
                "event_time": "2026-05-20T13:01:00Z",
                "event_type": "identity.access_review",
                "control_ids": ["SOC2-CC6.1"],
                "asset_id": "aws:iam:role/admin",
                "asset_owner": "security-platform",
                "asset_type": "iam_role",
                "environment": "prod",
                "source": "okta",
                "status": "open",
                "severity": "high",
                "severity_score": 80,
                "evidence_ref": "s3://evidence/evt-non-ai.json",
                "raw_sha256": "abc",
            }
        ],
    )
    data = build_ai_governance_status(lake=tmp_path)
    assert data["state"] == "needs_work"
    gap_ids = {gap["id"] for gap in data["gaps"]}
    assert gap_ids == {"model_inventory", "model_lineage", "model_cards", "agent_governance"}
    assert data["evidence_loops"]["inventory_events"] is False
    assert data["aibom"]["shipped"] is True


def test_complete_inventory_without_passing_controls_is_not_governed(tmp_path: Path) -> None:
    _seed_ai_events(tmp_path)
    data = build_ai_governance_status(lake=tmp_path)
    assert data["governance_score"] < 85
    assert data["state"] != "governed"
    assert data["gaps"] == []


def test_list_ai_inventory_pagination(tmp_path: Path) -> None:
    _seed_ai_events(tmp_path)
    page = list_ai_inventory(lake=tmp_path, limit=1, offset=0)
    assert len(page) == 1
    rest = list_ai_inventory(lake=tmp_path, limit=10, offset=1)
    assert page[0]["asset_id"] != rest[0]["asset_id"]


def test_ai_governance_api_requires_auth(tmp_path: Path) -> None:
    _seed_ai_events(tmp_path)
    app = create_app(tmp_path)
    client = TestClient(app)
    resp = client.get("/api/v1/platform/ai-governance")
    assert resp.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_evidence_presence_does_not_make_ai_posture_pass(status):
    from security_lakehouse.ai_governance import _framework_rows

    control_id = "NIST-AI-RMF-GOVERN-1.1"
    rows = _framework_rows(
        controls=[{"control_id": control_id, "status": status}],
        events=[{"control_ids": [control_id], "status": "open"}],
    )
    row = next(r for r in rows if r["framework_id"] == "nist-ai-rmf")
    assert row["evidence_pct"] == 100.0  # Evidence exists; it does not prove a pass.
    assert row["score"] == 0
    assert row["passing_controls"] == 0


def test_ai_posture_separates_pass_fail_and_unevaluated_controls():
    from security_lakehouse.ai_governance import _framework_rows

    rows = _framework_rows(
        controls=[
            {"control_id": "NIST-AI-RMF-GOVERN-1.1", "status": "pass"},
            {"control_id": "NIST-AI-RMF-GOVERN-1.2", "status": "fail"},
        ],
        events=[
            {"control_ids": ["NIST-AI-RMF-GOVERN-1.3"], "status": "observed"},
            {
                "control_ids": ["NIST-AI-RMF-GOVERN-1.1"],
                "status": "pass",
                "event_time": datetime.now(UTC).isoformat(),
                "evidence_ref": "fixture://current",
            },
        ],
    )
    row = next(r for r in rows if r["framework_id"] == "nist-ai-rmf")
    assert row["score"] == 33
    assert row["passing_controls"] == 1
    assert row["failing_controls"] == 1
    assert row["unevaluated_controls"] == 1


def test_ai_frameworks_use_catalog_ids_and_the_safeguard_mapped_count():
    from security_lakehouse.ai_governance import _framework_rows
    from security_lakehouse.safeguards import coverage_by_framework

    rows = {row["framework_id"]: row for row in _framework_rows(controls=[], events=[])}
    coverage = coverage_by_framework()["frameworks"]

    assert set(rows) == {"nist-ai-rmf", "iso-42001-2023", "eu-ai-act-2024-1689"}
    for framework_id, row in rows.items():
        # The same numbers the Frameworks page shows for the pack.
        assert row["requirements"] == coverage[framework_id]["controls"] > 0
        assert row["mapped_requirements"] == coverage[framework_id]["covered"]
        assert row["mapped_pct"] == coverage[framework_id]["coverage_pct"]
        # Nothing evaluated is "not evaluated", not a 0% score.
        assert row["score"] is None


def test_unevaluated_ai_frameworks_do_not_drag_the_governance_score(tmp_path: Path) -> None:
    from security_lakehouse.ai_governance import _framework_score

    rows = [{"score": 90, "controls_with_evidence": 10, "passing_controls": 9}, {"score": None}, {"score": None}]
    assert _framework_score(rows) == 90
    assert _framework_score([{"score": None}]) == 0


def test_inferred_model_inventory_is_not_reported_as_missing(tmp_path: Path) -> None:
    _seed_lake(tmp_path)
    _write_jsonl(
        tmp_path / "silver" / "normalized_events.jsonl",
        [
            {
                "event_id": "evt-lineage",
                "event_time": "2026-05-20T13:00:00Z",
                "event_type": "model.lineage",
                "control_ids": [],
                "asset_id": "model:fraud-scorer",
                "asset_owner": "ml-platform",
                "asset_type": "ai_model",
                "environment": "prod",
                "source": "mlflow",
                "status": "observed",
                "severity": "low",
                "severity_score": 10,
                "evidence_ref": "s3://evidence/evt-lineage.json",
                "raw_sha256": "abc",
            }
        ],
    )
    data = build_ai_governance_status(lake=tmp_path)
    assert data["inventory"]["models"] == 1
    assert "model_inventory" not in {gap["id"] for gap in data["gaps"]}


@pytest.mark.parametrize("signal", ["false", "true", "unknown", 1, {"present": False}, [True]])
def test_inventory_requires_explicit_boolean_signals(tmp_path: Path, signal) -> None:
    _write_jsonl(
        tmp_path / "silver" / "normalized_events.jsonl",
        [
            {
                "asset_id": "model:unverified",
                "asset_type": "model",
                "event_type": "model.inventory",
                "attributes": {"model_card": signal, "lineage_complete": signal},
            }
        ],
    )
    item = list_ai_inventory(lake=tmp_path)[0]
    assert item["model_card"] is False
    assert item["lineage_complete"] is False
    status = build_ai_governance_status(lake=tmp_path)
    assert status["inventory"]["with_model_card"] == 0
    assert status["inventory"]["with_lineage"] == 0


def test_event_inventory_preserves_matching_imported_model_card(tmp_path: Path) -> None:
    import json

    from security_lakehouse.aibom import import_aibom

    source = tmp_path / "bom.json"
    source.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.7",
                "components": [
                    {
                        "type": "machine-learning-model",
                        "bom-ref": "model:documented",
                        "name": "Documented model",
                        "modelCard": {"bom-ref": "card:documented"},
                    }
                ],
            }
        )
    )
    import_aibom(input_path=source, lake=tmp_path)
    _write_jsonl(
        tmp_path / "silver" / "normalized_events.jsonl",
        [
            {
                "asset_id": "model:documented",
                "asset_type": "model",
                "event_type": "model.lineage",
                "source": "registry",
                "asset_owner": "ML team",
                "control_ids": ["NIST-AI-RMF-MAP-1.5"],
            },
            {"asset_id": "model:other", "asset_type": "model", "event_type": "model.inventory"},
        ],
    )
    items = {row["asset_id"]: row for row in list_ai_inventory(lake=tmp_path)}
    assert items["model:documented"]["model_card"] is True
    assert items["model:documented"]["owner"] == "ML team"
    assert set(items["model:documented"]["sources"]) == {"registry", "cyclonedx-1.7"}
    assert set(items["model:documented"]["event_types"]) == {"model.lineage", "aibom.inventory"}
    assert items["model:other"]["model_card"] is False
    status = build_ai_governance_status(lake=tmp_path)
    assert status["inventory"]["with_model_card"] == 1
    assert status["inventory"]["models"] == 2


def test_inventory_keeps_colliding_source_account_assets_separate(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "silver" / "normalized_events.jsonl",
        [
            {
                "asset_id": "model:shared",
                "asset_type": "model",
                "event_type": "model.inventory",
                "tenant_id": "source-a",
                "source_account_id": "source-a",
                "asset_owner": "Team A",
                "attributes": {"model_card": True},
                "control_ids": ["control-a"],
            },
            {
                "asset_id": "model:shared",
                "asset_type": "model",
                "event_type": "model.inventory",
                "tenant_id": "source-b",
                "source_account_id": "source-b",
                "asset_owner": "Team B",
                "attributes": {"model_card": False},
                "control_ids": ["control-b"],
            },
        ],
    )
    _write_jsonl(
        tmp_path / "gold" / "asset_risk.jsonl",
        [
            {"asset_id": "model:shared", "asset_name": "Unscoped display name"},
        ],
    )
    rows = list_ai_inventory(lake=tmp_path)
    assert len(rows) == 2
    by_account = {row["source_account_id"]: row for row in rows}
    assert by_account["source-a"]["model_card"] is True
    assert by_account["source-b"]["model_card"] is False
    assert by_account["source-b"]["owner"] == "Team B"
    assert by_account["source-b"]["control_ids"] == ["control-b"]
    assert all("asset_name" not in row for row in rows)
    assert build_ai_governance_status(lake=tmp_path)["inventory"]["models"] == 2


def test_unscoped_import_cannot_document_a_source_account_model(tmp_path: Path) -> None:
    import json

    from security_lakehouse.aibom import import_aibom

    source = tmp_path / "bom.json"
    source.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.7",
                "components": [
                    {
                        "type": "machine-learning-model",
                        "bom-ref": "model:same",
                        "name": "Model",
                        "modelCard": {"bom-ref": "card:same"},
                    }
                ],
            }
        )
    )
    import_aibom(input_path=source, lake=tmp_path)
    _write_jsonl(
        tmp_path / "silver" / "normalized_events.jsonl",
        [
            {"asset_id": "model:same", "asset_type": "model", "event_type": "model.inventory", "tenant_id": "source-a"},
        ],
    )
    rows = list_ai_inventory(lake=tmp_path)
    assert len(rows) == 2
    assert {row["source_account_id"]: row["model_card"] for row in rows} == {"": True, "source-a": False}


def test_scoped_import_documents_only_exact_account_asset_pair(tmp_path: Path) -> None:
    import json

    from security_lakehouse.aibom import import_aibom

    source = tmp_path / "bom.json"
    source.write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.7",
                "components": [
                    {
                        "type": "machine-learning-model",
                        "bom-ref": "model:same",
                        "name": "Model",
                        "modelCard": {"bom-ref": "card:same"},
                        "source_account_id": "source-b",
                    }
                ],
            }
        )
    )
    import_aibom(input_path=source, lake=tmp_path, source_account_id="source-a")
    _write_jsonl(
        tmp_path / "silver/normalized_events.jsonl",
        [
            {
                "asset_id": "model:same",
                "asset_type": "model",
                "event_type": "model.inventory",
                "source_account_id": account,
                "asset_owner": account,
                "attributes": {"model_card": False},
            }
            for account in ("source-a", "source-b")
        ],
    )
    items = {row["source_account_id"]: row for row in list_ai_inventory(lake=tmp_path)}
    assert set(items) == {"source-a", "source-b"}
    assert items["source-a"]["model_card"] is True
    assert items["source-a"]["owner"] == "source-a"
    assert items["source-a"]["control_ids"] == []
    assert items["source-b"]["model_card"] is False
