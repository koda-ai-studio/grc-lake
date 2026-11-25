"""Synthetic Kandji API contracts, including incomplete and stale posture."""

from __future__ import annotations

import copy
import io
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import netguard
from security_lakehouse.connector_errors import ConnectorConfigError
from security_lakehouse.connectors_kandji_devices import (
    KandjiDevicesClient,
    KandjiDevicesFixtureClient,
    collect_kandji_devices_evidence,
)
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures/kandji_devices"
NOW = datetime(2026, 11, 25, tzinfo=UTC)
DEVICE = "00000000-0000-4000-8000-000000000001"
LOCK = "00000000-0000-4000-8000-000000000002"
PATCH = "00000000-0000-4000-8000-000000000003"
TOKEN = "synthetic-kandji-token"


def client() -> KandjiDevicesFixtureClient:
    return KandjiDevicesFixtureClient(FIXTURE, subdomain="example", region="us")


def collect(c: Any) -> list[dict[str, Any]]:
    return collect_kandji_devices_evidence(
        c, collected_at=NOW, screen_lock_parameter_id=LOCK, os_patch_parameter_id=PATCH
    )


def test_fixture_posture_binds_encryption_and_preserves_unknown() -> None:
    rows = collect(client())
    assert validate_raw_events(rows) == []
    signals = {r["event_type"].split(".")[-1]: r for r in rows}
    assert signals["encryption"]["status"] == "pass"
    assert signals["encryption"]["safeguard_ids"] == ["SG-ENDPOINTENCRYPTION-001"]
    assert signals["firewall"]["status"] == "open"
    assert signals["screen_lock"]["status"] == "pass"
    assert signals["os_patch"]["status"] == "not_evaluated"
    assert all(r["entity"]["asset_type"] == "managed_device" for r in rows)
    assert "serial_number" not in json.dumps(rows)


def test_stale_device_never_passes_any_signal() -> None:
    c = client()
    c.responses["/api/v1/devices?limit=300&offset=0"][0]["last_check_in"] = "2020-01-01T00:00:00Z"
    assert all(r["status"] != "pass" for r in collect(c))


@pytest.mark.parametrize("value", [None, "true", 1, {}, []])
def test_unknown_encryption_is_not_a_verdict(value: Any) -> None:
    c = client()
    c.responses[f"/api/v1/devices/{DEVICE}/details"]["filevault"]["filevault_enabled"] = value
    row = next(r for r in collect(c) if r["event_type"].endswith(".encryption"))
    assert row["status"] == "not_evaluated"


@pytest.mark.parametrize("subdomain", ["evil.test", "a@evil", "a/b", "a:443", "-bad", "a%2e"])
def test_host_injection_rejected(subdomain: str) -> None:
    with pytest.raises(ConnectorConfigError):
        KandjiDevicesClient(token=TOKEN, subdomain=subdomain)


@pytest.mark.parametrize("payload", [[], {}, [None], [{"device_id": "../../secrets"}]])
def test_empty_and_malformed_inventory_are_gaps(payload: Any) -> None:
    c = client()
    c.responses["/api/v1/devices?limit=300&offset=0"] = payload
    rows = collect(c)
    assert rows and all(r["status"] == "not_evaluated" for r in rows)
    assert rows[0]["attributes"]["collection_gap"] is True


def test_repeated_page_and_budget_exhaustion_are_gaps() -> None:
    c = client()
    row = c.responses["/api/v1/devices?limit=300&offset=0"][0]
    c.responses["/api/v1/devices?limit=300&offset=0"] = [copy.deepcopy(row) for _ in range(300)]
    assert collect(c)[0]["attributes"]["collection_gap"] is True
    c.responses["/api/v1/devices?limit=300&offset=0"] = [
        dict(row, device_id=f"00000000-0000-4000-8000-{i:012d}") for i in range(300)
    ]
    c.max_pages = 1
    assert collect(c)[0]["attributes"]["collection_gap"] is True


