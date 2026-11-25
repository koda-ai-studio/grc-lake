"""Offline PagerDuty collection and evidence semantics."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import netguard
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.pipeline import run_pipeline

FIXTURE = Path(__file__).parent / "fixtures/pagerduty"
NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
TOKEN = "synthetic-pagerduty-token"


def collect() -> list[dict[str, Any]]:
    from security_lakehouse.connectors_pagerduty import PagerDutyClient, collect_pagerduty_evidence

    return collect_pagerduty_evidence(PagerDutyClient(token=TOKEN, account="example"), collected_at=NOW)


def fake(monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any] | None = None) -> list[str]:
    routes = json.loads((FIXTURE / "responses.json").read_text())
    routes.update(overrides or {})
    calls: list[str] = []

    def read(request: Any, **kwargs: Any) -> io.BytesIO:
        assert request.get_method() == "GET"
        url = urllib.parse.urlsplit(request.full_url)
        assert url.scheme == "https" and url.netloc == "api.pagerduty.com"
        assert request.get_header("Authorization") == f"Token token={TOKEN}"
        params = urllib.parse.parse_qs(url.query)
        assert params["limit"] == ["100"]
        key = url.path.lstrip("/") + ":" + params["offset"][0]
        calls.append(key)
        value = routes[key]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(netguard, "open_public", read)
    return calls


def test_pagerduty_runner_to_ccf(tmp_path: Path) -> None:
    append_config_event(
        tmp_path, connector_id="pagerduty-incidents", state="enabled", actor="test", credentials={"account": "example"}
    )
    result = run_connector_sync(tmp_path, connector_id="pagerduty-incidents", fixture_dir=FIXTURE, materialize=False)
    assert result.evidence_count >= 4
    rows = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    assert any(r["attributes"].get("incident_id") == "PINC001" and r["status"] == "open" for r in rows)
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="pd-test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    sg = next(r for r in assessment["safeguards"] if r["safeguard_id"] == "SG-INCIDENTHANDLING-001")
    assert sg["assessed_asset_count"] > 0 and sg["invalid_binding_count"] == 0 and sg["status"] == "not_evaluated"


def test_incident_timing_and_oncall_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch)
    rows = collect()
    incident = next(r for r in rows if r["attributes"].get("incident_id") == "PINC002")
    assert incident["attributes"]["time_to_acknowledge_seconds"] == 600
    assert incident["attributes"]["time_to_resolve_seconds"] == 3600
    assert incident["status"] == "observed"  # closure is not proof of containment or root cause
    service = next(
        r
        for r in rows
        if r["event_type"] == "pagerduty.service.coverage" and r["attributes"]["service_id"] == "PSVC001"
    )
    assert service["attributes"]["oncall_covered"] is True
    missing = next(
        r
        for r in rows
        if r["event_type"] == "pagerduty.service.coverage" and r["attributes"]["service_id"] == "PSVC002"
    )
    assert missing["status"] == "not_evaluated" and missing["attributes"]["collection_gap"] is True


@pytest.mark.parametrize("code", [401, 403, 429])
def test_denied_oncall_scope_is_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    fake(
        monkeypatch,
        {"oncalls:0": urllib.error.HTTPError("https://example.com", code, TOKEN, {"Retry-After": "301"}, None)},
    )
    monkeypatch.setenv("PD_TEST_TOKEN", TOKEN)
    append_config_event(
        tmp_path,
        connector_id="pagerduty-incidents",
        state="enabled",
        actor="test",
        credentials={"account": "example", "credential_ref": "PD_TEST_TOKEN"},
    )
    result = run_connector_sync(tmp_path, connector_id="pagerduty-incidents", materialize=False)
    assert (
        result.coverage_gaps and latest_run(tmp_path, "pagerduty-incidents", kind="sync")["metadata"]["partial"] is True
    )
    assert TOKEN not in (tmp_path / CONNECTOR_RAW_FILE).read_text()


def test_missing_logs_preserve_overdue_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, {"incidents/PINC001/log_entries:0": {"log_entries": None, "more": False}})
    row = next(r for r in collect() if r["attributes"].get("incident_id") == "PINC001")
    assert row["status"] == "open" and row["attributes"]["collection_gap"] is True
    assert row["attributes"]["time_to_acknowledge_seconds"] is None


def test_empty_scopes_do_not_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, {"incidents:0": {"incidents": [], "more": False}, "services:0": {"services": [], "more": False}})
    rows = collect()
    assert any(r["attributes"].get("collection_gap") for r in rows)
    assert not any(r["status"] == "pass" for r in rows)


def test_replay_is_stable_and_private_details_are_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch)
    first, second = collect(), collect()
    assert [r["event_id"] for r in first] == [r["event_id"] for r in second]
    assert len({r["event_id"] for r in first}) == len(first)
    assert "private incident description" not in json.dumps(first)


def test_pagination_and_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_pagerduty import PagerDutyClient, collect_pagerduty_evidence

    routes = json.loads((FIXTURE / "responses.json").read_text())
    routes["services:0"]["more"] = True
    routes["services:2"] = {"services": [{"id": "PSVC003", "escalation_policy": None}], "more": False, "offset": 2}
    calls = fake(monkeypatch, routes)
    rows = collect()
    assert "services:2" in calls and any(r["attributes"].get("service_id") == "PSVC003" for r in rows)
    capped = collect_pagerduty_evidence(PagerDutyClient(token=TOKEN, account="example", max_pages=1), collected_at=NOW)
    assert any(r["attributes"].get("reason") == "page_budget_exhausted" for r in capped)


def test_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_pagerduty import PagerDutyClient
    from security_lakehouse.ingestion import backoff

    calls, sleeps = [], []

    def read(request: Any, **kwargs: Any) -> io.BytesIO:
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {"Retry-After": "2"}, None)
        return io.BytesIO(b'{"services":[],"more":false}')

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr(backoff.time, "sleep", sleeps.append)
    assert PagerDutyClient(token=TOKEN, account="example").get("services", {})["services"] == []
    assert sleeps == [2]


def test_untrusted_ids_never_become_request_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = fake(monkeypatch, {"incidents:0": {"incidents": [{"id": "../../users"}], "more": False}})
    rows = collect()
    assert any(r["attributes"].get("collection_gap") for r in rows)
    assert not any(".." in path for path in calls)


def test_unknown_oncall_interval_blocks_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(
        monkeypatch,
        {
            "oncalls:0": {
                "oncalls": [
                    {"escalation_policy": {"id": "PPOL001"}, "user": {"id": "PUSR001"}, "start": "invalid", "end": None}
                ],
                "more": False,
            }
        },
    )
    row = next(r for r in collect() if r["attributes"].get("service_id") == "PSVC001")
    assert row["status"] == "not_evaluated" and row["attributes"]["reason"] == "unknown_oncall_interval"
