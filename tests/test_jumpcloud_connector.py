"""Synthetic JumpCloud identity collection, failure and assessment contracts."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import netguard
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.pipeline import run_pipeline

FIXTURE = Path(__file__).parent / "fixtures/jumpcloud"
TOKEN = "synthetic-jumpcloud-token"
ORG = "a" * 24


def collect() -> list[dict[str, Any]]:
    from security_lakehouse.connectors_jumpcloud import JumpCloudClient, collect_jumpcloud_evidence

    return collect_jumpcloud_evidence(JumpCloudClient(token=TOKEN, organization=ORG))


def fake(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any] | None = None) -> list[str]:
    routes = json.loads((FIXTURE / "responses.json").read_text())
    routes.update(overrides or {})
    calls: list[str] = []

    def read(request: Any, **kwargs: Any) -> io.BytesIO:
        assert request.get_method() == "GET"
        assert request.full_url.startswith("https://console.jumpcloud.com/api/")
        assert request.get_header("X-api-key") == TOKEN
        assert request.get_header("X-org-id") == ORG
        path = request.full_url.split("/api/", 1)[1]
        calls.append(path)
        value = routes[path]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(netguard, "open_public", read)
    return calls


def test_jumpcloud_fixture_runner_to_ccf(tmp_path: Path) -> None:
    append_config_event(
        tmp_path, connector_id="jumpcloud-identity", state="enabled", actor="test", credentials={"organization_id": ORG}
    )
    result = run_connector_sync(tmp_path, connector_id="jumpcloud-identity", fixture_dir=FIXTURE, materialize=False)
    assert not result.coverage_gaps
    raw = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    mfa = {r["attributes"]["user_id"]: r for r in raw if r["event_type"] == "jumpcloud.identity.mfa_enrollment"}
    assert [mfa[str(i) * 24]["status"] for i in range(1, 5)] == ["pass", "open", "observed", "pass"]
    assert mfa["3" * 24]["attributes"]["active"] is False
    assert any(r["event_type"] == "jumpcloud.identity.group_membership" for r in raw)
    assert any(r["attributes"].get("admin_roles") == ["Help Desk"] for r in raw)
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="jc-test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    identity = [r for r in assessment["safeguards"] if r["safeguard_id"] in {"SG-IDENTITY-001", "SG-IDENTITY-002"}]
    assert len(identity) == 2 and all(r["assessed_asset_count"] > 0 for r in identity)
    assert all(r["status"] == "not_evaluated" and r["invalid_binding_count"] == 0 for r in identity)


@pytest.mark.parametrize("code", [401, 403, 429])
def test_denied_group_read_is_partial_and_preserves_mfa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    fake(
        monkeypatch,
        {
            "v2/usergroups?limit=100&skip=0": urllib.error.HTTPError(
                "https://example.com", code, TOKEN, {"Retry-After": "301"}, None
            )
        },
    )
    monkeypatch.setenv("JC_TEST_KEY", TOKEN)
    append_config_event(
        tmp_path,
        connector_id="jumpcloud-identity",
        state="enabled",
        actor="test",
        credentials={"credential_ref": "JC_TEST_KEY", "organization_id": ORG},
    )
    result = run_connector_sync(tmp_path, connector_id="jumpcloud-identity", materialize=False)
    assert (
        result.coverage_gaps and latest_run(tmp_path, "jumpcloud-identity", kind="sync")["metadata"]["partial"] is True
    )
    raw = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    assert any(r["status"] == "open" for r in raw)
    assert TOKEN not in json.dumps(raw)


def test_missing_mfa_and_contradictory_account_state_never_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = json.loads((FIXTURE / "responses.json").read_text())
    users = routes["systemusers?limit=100&skip=0"]["results"]
    users[0].pop("mfaEnrollment")
    users[0].pop("totp_enabled")
    users[3]["suspended"] = True
    fake(monkeypatch, routes)
    rows = collect()
    for user_id in ["1" * 24, "4" * 24]:
        row = next(
            r
            for r in rows
            if r["event_type"] == "jumpcloud.identity.mfa_enrollment" and r["attributes"]["user_id"] == user_id
        )
        assert row["status"] == "not_evaluated"


def test_user_count_mismatch_and_missing_rows_are_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, {"systemusers?limit=100&skip=0": {"results": [], "totalCount": 4}})
    assert collect()[0]["attributes"]["collection_gap"] is True


def test_replay_identity_and_data_minimization(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch)
    first, second = collect(), collect()
    assert [r["event_id"] for r in first] == [r["event_id"] for r in second]
    assert len({r["event_id"] for r in first}) == len(first)
    assert "private@example.com" not in json.dumps(first)


@pytest.mark.parametrize("region", ["https://example.com", "localhost", "console.jumpcloud.com.evil.example"])
def test_region_cannot_redirect_credentials(region: str) -> None:
    from security_lakehouse.connector_errors import ConnectorConfigError
    from security_lakehouse.connectors_jumpcloud import JumpCloudClient

    with pytest.raises(ConnectorConfigError):
        JumpCloudClient(token=TOKEN, organization=ORG, region=region)


@pytest.mark.parametrize("field", ["totpStatus", "webAuthnStatus"])
def test_malformed_enrollment_is_a_gap(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    routes = json.loads((FIXTURE / "responses.json").read_text())
    user = routes["systemusers?limit=100&skip=0"]["results"][1]
    user["mfaEnrollment"][field] = ["ENROLLED"]
    fake(monkeypatch, routes)
    row = next(
        r
        for r in collect()
        if r["event_type"] == "jumpcloud.identity.mfa_enrollment" and r["attributes"]["user_id"] == "2" * 24
    )
    assert row["status"] == "not_evaluated"


def test_malformed_admin_roles_are_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = json.loads((FIXTURE / "responses.json").read_text())
    routes["systemusers?limit=100&skip=0"]["results"][0]["admin"] = "unknown"
    fake(monkeypatch, routes)
    row = next(
        r
        for r in collect()
        if r["event_type"] == "jumpcloud.identity.user_access" and r["attributes"]["user_id"] == "1" * 24
    )
    assert row["status"] == "not_evaluated"


def test_pagination_budget_and_second_page(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_jumpcloud import JumpCloudClient, collect_jumpcloud_evidence

    routes = json.loads((FIXTURE / "responses.json").read_text())
    seed = routes["systemusers?limit=100&skip=0"]["results"][0]
    routes["systemusers?limit=100&skip=0"] = {
        "results": [{**seed, "_id": f"{i:024x}"} for i in range(100)],
        "totalCount": 101,
    }
    routes["systemusers?limit=100&skip=100"] = {"results": [{**seed, "_id": f"{100:024x}"}], "totalCount": 101}
    fake(monkeypatch, routes)
    rows = collect()
    assert sum(r["event_type"] == "jumpcloud.identity.mfa_enrollment" for r in rows) == 101
    capped = collect_jumpcloud_evidence(JumpCloudClient(token=TOKEN, organization=ORG, max_pages=1))
    assert capped[0]["attributes"]["reason"] == "page_budget_exhausted"


def test_retry_after_and_scope_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_jumpcloud import (
        JumpCloudClient,
        JumpCloudFixtureClient,
        collect_jumpcloud_evidence,
    )
    from security_lakehouse.ingestion import backoff

    calls, sleeps = [], []

    def read(request: Any, **kwargs: Any) -> io.BytesIO:
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "rate limit", {"Retry-After": "1"}, None)
        return io.BytesIO(b"[]")

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr(backoff.time, "sleep", sleeps.append)
    assert JumpCloudClient(token=TOKEN, organization=ORG).get("v2/usergroups") == []
    assert sleeps == [1]
    first = collect_jumpcloud_evidence(JumpCloudFixtureClient(FIXTURE, organization=ORG))
    second = collect_jumpcloud_evidence(JumpCloudFixtureClient(FIXTURE, organization="c" * 24))
    assert not {r["event_id"] for r in first} & {r["event_id"] for r in second}
