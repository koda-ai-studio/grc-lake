"""Collection gaps and inventory absences never hide a failing verdict or allow a pass."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connector_runner import run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_aws import AWSFixtureClient, collect_aws_evidence, collect_aws_inventory_evidence
from security_lakehouse.connectors_gcp import GCPFixtureClient
from security_lakehouse.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
IDENTITY = "SG-IDENTITY-001"
ACCOUNT = "123456789012"
COLLECTED_AT = datetime.now(UTC)
STRONG_POLICY = {
    "MinimumPasswordLength": 14,
    "RequireSymbols": True,
    "RequireNumbers": True,
    "RequireUppercaseCharacters": True,
    "RequireLowercaseCharacters": True,
}


class _Denied(Exception):
    def __init__(self) -> None:
        super().__init__("AccessDeniedException")
        self.response = {"Error": {"Code": "AccessDeniedException"}}


class _InventoryClient:
    """No CloudTrail trail (an absence) and a denied RDS read (a gap)."""

    def inventory(self, service: str, *, region_name: str) -> list[dict[str, Any]]:
        if service == "rds":
            raise _Denied
        return []


def _identity(lake: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    assessment = json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))
    safeguard = next(row for row in assessment["safeguards"] if row["safeguard_id"] == IDENTITY)
    results = {row["asset_id"]: row for row in assessment["asset_results"] if row["safeguard_id"] == IDENTITY}
    return safeguard, results


def _aws_lake(tmp_path: Path, iam_fixture: Path, *, services: list[str]) -> Path:
    rows = collect_aws_evidence(AWSFixtureClient(iam_fixture), account_id=ACCOUNT, collected_at=COLLECTED_AT)
    rows += collect_aws_inventory_evidence(
        _InventoryClient(), account_id=ACCOUNT, regions=["us-east-1"], services=services, collected_at=COLLECTED_AT
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    lake = tmp_path / "lake"
    run_pipeline(raw, lake)
    return lake


def _strong_policy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "aws"
    target.mkdir()
    for name, payload in {
        "iam_users.json": [],
        "mfa_devices.json": {},
        "password_policy.json": {"PasswordPolicy": STRONG_POLICY},
    }.items():
        (target / name).write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_aws_gap_and_absence_do_not_hide_a_failing_password_policy(tmp_path: Path) -> None:
    lake = _aws_lake(tmp_path, FIXTURES / "aws", services=["cloudtrail", "rds"])

    safeguard, results = _identity(lake)
    assert results[f"aws:account:{ACCOUNT}"]["status"] == "fail"
    assert safeguard["status"] == "fail"


def test_aws_collection_gap_keeps_a_passing_policy_from_passing_the_safeguard(tmp_path: Path) -> None:
    fixture = _strong_policy_fixture(tmp_path)
    assert _identity(_aws_lake(tmp_path / "clean", fixture, services=["s3"]))[0]["status"] == "pass"

    safeguard, results = _identity(_aws_lake(tmp_path / "gap", fixture, services=["rds"]))
    assert results[f"aws:account:{ACCOUNT}"]["status"] == "pass"
    assert safeguard["status"] == "not_evaluated"


def test_gcp_asset_gap_does_not_hide_a_failing_org_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(self: GCPFixtureClient) -> list[dict[str, Any]]:
        raise CollectionGapError("read denied", collection="assets", reason="permission_denied")

    monkeypatch.setattr(GCPFixtureClient, "assets", denied)
    fixture = tmp_path / "gcp"
    shutil.copytree(FIXTURES / "gcp", fixture)
    lake = tmp_path / "lake"
    append_config_event(lake, connector_id="gcp-posture", state="enabled", actor="alice")
    assert run_connector_sync(lake, connector_id="gcp-posture", fixture_dir=fixture).result == "ok"

    safeguard, results = _identity(lake)
    assert results["gcp:project:fixture-project"]["status"] == "fail"
    assert safeguard["status"] == "fail"
