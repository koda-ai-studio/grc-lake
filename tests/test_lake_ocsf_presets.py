"""Built-in OCSF mapping presets against realistic Amazon Security Lake rows."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_json
from security_lakehouse.lake_mapping import (
    compile_select,
    list_presets,
    load_preset,
    map_rows,
    read_fixture_table,
    resolve_mapping_ref,
    resolve_mappings,
)
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.validation import validate_raw_events

FIXTURES = Path(__file__).parent / "fixtures" / "ocsf"
REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTED = datetime(2026, 9, 22, tzinfo=UTC)
EXPECTED_PRESETS = {
    "ocsf/authentication": 3002,
    "ocsf/account_change": 3001,
    "ocsf/api_activity": 6003,
    "ocsf/detection_finding": 2004,
    "ocsf/vulnerability_finding": 2002,
    "ocsf/compliance_finding": 2003,
    "ocsf/security_finding": 2001,
}


def _preset(name: str, table: str = "amazon_security_lake_table_us_east_1_sh_findings_2_0"):
    return resolve_mapping_ref({"preset": name, "source": {"table": table}})


def _catalog_control_ids() -> set[str]:
    catalog = json.loads((REPO_ROOT / "controls" / "catalog.json").read_text(encoding="utf-8"))
    return {control["control_id"] for control in catalog["controls"]}


def test_every_expected_preset_ships_and_parses() -> None:
    assert set(list_presets()) == set(EXPECTED_PRESETS)
    for name, class_uid in EXPECTED_PRESETS.items():
        spec = _preset(name)
        assert spec.preset == name
        assert [(f.column, f.op, f.value) for f in spec.filters] == [("class_uid", "eq", class_uid)]
        assert "OCSF 1." in spec.description, "each preset must cite the OCSF version it targets"


def test_preset_control_hints_exist_in_the_control_catalog() -> None:
    known = _catalog_control_ids()
    for name in EXPECTED_PRESETS:
        controls = load_preset(name)["fields"]["controls"]["const"]
        assert controls, name
        assert set(controls) <= known, (name, set(controls) - known)


def test_cloudtrail_table_splits_into_the_three_activity_classes() -> None:
    rows = read_fixture_table(FIXTURES, "cloud_trail_mgmt_2_0")
    by_class = {}
    for name in ("ocsf/authentication", "ocsf/account_change", "ocsf/api_activity"):
        result = map_rows(_preset(name, "cloud_trail_mgmt_2_0"), rows, collected_at=COLLECTED)
        assert result.errors == []
        assert validate_raw_events(result.events) == []
        by_class[name] = result.events
    assert [len(events) for events in by_class.values()] == [1, 1, 1]

    [auth] = by_class["ocsf/authentication"]
    assert auth["event_type"] == "ocsf.authentication"
    assert auth["source"] == "CloudTrail"
    assert auth["event_time"] == "2026-09-21T14:03:11Z"
    assert auth["entity"]["asset_id"] == "AIDAEXAMPLEALICE"
    # a failed sign-in is activity evidence, not a control failure
    assert auth["status"] == "observed"
    assert auth["attributes"]["outcome"] == "Failure"
    assert auth["attributes"]["is_mfa"] is False
    assert auth["attributes"]["cloud_account"] == "111122223333"
    assert "SOC2-CC6.1" in auth["controls"]

    [change] = by_class["ocsf/account_change"]
    assert change["entity"]["asset_id"] == "AIDAEXAMPLEBOT"
    assert change["attributes"]["actor"] == "platform-admin"

    [api] = by_class["ocsf/api_activity"]
    assert api["entity"]["asset_id"] == "arn:aws:s3:::acme-audit-logs"
    assert api["entity"]["asset_type"] == "AWS::S3::Bucket"
    assert api["attributes"]["api_operation"] == "PutBucketPolicy"


def test_security_hub_v2_table_splits_into_finding_classes() -> None:
    rows = read_fixture_table(FIXTURES, "sh_findings_2_0")

    detection = map_rows(_preset("ocsf/detection_finding"), rows, collected_at=COLLECTED).events
    assert len(detection) == 1
    assert detection[0]["severity"] == "high"
    assert detection[0]["status"] == "open"
    assert detection[0]["source"] == "GuardDuty"
    assert detection[0]["entity"]["asset_id"].endswith("instance/i-0abc1234def567890")
    assert detection[0]["evidence"]["evidence_ref"].startswith("https://console.aws.amazon.com/guardduty/")

    vulnerability = map_rows(_preset("ocsf/vulnerability_finding"), rows, collected_at=COLLECTED).events
    assert len(vulnerability) == 1
    assert vulnerability[0]["severity"] == "critical"
    assert vulnerability[0]["attributes"]["cve"] == "CVE-2024-3094"
    assert vulnerability[0]["attributes"]["fix_available"] is True

    compliance = map_rows(_preset("ocsf/compliance_finding"), rows, collected_at=COLLECTED).events
    statuses = {event["attributes"]["compliance_control"]: event["status"] for event in compliance}
    assert statuses == {"IAM.6": "open", "S3.1": "pass"}
    assert validate_raw_events(detection + vulnerability + compliance) == []


def test_legacy_security_finding_reads_ocsf_rc2_rows() -> None:
    rows = read_fixture_table(FIXTURES, "sh_findings_1_0")
    [event] = map_rows(_preset("ocsf/security_finding", "sh_findings_1_0"), rows, collected_at=COLLECTED).events
    assert event["event_time"] == "2026-09-20T10:26:40Z"
    assert event["status"] == "open"
    assert event["severity"] == "high"
    assert event["attributes"]["cloud_account"] == "111122223333"
    assert event["attributes"]["ocsf_version"] == "1.0.0-rc.2"


def test_finding_ids_are_stable_so_updates_replace_prior_state() -> None:
    rows = read_fixture_table(FIXTURES, "sh_findings_2_0")
    spec = _preset("ocsf/compliance_finding")
    first = map_rows(spec, rows).events
    resolved = [dict(row, status_id=4, status="Resolved") for row in rows]
    second = map_rows(spec, resolved).events
    assert [e["event_id"] for e in first] == [e["event_id"] for e in second]


def test_connector_options_accept_preset_references_alongside_inline_specs() -> None:
    specs = resolve_mappings(
        {
            "mappings": [
                {"preset": "ocsf/authentication", "source": {"table": "db.cloudtrail"}},
                {"preset": "ocsf/api_activity", "source": {"table": "db.cloudtrail"}},
            ]
        }
    )
    assert [(s.name, s.source_table) for s in specs] == [
        ("ocsf_authentication", "db.cloudtrail"),
        ("ocsf_api_activity", "db.cloudtrail"),
    ]


def test_preset_overrides_merge_onto_the_preset() -> None:
    spec = resolve_mapping_ref(
        {
            "preset": "ocsf/api_activity",
            "source": {"table": "db.custom_ocsf", "lookback_minutes": 5},
            "fields": {"observed_at": {"column": "time", "format": "epoch_ms"}},
        }
    )
    assert spec.observed_column == "time"
    assert spec.lookback_minutes == 5
    assert spec.fields["event_type"].const == "ocsf.api_activity"


@pytest.mark.parametrize("dialect", ["snowflake", "databricks", "clickhouse", "bigquery"])
def test_every_preset_compiles_for_every_sql_dialect(dialect: str) -> None:
    for name in EXPECTED_PRESETS:
        query = compile_select(
            _preset(name, "sec.amazon_security_lake_table"),
            dialect,
            since="2026-09-21T00:00:00Z",
            limit=100,
        )
        assert query.sql.startswith("SELECT ")
        assert "2026" not in query.sql
        assert query.params["since"]


# --------------------------------------------------------------------------------
# OCSF -> CCF safeguard binding
# --------------------------------------------------------------------------------

IDENTITY_TABLE = "ocsf_identity_events"


def _safeguards() -> dict[str, dict[str, Any]]:
    payload = json.loads((REPO_ROOT / "controls" / "safeguards.json").read_text(encoding="utf-8"))
    return {row["safeguard_id"]: row for row in payload["safeguards"]}


def _mapped(name: str) -> dict[str, dict[str, Any]]:
    rows = read_fixture_table(FIXTURES, IDENTITY_TABLE)
    result = map_rows(_preset(name, IDENTITY_TABLE), rows, collected_at=COLLECTED)
    assert result.errors == []
    assert validate_raw_events(result.events) == []
    return {event["attributes"]["source_id"][0]: event for event in result.events}


def _outcome(event: dict[str, Any]) -> tuple[str, list[str], str | None]:
    return event["status"], event.get("safeguard_ids", []), event["attributes"].get("mapping_rule")


def test_authentication_rules_judge_only_successful_logons_by_mfa() -> None:
    events = _mapped("ocsf/authentication")
    assert {key: _outcome(event) for key, event in events.items()} == {
        "syn-auth-0001": ("pass", ["SG-IDENTITY-001"], "mfa_sign_in"),
        "syn-auth-0002": ("open", ["SG-IDENTITY-001"], "sign_in_without_mfa"),
        # a failed sign-in records an attempt, not control effectiveness
        "syn-auth-0003": ("observed", [], None),
        # the source did not say whether MFA was used
        "syn-auth-0004": ("observed", [], None),
        # a logoff says nothing about how the session was authenticated
        "syn-auth-0005": ("observed", [], None),
    }
    assert events["syn-auth-0002"]["severity"] == "medium"
    # verdict rows carry only the authentication tags the verdict is about
    assert events["syn-auth-0001"]["controls"] == ["SOC2-CC6.1", "ISO27001-A.8.5", "NIST-800-53-IA-2"]
    assert "NIST-800-53-AU-2" in events["syn-auth-0003"]["controls"]
    assert {event["entity"]["asset_type"] for event in events.values()} == {"identity_user"}


def test_account_change_flags_successful_privilege_grants_for_review() -> None:
    events = _mapped("ocsf/account_change")
    assert {key: _outcome(event) for key, event in events.items()} == {
        "syn-acct-0001": ("not_evaluated", ["SG-IDENTITY-002"], "privilege_grant"),
        "syn-acct-0002": ("observed", [], None),  # the grant failed, so nothing changed
        "syn-acct-0003": ("observed", [], None),
    }
    # the rule leaves framework tags alone
    assert events["syn-acct-0001"]["controls"] == events["syn-acct-0003"]["controls"]


def test_api_activity_stays_presence_only_logging_evidence() -> None:
    rows = read_fixture_table(FIXTURES, "cloud_trail_mgmt_2_0")
    [event] = map_rows(_preset("ocsf/api_activity", "cloud_trail_mgmt_2_0"), rows, collected_at=COLLECTED).events
    assert event["status"] == "observed"
    assert "safeguard_ids" not in event
    assert load_preset("ocsf/api_activity").get("rules") is None


def test_preset_rules_bind_catalog_safeguards_that_apply_to_the_asset_type() -> None:
    safeguards = _safeguards()
    known = _catalog_control_ids()
    bound = 0
    for name in EXPECTED_PRESETS:
        payload = load_preset(name)
        asset_type = payload["fields"]["asset_type"]
        for rule in payload.get("rules", []):
            for safeguard_id in rule.get("safeguard_ids", []):
                bound += 1
                # a type the safeguard does not list would be an invalid binding in the assessment
                assert asset_type == {"const": asset_type.get("const")}, name
                assert asset_type["const"] in safeguards[safeguard_id]["asset_types"], (name, safeguard_id)
            controls = rule.get("controls")
            if controls is None:
                continue
            assert set(controls) <= known, (name, rule["name"])
            # framework tags on a verdict row must be requirements the bound safeguards map to
            members = {
                member["control_id"]
                for safeguard_id in rule.get("safeguard_ids", [])
                for member in safeguards[safeguard_id]["satisfies"]
            }
            assert set(controls) <= members, (name, rule["name"], set(controls) - members)
    assert bound == 3


def test_disabling_rules_restores_presence_only_mapping() -> None:
    rows = read_fixture_table(FIXTURES, IDENTITY_TABLE)
    spec = resolve_mapping_ref({"preset": "ocsf/authentication", "source": {"table": IDENTITY_TABLE}, "rules": []})
    events = map_rows(spec, rows, collected_at=COLLECTED).events
    assert {event["status"] for event in events} == {"observed"}
    assert not any("safeguard_ids" in event for event in events)


def _fresh_fixture(target: Path) -> Path:
    """Copy the identity fixture with current timestamps so freshness does not decide the verdict."""
    target.mkdir()
    rows = read_fixture_table(FIXTURES, IDENTITY_TABLE)
    base = datetime.now(UTC) - timedelta(hours=2)
    for offset, row in enumerate(rows):
        row["time_dt"] = (base + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (target / f"{IDENTITY_TABLE}.json").write_text(json.dumps(rows), encoding="utf-8")
    return target


def test_ocsf_rows_reach_the_ccf_assessment_through_sync_and_pipeline(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    append_config_event(
        lake,
        connector_id="databricks-evidence-lake",
        state="enabled",
        actor="t",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={
            "mappings": [
                {"preset": "ocsf/authentication", "source": {"table": IDENTITY_TABLE}},
                {"preset": "ocsf/account_change", "source": {"table": IDENTITY_TABLE}},
            ]
        },
    )
    synced = run_connector_sync(
        lake,
        connector_id="databricks-evidence-lake",
        fixture_dir=_fresh_fixture(tmp_path / "fixtures"),
        materialize=False,
    )
    assert synced.evidence_count == 8
    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="ocsf-test")
    assessment = read_json(out / "gold" / "ccf_assessment.json")

    by_asset = {
        (row["safeguard_id"], row["asset_id"]): row
        for row in assessment["asset_results"]
        if row["safeguard_id"] in {"SG-IDENTITY-001", "SG-IDENTITY-002"}
    }
    assert {key: row["status"] for key, row in by_asset.items()} == {
        ("SG-IDENTITY-001", "user-alice"): "pass",
        ("SG-IDENTITY-001", "user-bob"): "fail",
        ("SG-IDENTITY-002", "user-build-bot"): "not_evaluated",
    }
    assert any(
        "unknown or unevaluated" in reason for reason in by_asset[("SG-IDENTITY-002", "user-build-bot")]["reasons"]
    )

    safeguards = {row["safeguard_id"]: row for row in assessment["safeguards"]}
    identity = safeguards["SG-IDENTITY-001"]
    assert identity["status"] == "fail"
    # carol, dave, erin, frank, and build-bot were observed without MFA evidence: never silently passed
    assert (identity["assessed_asset_count"], identity["unassessed_asset_count"]) == (2, 5)
    assert identity["invalid_binding_count"] == 0

    # framework requirements come from the reviewed crosswalk, not from the preset's tags
    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    assert requirements["SOC2-CC6.1"]["status"] == "fail"
    assert requirements["SOC2-CC6.1"]["reviewed_safeguard_ids"] == ["SG-IDENTITY-001"]
    assert requirements["CIS-AWS-1.10"]["status"] == "fail"  # tagged nowhere in the preset
    # a proposed mapping is never attested, even when the safeguard has evidence
    iso = requirements["ISO27001-A.8.5"]
    assert "SG-IDENTITY-001" not in iso["reviewed_safeguard_ids"]
    assert iso["pending_mapping_count"] >= 1
    assert iso["status"] != "pass"
    assert requirements["SOC2-CC6.2"]["status"] == "not_evaluated"