@pytest.mark.parametrize("code", [401, 403, 429])
def test_denied_requests_are_safe_gaps(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    def deny(request: Any, **kwargs: Any) -> Any:
        assert request.get_method() == "GET"
        assert request.full_url.startswith("https://example.api.kandji.io/")
        raise urllib.error.HTTPError(request.full_url, code, TOKEN, {}, io.BytesIO(TOKEN.encode()))

    monkeypatch.setattr(netguard, "open_public", deny)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", lambda _: None)
    rows = collect(KandjiDevicesClient(token=TOKEN, subdomain="example"))
    assert rows[0]["attributes"]["collection_gap"] is True
    assert TOKEN not in json.dumps(rows)


def test_missing_detail_preserves_other_device_signals() -> None:
    c = client()
    del c.responses[f"/api/v1/devices/{DEVICE}/details"]
    rows = collect(c)
    assert any(r["event_type"].endswith(".management") for r in rows)
    assert next(r for r in rows if r["event_type"].endswith(".encryption"))["status"] == "not_evaluated"


def test_runner_to_ccf_and_partial_metadata(tmp_path: Path) -> None:
    from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
    from security_lakehouse.connector_state import append_config_event, latest_run
    from security_lakehouse.io import read_json
    from security_lakehouse.pipeline import run_pipeline

    append_config_event(
        tmp_path, connector_id="kandji-devices", state="enabled", actor="test", credentials={"subdomain": "example"}
    )
    result = run_connector_sync(tmp_path, connector_id="kandji-devices", fixture_dir=FIXTURE, materialize=False)
    assert result.coverage_gaps
    assert latest_run(tmp_path, "kandji-devices", kind="sync")["metadata"]["partial"] is True
    run_pipeline(tmp_path / CONNECTOR_RAW_FILE, tmp_path / "out", tenant_id="kandji-test")
    assessment = read_json(tmp_path / "out/gold/ccf_assessment.json")
    encryption = next(r for r in assessment["safeguards"] if r["safeguard_id"] == "SG-ENDPOINTENCRYPTION-001")
    assert encryption["assessed_asset_count"] == 1
    assert encryption["invalid_binding_count"] == 0


def test_retry_after_and_cursor_never_change_host(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    calls: list[str] = []

    def read(request: Any, **kwargs: Any) -> Any:
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "rate limit", {"Retry-After": "2"}, None)
        assert request.get_method() == "GET"
        assert request.full_url.startswith("https://example.api.eu.kandji.io/")
        return io.BytesIO(b"[]")

    monkeypatch.setattr(netguard, "open_public", read)
    monkeypatch.setattr("security_lakehouse.ingestion.backoff.time.sleep", sleeps.append)
    assert collect(KandjiDevicesClient(token=TOKEN, subdomain="example", region="eu"))[0]["status"] == "not_evaluated"
    assert sleeps == [2.0] and len(calls) == 2


def test_prism_foreign_url_is_only_an_encoded_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connectors_kandji_devices import _list

    calls: list[str] = []

    def read(request: Any, **kwargs: Any) -> Any:
        calls.append(request.full_url)
        payload = {"data": [], "cursor": "https://evil.example/path" if len(calls) == 1 else None}
        assert request.full_url.startswith("https://example.api.kandji.io/")
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(netguard, "open_public", read)
    assert (
        _list(KandjiDevicesClient(token=TOKEN, subdomain="example"), "/api/v1/prism/application_firewall", prism=True)
        == []
    )
    assert "cursor=https%3A%2F%2Fevil.example%2Fpath" in calls[1]


def test_inventory_offset_pages_and_stable_ids() -> None:
    from security_lakehouse.connectors_kandji_devices import _list

    c = client()
    row = c.responses["/api/v1/devices?limit=300&offset=0"][0]
    c.responses["/api/v1/devices?limit=300&offset=0"] = [
        dict(row, device_id=f"00000000-0000-4000-8000-{i:012d}") for i in range(300)
    ]
    c.responses["/api/v1/devices?limit=300&offset=300"] = [dict(row, device_id="00000000-0000-4000-8000-000000000300")]
    assert len(_list(c, "/api/v1/devices")) == 301
    assert [r["event_id"] for r in collect(client())] == [r["event_id"] for r in collect(client())]


def test_live_runner_requires_explicit_secret_reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from security_lakehouse.connector_runner import ConnectorSyncError, run_connector_sync
    from security_lakehouse.connector_state import append_config_event

    monkeypatch.setenv("KANDJI_API_TOKEN", TOKEN)
    append_config_event(
        tmp_path, connector_id="kandji-devices", state="enabled", actor="test", credentials={"subdomain": "example"}
    )
    with pytest.raises(ConnectorSyncError, match="credential_ref"):
        run_connector_sync(tmp_path, connector_id="kandji-devices", materialize=False)


def test_unresolved_reference_does_not_fall_back_to_another_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from security_lakehouse.connector_runner import ConnectorSyncError, run_connector_sync
    from security_lakehouse.connector_state import append_config_event

    monkeypatch.setenv("KANDJI_API_TOKEN", TOKEN)
    monkeypatch.delenv("KANDJI_MISSING_REF", raising=False)

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Unresolved reference attempted a network request")

    monkeypatch.setattr(netguard, "open_public", unexpected)
    append_config_event(
        tmp_path,
        connector_id="kandji-devices",
        state="enabled",
        actor="test",
        credentials={"subdomain": "example", "credential_ref": "KANDJI_MISSING_REF"},
    )
    with pytest.raises(ConnectorSyncError, match="could not be resolved"):
        run_connector_sync(tmp_path, connector_id="kandji-devices", materialize=False)
