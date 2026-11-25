"""Synthetic Cloudflare zone security contracts; no vendor account is contacted."""

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

FIXTURE = Path(__file__).parent / "fixtures" / "cloudflare" / "responses.json"
ZONE = "a" * 32
TOKEN = "synthetic-cloudflare-token"


def fake_api(monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any] | None = None) -> list[str]:
    routes = json.loads(FIXTURE.read_text())
    routes.update(changes or {})
    calls: list[str] = []

    def open_request(request: Any, **kwargs: Any) -> io.BytesIO:
        assert request.get_method() == "GET"
        assert request.full_url.startswith("https://api.cloudflare.com/client/v4/")
        assert request.get_header("Authorization") == f"Bearer {TOKEN}"
        path = request.full_url.split("/client/v4/", 1)[1]
        calls.append(path)
        value = routes[path]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(netguard, "open_public", open_request)
    return calls


def collect() -> list[dict[str, Any]]:
    from security_lakehouse.connectors_cloudflare import CloudflareClient, collect_cloudflare_evidence

    return collect_cloudflare_evidence(CloudflareClient(token=TOKEN))


def test_zone_security_runner_reaches_ccf(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="cloudflare-zones", state="enabled", actor="test")
    result = run_connector_sync(
        tmp_path, connector_id="cloudflare-zones", fixture_dir=FIXTURE.parent, materialize=False
    )
    assert result.evidence_count == 5 and not result.coverage_gaps
    raw = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    assert {r["status"] for r in raw} == {"pass", "observed"}
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="cloudflare-test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    results = [r for r in assessment["asset_results"] if r["asset_id"] == f"cloudflare:zone:{ZONE}"]
    assert {r["safeguard_id"] for r in results} == {"SG-DATAPROTECTION-001", "SG-NETWORK-001"}
    assert all(r["status"] == "not_evaluated" for r in results)
    assert all(r["invalid_binding_count"] == 0 for r in assessment["safeguards"])


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("min_tls_version", "1.0"),
        ("always_use_https", "off"),
        ("security_header", {"strict_transport_security": {"enabled": False}}),
    ],
)
def test_disabled_settings_are_open(monkeypatch: pytest.MonkeyPatch, setting: str, value: Any) -> None:
    fake_api(
        monkeypatch, {f"zones/{ZONE}/settings/{setting}": {"success": True, "result": {"id": setting, "value": value}}}
    )
    row = next(r for r in collect() if r["event_type"] == f"cloudflare.{setting}")
    assert row["status"] == "open"


@pytest.mark.parametrize(
    "payload", [{}, {"success": False, "errors": [{"message": TOKEN}]}, {"success": True, "result": []}]
)
def test_malformed_read_is_a_gap(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    fake_api(monkeypatch, {f"zones/{ZONE}/settings/min_tls_version": payload})
    rows = collect()
    assert any(r["attributes"].get("collection_gap") for r in rows)
    assert TOKEN not in json.dumps(rows)
    assert not any(r["event_type"] == "cloudflare.min_tls_version" and r["status"] == "pass" for r in rows)


@pytest.mark.parametrize("code", [401, 403, 404])
def test_denied_read_marks_runner_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    fake_api(
        monkeypatch, {f"zones/{ZONE}/dnssec": urllib.error.HTTPError("https://example.com", code, TOKEN, {}, None)}
    )
    monkeypatch.setenv("CF_TEST_TOKEN", TOKEN)
    append_config_event(
        tmp_path,
        connector_id="cloudflare-zones",
        state="enabled",
        actor="test",
        credentials={"credential_ref": "CF_TEST_TOKEN"},
    )
    result = run_connector_sync(tmp_path, connector_id="cloudflare-zones", materialize=False)
    assert result.coverage_gaps
    assert latest_run(tmp_path, "cloudflare-zones", kind="sync")["metadata"]["partial"] is True
    assert TOKEN not in (tmp_path / CONNECTOR_RAW_FILE).read_text()


def test_empty_zone_list_is_not_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api(
        monkeypatch,
        {"zones?page=1&per_page=50": {"success": True, "result": [], "result_info": {"page": 1, "total_pages": 0}}},
    )
    assert collect()[0]["attributes"]["collection_gap"] is True


def test_ids_and_pagination_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_cloudflare import CloudflareClient, collect_cloudflare_evidence

    calls = fake_api(
        monkeypatch,
        {
            "zones?page=1&per_page=50": {
                "success": True,
                "result": [{"id": "../../admin"}],
                "result_info": {"page": 1, "total_pages": 2},
            }
        },
    )
    rows = collect_cloudflare_evidence(CloudflareClient(token=TOKEN, max_pages=1))
    assert rows[0]["attributes"]["collection_gap"] is True
    assert len(calls) == 1


def test_retry_after_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_cloudflare import CloudflareClient
    from security_lakehouse.ingestion import backoff

    attempts = []
    sleeps = []

    def open_request(request: Any, **kwargs: Any) -> io.BytesIO:
        attempts.append(request)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "2"}, None)
        return io.BytesIO(b'{"success":true,"result":[]}')

    monkeypatch.setattr(netguard, "open_public", open_request)
    monkeypatch.setattr(backoff.time, "sleep", sleeps.append)
    assert CloudflareClient(token=TOKEN).get("zones")["result"] == []
    assert sleeps == [2] and len(attempts) == 2


def test_two_pages_and_replay_keep_zone_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_cloudflare import CloudflareClient, collect_cloudflare_evidence

    routes = json.loads(FIXTURE.read_text())
    second = "b" * 32
    for path, response in list(routes.items()):
        if ZONE in path:
            routes[path.replace(ZONE, second)] = response
    routes["zones?page=1&per_page=50"]["result_info"]["total_pages"] = 2
    routes["zones?page=2&per_page=50"] = {
        "success": True,
        "result": [{"id": second, "status": "active", "paused": False}],
        "result_info": {"page": 2, "total_pages": 2},
    }
    calls = fake_api(monkeypatch, routes)
    rows = collect_cloudflare_evidence(CloudflareClient(token=TOKEN))
    assert len(rows) == 10 and len({r["event_id"] for r in rows}) == 10
    assert len(calls) == 12
    assert [r["event_id"] for r in collect()] == [r["event_id"] for r in rows]


def test_bindings_fit_reviewed_catalog_without_changing_definitions(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.safeguards import load_safeguards

    fake_api(monkeypatch)
    safeguards = {r["safeguard_id"]: r for r in load_safeguards()["safeguards"]}
    for row in collect():
        safeguard = safeguards[row["safeguard_ids"][0]]
        assert row["entity"]["asset_type"] in safeguard["asset_types"]
        assert set(row["controls"]) <= {r["control_id"] for r in safeguard["satisfies"]}


def test_unknown_waf_rule_enablement_is_not_a_failure_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_api(
        monkeypatch,
        {
            f"zones/{ZONE}/rulesets/phases/http_request_firewall_managed/entrypoint": {
                "success": True,
                "result": {"rules": [{"action": "execute"}]},
            }
        },
    )
    row = next(r for r in collect() if r["event_type"] == "cloudflare.managed_waf")
    assert row["status"] == "not_evaluated" and row["attributes"]["collection_gap"] is True
