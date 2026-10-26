"""Provider device verdicts retain scope, unknowns and proposed mapping boundaries."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.safeguards import load_safeguards

FIXTURES = Path(__file__).parent / "fixtures"
ENCRYPTION = "SG-ENDPOINTENCRYPTION-001"
PREVENTION = "SG-ENDPOINTPREVENTION-001"
CASES = [
    ("intune-devices", "intune", ENCRYPTION, "managed_device"),
    ("jamf-devices", "jamf", ENCRYPTION, "managed_device"),
    ("crowdstrike-falcon", "crowdstrike", PREVENTION, "endpoint_host"),
]


def sync(lake, connector, fixture):
    append_config_event(
        lake,
        connector_id=connector,
        state="enabled",
        actor="fixture-reviewer",
        credentials={
            "tenant_id": "fixture-tenant",
            "base_url": "https://fixture.jamfcloud.com",
            "client_id": "fixture-client",
            "client_secret_ref": "FIXTURE_SECRET",
            "cloud": "us-1",
        },
    )
    assert run_connector_sync(lake, connector_id=connector, fixture_dir=fixture).result == "ok"
    return read_json(lake / "gold/ccf_assessment.json")


@pytest.mark.parametrize("connector,fixture,sid,asset_type", CASES)
def test_device_fixture_verdict_reaches_compatible_safeguard_and_never_approves_mapping(
    tmp_path, connector, fixture, sid, asset_type
):
    lake = tmp_path / "lake"
    assessment = sync(lake, connector, FIXTURES / fixture)
    rows = [r for r in assessment["asset_results"] if r["safeguard_id"] == sid]
    assert rows and any(r["status"] == "fail" for r in rows)
    definition = next(e for e in load_safeguards()["safeguards"] if e["safeguard_id"] == sid)
    assert definition["asset_types"] == [asset_type]
    assert all(m["review_status"] == "proposed" and not m.get("maintainer_review_ref") for m in definition["satisfies"])
    controls = {m["control_id"] for m in definition["satisfies"]}
    raw = [r for r in read_jsonl(lake / CONNECTOR_RAW_FILE) if sid in r.get("safeguard_ids", [])]
    assert raw and all(set(r["controls"]) <= controls for r in raw)
    assert all(r["entity"]["asset_type"] == asset_type for r in raw)
    assert all(sid not in r["reviewed_safeguard_ids"] for r in assessment["requirements"])
    assert not any(r["status"] == "pass" for r in assessment["requirements"] if r["control_id"] in controls)


@pytest.mark.parametrize("encrypted", [None, "true", 1])
def test_unknown_intune_encryption_is_not_an_asserted_failure_or_pass(tmp_path, encrypted):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "managed_devices.json").write_text(json.dumps([{"id": "device-1", "isEncrypted": encrypted}]))
    lake = tmp_path / "lake"
    result = sync(lake, "intune-devices", fixture)
    row = next(r for r in read_jsonl(lake / CONNECTOR_RAW_FILE) if r["event_type"] == "intune.device.encryption")
    assert row["status"] == "not_evaluated"
    assert next(r for r in result["safeguards"] if r["safeguard_id"] == ENCRYPTION)["status"] == "not_evaluated"


def test_missing_jamf_encryption_is_not_evaluated(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "computers.json").write_text(json.dumps([{"id": "device-1"}]))
    (fixture / "mobile_devices.json").write_text("[]")
    lake = tmp_path / "lake"
    sync(lake, "jamf-devices", fixture)
    row = next(r for r in read_jsonl(lake / CONNECTOR_RAW_FILE) if r["event_type"] == "jamf.device.encryption")
    assert row["status"] == "not_evaluated"


def test_unreadable_crowdstrike_policy_details_do_not_assert_failure_or_pass(tmp_path):
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURES / "crowdstrike", fixture)
    (fixture / "prevention_policies.json").write_text("[]")
    lake = tmp_path / "lake"
    sync(lake, "crowdstrike-falcon", fixture)
    rows = [r for r in read_jsonl(lake / CONNECTOR_RAW_FILE) if r["event_type"] == "crowdstrike.host.prevention_policy"]
    unknown = [r for r in rows if r["attributes"]["finding_reason"] == "policy_not_found"]
    assert unknown and all(r["status"] == "not_evaluated" for r in unknown)


def test_passing_intune_encryption_is_operating_evidence_only(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "managed_devices.json").write_text(json.dumps([{"id": "device-1", "isEncrypted": True}]))
    result = sync(tmp_path / "lake", "intune-devices", fixture)
    assert next(r for r in result["safeguards"] if r["safeguard_id"] == ENCRYPTION)["status"] == "pass"
    assert (
        next(r for r in result["requirements"] if r["control_id"] == "NIST-800-53-SC-28.1")["status"] == "not_evaluated"
    )


def test_jamf_mobile_missing_encryption_blocks_a_passing_population(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "computers.json").write_text("[]")
    (fixture / "mobile_devices.json").write_text(
        json.dumps(
            [
                {"mobileDeviceId": "encrypted", "security": {"dataProtected": True}},
                {"mobileDeviceId": "unknown", "security": {}},
            ]
        )
    )
    result = sync(tmp_path / "lake", "jamf-devices", fixture)
    assert next(r for r in result["safeguards"] if r["safeguard_id"] == ENCRYPTION)["status"] == "not_evaluated"


def test_conflicting_jamf_encryption_reports_cannot_pass(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "computers.json").write_text(
        json.dumps(
            [
                {
                    "id": "device-1",
                    "operatingSystem": {"fileVault2Status": "ALL_ENCRYPTED"},
                    "diskEncryption": {"bootPartitionEncryptionDetails": {"partitionFileVault2State": "UNENCRYPTED"}},
                }
            ]
        )
    )
    (fixture / "mobile_devices.json").write_text("[]")
    result = sync(tmp_path / "lake", "jamf-devices", fixture)
    assert next(r for r in result["safeguards"] if r["safeguard_id"] == ENCRYPTION)["status"] == "not_evaluated"


@pytest.mark.parametrize("field", ["reduced_functionality_mode", "applied"])
def test_missing_crowdstrike_state_remains_unknown_in_verdict_and_attributes(tmp_path, field):
    fixture = tmp_path / "fixture"
    shutil.copytree(FIXTURES / "crowdstrike", fixture)
    payload = json.loads((fixture / "hosts.json").read_text())
    host = payload["resources"][0]
    host["last_seen"] = datetime.now(UTC).isoformat()
    if field == "applied":
        host["device_policies"]["prevention"].pop(field)
    else:
        host.pop(field)
    payload["resources"] = [host]
    (fixture / "hosts.json").write_text(json.dumps(payload))
    lake = tmp_path / "lake"
    result = sync(lake, "crowdstrike-falcon", fixture)
    signal = "host.sensor" if field == "reduced_functionality_mode" else "host.prevention_policy"
    row = next(r for r in read_jsonl(lake / CONNECTOR_RAW_FILE) if r["event_type"] == f"crowdstrike.{signal}")
    assert row["status"] == "not_evaluated"
    key = field if field == "reduced_functionality_mode" else "prevention_policy_applied"
    assert row["attributes"][key] is None
    assert next(r for r in result["safeguards"] if r["safeguard_id"] == PREVENTION)["status"] == "not_evaluated"
