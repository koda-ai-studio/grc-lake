"""Provider benchmark requirements are evaluated only from their own provider's evidence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse.catalog import load_framework_registry
from security_lakehouse.connector_runner import run_connector_sync
from security_lakehouse.connector_state import append_config_event

FIXTURES = Path(__file__).parent / "fixtures"
CIS_AWS = "CIS-AWS-1.10"
SOC2 = "SOC2-CC6.1"
ENFORCED = [
    {
        "name": f"projects/fixture-project/policies/constraints/{constraint}",
        "constraint": f"constraints/{constraint}",
        "enforced": True,
    }
    for constraint in ("iam.disableServiceAccountKeyCreation", "compute.requireOsLogin")
]


@pytest.fixture(autouse=True)
def _no_ambient_aws_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)


@pytest.fixture
def identity_evidence_type() -> str:
    return "gcp.cloud.org_policy"


@pytest.fixture(autouse=True)
def _explicit_reviewed_provider_mappings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity_evidence_type: str
) -> None:
    """Test provider isolation with an explicit test-only reviewed catalog."""
    from security_lakehouse import safeguards

    payload = json.loads(safeguards.DEFAULT_SAFEGUARDS.read_text())
    for entry in payload["safeguards"]:
        if entry["safeguard_id"] == "SG-IDENTITY-001":
            entry["required_evidence_types"] = [identity_evidence_type]
            for member in entry["satisfies"]:
                if member["control_id"] in {CIS_AWS, SOC2}:
                    member["review_status"] = "reviewed"
    path = tmp_path / "reviewed-test-catalog.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(safeguards, "DEFAULT_SAFEGUARDS", path)


def _sync(lake: Path, connector_id: str, fixture: Path) -> None:
    append_config_event(lake, connector_id=connector_id, state="enabled", actor="alice")
    assert run_connector_sync(lake, connector_id=connector_id, fixture_dir=fixture).result == "ok"


def _assessment(lake: Path) -> dict[str, Any]:
    return json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))


def _requirements(lake: Path) -> dict[str, str]:
    return {row["control_id"]: row["status"] for row in _assessment(lake)["requirements"]}


def _gcp_fixture(tmp_path: Path, **files: object) -> Path:
    target = tmp_path / "gcp"
    shutil.copytree(FIXTURES / "gcp", target)
    for name, payload in files.items():
        (target / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_cis_aws_declares_its_provider_sources_in_the_registry() -> None:
    assert load_framework_registry()["cis_aws"]["provider_sources"] == ["aws", "aws_config"]


def test_failing_gcp_evidence_fails_soc2_but_not_cis_aws(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", FIXTURES / "gcp")

    requirements = _requirements(lake)
    assert requirements[SOC2] == "fail"
    assert requirements[CIS_AWS] == "not_evaluated"


def test_passing_gcp_evidence_never_attests_cis_aws(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", _gcp_fixture(tmp_path, org_policies=ENFORCED, assets={"assets": []}))

    identity = next(row for row in _assessment(lake)["safeguards"] if row["safeguard_id"] == "SG-IDENTITY-001")
    assert identity["status"] == "pass"
    assert _requirements(lake)[CIS_AWS] == "not_evaluated"


@pytest.mark.parametrize("identity_evidence_type", ["aws.iam.password_policy"])
def test_failing_aws_evidence_still_fails_cis_aws_alongside_gcp(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", _gcp_fixture(tmp_path, org_policies=ENFORCED, assets={"assets": []}))
    _sync(lake, "aws-posture", FIXTURES / "aws")

    requirements = _requirements(lake)
    assert requirements[CIS_AWS] == "fail"
    assert requirements[SOC2] == "fail"
