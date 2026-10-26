"""Okta, Google Workspace and GCP posture verdicts reach CCF safeguards end to end."""

from __future__ import annotations

import json
import shutil
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_gcp import GCPFixtureClient
from security_lakehouse.connectors_okta import OktaFixtureClient
from security_lakehouse.io import read_jsonl
from security_lakehouse.safeguards import load_safeguards

FIXTURES = Path(__file__).parent / "fixtures"
IDENTITY = "SG-IDENTITY-001"
OKTA_MFA = "okta.identity.mfa_enrollment"
GW_MFA = "google_workspace.identity.mfa_enrollment"
GCP_POLICY = "gcp.cloud.org_policy"
GCP_PROJECT = "gcp:project:fixture-project"
EXPECTED_CONSTRAINTS = ("iam.disableServiceAccountKeyCreation", "compute.requireOsLogin")


def _sync(lake: Path, connector_id: str, fixture: Path) -> None:
    append_config_event(lake, connector_id=connector_id, state="enabled", actor="alice")
    result = run_connector_sync(lake, connector_id=connector_id, fixture_dir=fixture)
    assert result.result == "ok"


def _raw(lake: Path) -> list[dict[str, Any]]:
    return read_jsonl(lake / CONNECTOR_RAW_FILE)


def _identity(lake: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    assessment = json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))
    safeguard = next(row for row in assessment["safeguards"] if row["safeguard_id"] == IDENTITY)
    results = {row["asset_id"]: row for row in assessment["asset_results"] if row["safeguard_id"] == IDENTITY}
    return safeguard, results


def _fixture(tmp_path: Path, name: str, **files: object) -> Path:
    target = tmp_path / name
    shutil.copytree(FIXTURES / name, target)
    for filename, payload in files.items():
        path = target / f"{filename}.json"
        if payload is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _okta_user(user_id: str, status: str = "ACTIVE") -> dict[str, Any]:
    return {"id": user_id, "status": status, "profile": {"login": f"{user_id}@acme.example"}}


ACTIVE_FACTOR = [{"id": "opf-webauthn", "factorType": "webauthn", "status": "ACTIVE"}]


def test_okta_unenrolled_active_user_fails_the_identity_safeguard(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "okta-identity", FIXTURES / "okta")

    safeguard, results = _identity(lake)
    assert safeguard["status"] == "fail"
    assert results["okta:user:00u2nomfa00000002"]["status"] == "fail"
    assert results["okta:user:00u1mfaenrolled01"]["status"] == "pass"
    # The deprovisioned user's MFA record is an observation and never binds.
    assert "okta:user:00u3deprovision03" not in results


def test_okta_fully_enrolled_population_passes_the_identity_safeguard(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        "okta",
        users=[_okta_user("00uenrolled1"), _okta_user("00uenrolled2")],
        factors={"00uenrolled1": ACTIVE_FACTOR, "00uenrolled2": ACTIVE_FACTOR},
    )
    lake = tmp_path / "lake"
    _sync(lake, "okta-identity", fixture)

    safeguard, results = _identity(lake)
    assert safeguard["status"] == "pass"
    assert safeguard["assessed_asset_count"] == safeguard["applicable_asset_count"] == 2
    assert {row["status"] for row in results.values()} == {"pass"}


def test_okta_unreadable_factors_and_inactive_users_never_produce_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(
        tmp_path,
        "okta",
        users=[_okta_user("00uenrolled1"), _okta_user("00uunread2"), _okta_user("00ugone3", "DEPROVISIONED")],
        factors={"00uenrolled1": ACTIVE_FACTOR, "00uunread2": ACTIVE_FACTOR, "00ugone3": []},
    )
    read_factors = OktaFixtureClient.factors

    def factors(self: OktaFixtureClient, user_id: str) -> list[dict[str, Any]]:
        if user_id == "00uunread2":
            raise urllib.error.HTTPError("https://acme.example/factors", 403, "Forbidden", Message(), None)
        return read_factors(self, user_id)

    monkeypatch.setattr(OktaFixtureClient, "factors", factors)
    lake = tmp_path / "lake"
    _sync(lake, "okta-identity", fixture)

    mfa = {row["entity"]["asset_id"]: row for row in _raw(lake) if row["event_type"] == OKTA_MFA}
    assert mfa["okta:user:00uunread2"]["status"] == "not_evaluated"
    assert mfa["okta:user:00ugone3"]["status"] == "observed"
    assert not mfa["okta:user:00ugone3"].get("safeguard_ids")
    safeguard, results = _identity(lake)
    assert results["okta:user:00uenrolled1"]["status"] == "pass"
    assert results["okta:user:00uunread2"]["status"] == "not_evaluated"
    assert "okta:user:00ugone3" not in results
    assert safeguard["status"] == "not_evaluated"
    assert safeguard["unassessed_asset_count"] == 1


