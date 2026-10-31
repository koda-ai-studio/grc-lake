"""Technical verdicts remain visible while untyped safeguards cannot be attested."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_jsonl
from security_lakehouse.safeguards import load_safeguards

AWS_FIXTURE = Path(__file__).parent / "fixtures" / "aws"
GITHUB_FIXTURE = Path(__file__).parent / "fixtures" / "github-governance"
IDENTITY = "SG-IDENTITY-001"
CHANGE_APPROVAL = "SG-CHANGEAPPROVAL-001"
CHANGE_EVENT = "repository.governance.change_approval"

COMPLIANT_PROTECTION = {
    "required_pull_request_reviews": {"required_approving_review_count": 1},
    "required_status_checks": {"strict": True, "contexts": ["quality"]},
    "enforce_admins": {"enabled": True},
    "allow_force_pushes": {"enabled": False},
    "allow_deletions": {"enabled": False},
}


@pytest.fixture(autouse=True)
def _no_ambient_aws_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_ACCOUNT_ID", raising=False)


def _assessment(lake: Path) -> dict[str, Any]:
    return json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))


def _safeguard(assessment: dict[str, Any], safeguard_id: str) -> dict[str, Any]:
    return next(row for row in assessment["safeguards"] if row["safeguard_id"] == safeguard_id)


def _asset_results(assessment: dict[str, Any], safeguard_id: str) -> dict[str, dict[str, Any]]:
    return {row["asset_id"]: row for row in assessment["asset_results"] if row["safeguard_id"] == safeguard_id}


def _assert_untyped(assessment: dict[str, Any], safeguard_id: str) -> None:
    assert _safeguard(assessment, safeguard_id)["status"] == "not_evaluated"
    results = _asset_results(assessment, safeguard_id)
    assert results
    for row in results.values():
        assert row["status"] == "not_evaluated"
        assert row["reasons"] == ["The safeguard has no declared evidence-type contract."]


def _sync(lake: Path, connector_id: str, fixture: Path, **options: Any) -> None:
    append_config_event(lake, connector_id=connector_id, state="enabled", actor="alice", options=options or None)
    repo = "acme/model-service" if connector_id == "github-security" else None
    result = run_connector_sync(lake, connector_id=connector_id, repo=repo, fixture_dir=fixture)
    assert result.result == "ok"


def _write_aws_fixture(path: Path, *, users: list[str], keys: dict[str, Any], policy: dict[str, Any]) -> Path:
    path.mkdir()
    (path / "iam_users.json").write_text(
        json.dumps([{"UserName": user, "Arn": f"arn:aws:iam::123456789012:user/{user}"} for user in users]),
        encoding="utf-8",
    )
    (path / "mfa_devices.json").write_text(json.dumps({user: [] for user in users}), encoding="utf-8")
    (path / "login_profiles.json").write_text("[]", encoding="utf-8")
    (path / "access_keys.json").write_text(json.dumps(keys), encoding="utf-8")
    (path / "password_policy.json").write_text(json.dumps({"PasswordPolicy": policy}), encoding="utf-8")
    return path


STRONG_POLICY = {
    "MinimumPasswordLength": 14,
    "RequireSymbols": True,
    "RequireNumbers": True,
    "RequireUppercaseCharacters": True,
    "RequireLowercaseCharacters": True,
}


def test_aws_open_mfa_and_password_policy_do_not_attest_an_untyped_safeguard(tmp_path: Path) -> None:
    _sync(tmp_path, "aws-posture", AWS_FIXTURE)
    assessment = _assessment(tmp_path)

    _assert_untyped(assessment, IDENTITY)
    rows = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    mfa = {row["entity"]["asset_id"]: row["status"] for row in rows if row["event_type"] == "aws.iam.mfa_enrollment"}
    assert mfa["aws:iam:user/grace-hopper"] == "open"
    assert mfa["aws:iam:user/ada-lovelace"] == "pass"
    assert next(row for row in rows if row["event_type"] == "aws.iam.password_policy")["status"] == "open"


def test_aws_stale_access_key_stays_open_without_a_safeguard_contract(tmp_path: Path) -> None:
    fixture = _write_aws_fixture(
        tmp_path / "aws",
        users=["svc-deploy"],
        keys={"svc-deploy": [{"AccessKeyId": "AKIAOLD", "Status": "Active", "CreateDate": "2020-01-01T00:00:00Z"}]},
        policy=STRONG_POLICY,
    )
    lake = tmp_path / "lake"
    _sync(lake, "aws-posture", fixture)
    assessment = _assessment(lake)

    _assert_untyped(assessment, IDENTITY)
    rows = read_jsonl(lake / CONNECTOR_RAW_FILE)
    assert any(row["status"] == "open" and row["entity"]["asset_id"] == "aws:iam:user/svc-deploy" for row in rows)


def test_aws_observation_only_users_never_produce_a_pass(tmp_path: Path) -> None:
    fixture = _write_aws_fixture(tmp_path / "aws", users=["svc-reader"], keys={}, policy=STRONG_POLICY)
    lake = tmp_path / "lake"
    _sync(lake, "aws-posture", fixture)
    raw = read_jsonl(lake / CONNECTOR_RAW_FILE)
    assert all(not row.get("safeguard_ids") for row in raw if row["status"] == "observed")

    assessment = _assessment(lake)
    identity = _safeguard(assessment, IDENTITY)
    assert identity["status"] == "not_evaluated"
    assert identity["unassessed_asset_count"] >= 1


def test_aws_bindings_accept_the_asset_type_and_stay_inside_the_crosswalk(tmp_path: Path) -> None:
    _sync(tmp_path, "aws-posture", AWS_FIXTURE)
    definition = next(row for row in load_safeguards()["safeguards"] if row["safeguard_id"] == IDENTITY)
    crosswalk = {member["control_id"] for member in definition["satisfies"]}
    bound = [row for row in read_jsonl(tmp_path / CONNECTOR_RAW_FILE) if row.get("safeguard_ids")]
    assert {row["event_type"] for row in bound} == {"aws.iam.mfa_enrollment", "aws.iam.password_policy"}
    for row in bound:
        assert row["safeguard_ids"] == [IDENTITY]
        assert row["entity"]["asset_type"] in definition["asset_types"]
        assert set(row["controls"]) <= crosswalk


def _github_fixture(tmp_path: Path, protection: object | None) -> Path:
    fixture = tmp_path / "github"
    shutil.copytree(GITHUB_FIXTURE, fixture)
    target = fixture / "branch_protection.json"
    if protection is None:
        target.unlink()
    else:
        target.write_text(json.dumps(protection), encoding="utf-8")
    return fixture


def _change_approval(lake: Path) -> dict[str, Any]:
    rows = [row for row in read_jsonl(lake / CONNECTOR_RAW_FILE) if row["event_type"] == CHANGE_EVENT]
    assert len(rows) == 1
    return rows[0]


def test_github_compliant_protection_does_not_attest_untyped_change_approval(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "github-security", _github_fixture(tmp_path, COMPLIANT_PROTECTION))

    event = _change_approval(lake)
    assert event["status"] == "pass"
    assert event["safeguard_ids"] == [CHANGE_APPROVAL]
    assessment = _assessment(lake)
    _assert_untyped(assessment, CHANGE_APPROVAL)
    # The observation records stay observations.
    branch = next(
        row
        for row in read_jsonl(lake / CONNECTOR_RAW_FILE)
        if row["event_type"] == "repository.governance.branch_protection"
    )
    assert branch["status"] == "observed"
    assert not branch.get("safeguard_ids")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"required_pull_request_reviews": {"required_approving_review_count": 0}}, "required_approving_reviews"),
        ({"required_pull_request_reviews": None}, "required_approving_reviews"),
        ({"allow_force_pushes": {"enabled": True}}, "force_pushes_allowed"),
        ({"allow_deletions": {"enabled": True}}, "deletions_allowed"),
        ({"enforce_admins": {"enabled": False}}, "admins_not_included"),
    ],
)
def test_github_weak_protection_keeps_the_technical_failure_reason(
    tmp_path: Path, change: dict[str, Any], reason: str
) -> None:
    protection = {**COMPLIANT_PROTECTION, **change}
    protection = {key: value for key, value in protection.items() if value is not None}
    lake = tmp_path / "lake"
    _sync(lake, "github-security", _github_fixture(tmp_path, protection))

    event = _change_approval(lake)
    assert event["status"] == "open"
    assert event["attributes"]["unmet_requirements"] == [reason]
    _assert_untyped(_assessment(lake), CHANGE_APPROVAL)


@pytest.mark.parametrize(
    "protection",
    [
        {"available": False, "requires_scope_or_permission": True, "http_status": 403},
        {"available": False, "requires_scope_or_permission": True, "http_status": 404},
        {"available": False, "requires_scope_or_permission": True, "http_status": 401},
        None,
        {**{k: v for k, v in COMPLIANT_PROTECTION.items() if k != "allow_force_pushes"}},
        {**COMPLIANT_PROTECTION, "enforce_admins": {"enabled": "yes"}},
    ],
)
def test_github_unreadable_or_incomplete_protection_is_never_a_pass(tmp_path: Path, protection: object) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "github-security", _github_fixture(tmp_path, protection))

    event = _change_approval(lake)
    assert event["status"] == "not_evaluated"
    assert _safeguard(_assessment(lake), CHANGE_APPROVAL)["status"] == "not_evaluated"


def test_github_resync_replaces_the_change_approval_verdict(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "github-security", _github_fixture(tmp_path, COMPLIANT_PROTECTION))
    shutil.rmtree(tmp_path / "github")
    weak = {**COMPLIANT_PROTECTION, "allow_force_pushes": {"enabled": True}}
    run_connector_sync(
        lake, connector_id="github-security", repo="acme/model-service", fixture_dir=_github_fixture(tmp_path, weak)
    )

    assert _change_approval(lake)["status"] == "open"
    _assert_untyped(_assessment(lake), CHANGE_APPROVAL)


def test_operator_bindings_merge_with_connector_bindings(tmp_path: Path) -> None:
    _sync(
        tmp_path,
        "aws-posture",
        AWS_FIXTURE,
        safeguard_bindings={"aws.iam.mfa_enrollment": ["SG-IDENTITY-002"]},
    )
    mfa = [row for row in read_jsonl(tmp_path / CONNECTOR_RAW_FILE) if row["event_type"] == "aws.iam.mfa_enrollment"]
    assert mfa
    assert all(row["safeguard_ids"] == ["SG-IDENTITY-001", "SG-IDENTITY-002"] for row in mfa)