def test_okta_observations_only_stay_not_evaluated(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "okta", users=[_okta_user("00ugone1", "SUSPENDED")], factors={"00ugone1": []})
    lake = tmp_path / "lake"
    _sync(lake, "okta-identity", fixture)

    assert all(not row.get("safeguard_ids") for row in _raw(lake))
    safeguard, results = _identity(lake)
    assert safeguard["status"] == "not_evaluated"
    assert results == {}


def _gw_user(user_id: str, *, enrolled: bool | None = True, suspended: bool = False) -> dict[str, Any]:
    user: dict[str, Any] = {"id": user_id, "primaryEmail": f"{user_id}@acme.example", "suspended": suspended}
    user["archived"] = False
    if enrolled is not None:
        user["isEnrolledIn2Sv"] = enrolled
    return user


def test_google_workspace_unenrolled_active_user_fails_the_identity_safeguard(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "google-workspace-identity", FIXTURES / "google_workspace")

    safeguard, results = _identity(lake)
    assert safeguard["status"] == "fail"
    assert results["google_workspace:user:100000000000000000002"]["status"] == "fail"
    assert results["google_workspace:user:100000000000000000001"]["status"] == "pass"
    assert "google_workspace:user:100000000000000000003" not in results
    # Group membership roles are a review signal, not an assessed failure.
    groups = [row for row in _raw(lake) if row["event_type"] == "google_workspace.identity.group_membership"]
    assert groups
    assert all(not row.get("safeguard_ids") for row in groups)


def test_google_workspace_fully_enrolled_population_passes_the_identity_safeguard(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "google_workspace", users=[_gw_user("u1"), _gw_user("u2")], groups=[], members={})
    lake = tmp_path / "lake"
    _sync(lake, "google-workspace-identity", fixture)

    safeguard, results = _identity(lake)
    assert safeguard["status"] == "pass"
    assert safeguard["assessed_asset_count"] == safeguard["applicable_asset_count"] == 2
    assert {row["status"] for row in results.values()} == {"pass"}


def test_google_workspace_unassessed_groups_or_unknown_enrollment_never_produce_a_pass(tmp_path: Path) -> None:
    with_groups = _fixture(tmp_path, "google_workspace", users=[_gw_user("u1")])
    lake = tmp_path / "lake"
    _sync(lake, "google-workspace-identity", with_groups)
    safeguard, results = _identity(lake)
    assert results["google_workspace:user:u1"]["status"] == "pass"
    assert safeguard["status"] == "not_evaluated"
    assert safeguard["unassessed_asset_count"] >= 1

    shutil.rmtree(with_groups)
    unknown = _fixture(tmp_path, "google_workspace", users=[_gw_user("u1"), _gw_user("u2", enrolled=None)], groups=[])
    other = tmp_path / "other"
    _sync(other, "google-workspace-identity", unknown)
    mfa = {row["entity"]["asset_id"]: row for row in _raw(other) if row["event_type"] == GW_MFA}
    assert mfa["google_workspace:user:u2"]["status"] == "not_evaluated"
    assert mfa["google_workspace:user:u2"]["safeguard_ids"] == [IDENTITY]
    assert _identity(other)[0]["status"] == "not_evaluated"


def test_google_workspace_observations_only_stay_not_evaluated(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "google_workspace", users=[_gw_user("u1", suspended=True)], groups=[])
    lake = tmp_path / "lake"
    _sync(lake, "google-workspace-identity", fixture)

    assert all(not row.get("safeguard_ids") for row in _raw(lake))
    safeguard, results = _identity(lake)
    assert safeguard["status"] == "not_evaluated"
    assert results == {}


def _policies(**enforced: bool | None) -> list[dict[str, Any]]:
    return [
        {
            "name": f"projects/fixture-project/policies/constraints/{constraint}",
            "constraint": f"constraints/{constraint}",
            "enforced": value,
        }
        for constraint, value in enforced.items()
    ]


def _gcp_policy_events(lake: Path) -> dict[str, dict[str, Any]]:
    return {row["attributes"]["constraint"]: row for row in _raw(lake) if row["event_type"] == GCP_POLICY}


def test_gcp_unenforced_expected_constraint_fails_the_identity_safeguard(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", FIXTURES / "gcp")

    safeguard, results = _identity(lake)
    assert safeguard["status"] == "fail"
    assert results[GCP_PROJECT]["status"] == "fail"


ENFORCED = _policies(
    **{
        "iam.disableServiceAccountKeyCreation": True,
        "compute.requireOsLogin": True,
        "gcp.resourceLocations": None,
    }
)


def test_gcp_enforced_expected_constraints_pass_the_identity_safeguard(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", _fixture(tmp_path, "gcp", org_policies=ENFORCED, assets={"assets": []}))

    events = _gcp_policy_events(lake)
    assert not events["constraints/gcp.resourceLocations"].get("safeguard_ids")
    safeguard, results = _identity(lake)
    assert results[GCP_PROJECT]["status"] == "pass"
    assert safeguard["status"] == "pass"
    assert safeguard["assessed_asset_count"] == safeguard["applicable_asset_count"] == 1


def test_gcp_unassessed_inventory_keeps_the_identity_safeguard_from_passing(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", _fixture(tmp_path, "gcp", org_policies=ENFORCED))

    safeguard, results = _identity(lake)
    assert results[GCP_PROJECT]["status"] == "pass"
    assert safeguard["status"] == "not_evaluated"
    assert safeguard["unassessed_asset_count"] >= 1


@pytest.mark.parametrize(
    "policies",
    [
        _policies(**{"iam.disableServiceAccountKeyCreation": True}),
        _policies(**{"iam.disableServiceAccountKeyCreation": True, "compute.requireOsLogin": None}),
        [],
    ],
    ids=["expected-constraint-not-set-on-project", "conditional-rule", "no-project-policies"],
)
def test_gcp_unestablished_constraint_enforcement_is_never_a_pass(tmp_path: Path, policies: list[Any]) -> None:
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", _fixture(tmp_path, "gcp", org_policies=policies))

    events = _gcp_policy_events(lake)
    for constraint in EXPECTED_CONSTRAINTS:
        assert f"constraints/{constraint}" in events
    assert events["constraints/compute.requireOsLogin"]["status"] == "not_evaluated"
    safeguard, results = _identity(lake)
    assert results.get(GCP_PROJECT, {}).get("status") != "pass"
    assert safeguard["status"] == "not_evaluated"


@pytest.mark.parametrize("collection", ["org_policies", "assets"])
def test_gcp_collection_gaps_never_produce_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, collection: str
) -> None:
    def denied(self: GCPFixtureClient) -> list[dict[str, Any]]:
        raise CollectionGapError("read denied", collection=collection, reason="permission_denied")

    monkeypatch.setattr(GCPFixtureClient, collection, denied)
    fixture = _fixture(
        tmp_path,
        "gcp",
        org_policies=_policies(**{"iam.disableServiceAccountKeyCreation": True, "compute.requireOsLogin": True}),
    )
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", fixture)

    safeguard, _ = _identity(lake)
    assert safeguard["status"] == "not_evaluated"


def _effective(**enforced: bool | None) -> list[dict[str, Any]]:
    return [{"constraint": f"constraints/{name}", "enforced": value} for name, value in enforced.items()]


INHERITED_ENFORCED = _effective(**{"iam.disableServiceAccountKeyCreation": True, "compute.requireOsLogin": True})


def test_gcp_inherited_enforced_constraints_pass_from_the_effective_policy(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path, "gcp", org_policies=[], effective_org_policies=INHERITED_ENFORCED, assets={"assets": []}
    )
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", fixture)

    events = _gcp_policy_events(lake)
    for constraint in EXPECTED_CONSTRAINTS:
        row = events[f"constraints/{constraint}"]
        assert row["status"] == "pass"
        assert row["safeguard_ids"] == [IDENTITY]
        assert row["attributes"]["effective"] is True
        assert row["attributes"]["set_on_project"] is False
        assert row["evidence"]["evidence_ref"].endswith(f"/policies/{constraint}:getEffectivePolicy")
    safeguard, results = _identity(lake)
    assert results[GCP_PROJECT]["status"] == "pass"
    assert safeguard["status"] == "pass"
    assert safeguard["assessed_asset_count"] == safeguard["applicable_asset_count"] == 1


def test_gcp_inherited_enforcement_still_needs_every_accepted_asset_assessed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, "gcp", org_policies=[], effective_org_policies=INHERITED_ENFORCED)
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", fixture)

    safeguard, results = _identity(lake)
    assert results[GCP_PROJECT]["status"] == "pass"
    assert safeguard["status"] == "not_evaluated"


def test_gcp_inherited_unenforced_constraint_fails_the_identity_safeguard(tmp_path: Path) -> None:
    effective = _effective(**{"iam.disableServiceAccountKeyCreation": True, "compute.requireOsLogin": False})
    fixture = _fixture(tmp_path, "gcp", org_policies=[], effective_org_policies=effective, assets={"assets": []})
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", fixture)

    events = _gcp_policy_events(lake)
    assert events["constraints/compute.requireOsLogin"]["status"] == "open"
    assert events["constraints/compute.requireOsLogin"]["attributes"]["needs_enforcement"] is True
    safeguard, results = _identity(lake)
    assert results[GCP_PROJECT]["status"] == "fail"
    assert safeguard["status"] == "fail"


@pytest.mark.parametrize(
    "effective",
    [
        _effective(**{"iam.disableServiceAccountKeyCreation": True, "compute.requireOsLogin": None}),
        _effective(**{"iam.disableServiceAccountKeyCreation": True}),
        None,
    ],
    ids=["conditional-effective-rule", "effective-read-failed", "effective-not-readable"],
)
def test_gcp_unestablished_effective_policy_is_never_a_pass(
    tmp_path: Path, effective: list[dict[str, Any]] | None
) -> None:
    fixture = _fixture(tmp_path, "gcp", org_policies=[], effective_org_policies=effective, assets={"assets": []})
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", fixture)

    row = _gcp_policy_events(lake)["constraints/compute.requireOsLogin"]
    assert row["status"] == "not_evaluated"
    assert row["safeguard_ids"] == [IDENTITY]
    gaps = [r for r in _raw(lake) if r["event_type"] == "gcp.collection_gap"]
    if effective is None or len(effective) == 1:
        assert row["attributes"]["effective"] is False
        collections = {gap["attributes"]["collection"] for gap in gaps}
        assert "effective_org_policies:compute.requireOsLogin" in collections
    else:
        assert row["attributes"]["effective"] is True
        assert not gaps
    safeguard, results = _identity(lake)
    assert results.get(GCP_PROJECT, {}).get("status") != "pass"
    assert safeguard["status"] == "not_evaluated"


def test_gcp_constraint_set_on_project_does_not_read_the_effective_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def effective(self: GCPFixtureClient, constraint: str) -> dict[str, Any]:
        calls.append(constraint)
        return {"constraint": constraint, "enforced": True}

    monkeypatch.setattr(GCPFixtureClient, "effective_org_policy", effective, raising=False)
    project_policies = _policies(**{"iam.disableServiceAccountKeyCreation": False})
    fixture = _fixture(tmp_path, "gcp", org_policies=project_policies, assets={"assets": []})
    lake = tmp_path / "lake"
    _sync(lake, "gcp-posture", fixture)

    assert calls == ["constraints/compute.requireOsLogin"]
    events = _gcp_policy_events(lake)
    listed = events["constraints/iam.disableServiceAccountKeyCreation"]
    assert listed["status"] == "open"
    assert listed["attributes"]["set_on_project"] is True
    assert listed["attributes"]["effective"] is False
    safeguard, _results = _identity(lake)
    assert safeguard["status"] == "fail"


@pytest.mark.parametrize(
    ("connector_id", "fixture", "event_types"),
    [
        ("okta-identity", "okta", {OKTA_MFA}),
        ("google-workspace-identity", "google_workspace", {GW_MFA}),
        ("gcp-posture", "gcp", {GCP_POLICY}),
    ],
)
def test_bindings_accept_the_asset_type_and_stay_inside_the_crosswalk(
    tmp_path: Path, connector_id: str, fixture: str, event_types: set[str]
) -> None:
    _sync(tmp_path, connector_id, FIXTURES / fixture)
    definition = next(row for row in load_safeguards()["safeguards"] if row["safeguard_id"] == IDENTITY)
    crosswalk = {member["control_id"] for member in definition["satisfies"]}
    bound = [row for row in _raw(tmp_path) if row.get("safeguard_ids")]
    assert bound
    assert {row["event_type"] for row in bound} == event_types
    for row in bound:
        assert row["status"] in {"pass", "open", "not_evaluated"}
        assert row["safeguard_ids"] == [IDENTITY]
        assert row["entity"]["asset_type"] in definition["asset_types"]
        assert set(row["controls"]) <= crosswalk


@pytest.mark.parametrize(
    ("connector_id", "fixture"),
    [
        ("azure-posture", "azure"),
        ("entra-identity", "entra"),
        ("jira-ticketing", "jira"),
        ("intune-devices", "intune"),
        ("jamf-devices", "jamf"),
        ("crowdstrike-falcon", "crowdstrike"),
    ],
)
def test_connectors_without_an_accepting_safeguard_stay_unbound(
    tmp_path: Path, connector_id: str, fixture: str
) -> None:
    _sync(tmp_path, connector_id, FIXTURES / fixture)
    rows = _raw(tmp_path)
    assert rows
    assert all(not row.get("safeguard_ids") for row in rows)
