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
    "ocsf/group_management": 3006,
    "ocsf/api_activity": 6003,
    "ocsf/detection_finding": 2004,
    "ocsf/vulnerability_finding": 2002,
    "ocsf/compliance_finding": 2003,
    "ocsf/security_finding": 2001,
    "ocsf/config_state": 5002,
    "ocsf/device_inventory": 5001,
    "ocsf/data_security_finding": 2006,
    "ocsf/incident_finding": 2005,
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
    # the CloudTrail type is translated to the catalog's type, as the finding presets do
    assert api["entity"]["asset_type"] == "s3_bucket"
    assert api["attributes"]["resource_type"] == "AWS::S3::Bucket"
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

    # vendor resource types with a clear catalog equivalent are translated; the rest pass through
    assert detection[0]["entity"]["asset_type"] == "host"
    assert vulnerability[0]["entity"]["asset_type"] == "container_image"
    assert {event["entity"]["asset_type"] for event in compliance} == {"AwsAccount"}
    assert detection[0]["attributes"]["resource_type"] == "AwsEc2Instance"
    assert vulnerability[0]["safeguard_ids"] == ["SG-VULNERABILITYMANAGEMENT-001"]
    assert not any("safeguard_ids" in event for event in detection + compliance)
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
FINDING_TABLE = "ocsf_finding_events"
# Presets whose asset type comes from a vendor resource type.
RESOURCE_TYPED_PRESETS = (
    "ocsf/api_activity",
    "ocsf/detection_finding",
    "ocsf/vulnerability_finding",
    "ocsf/compliance_finding",
    "ocsf/security_finding",
)
EC2_A = "arn:aws:ec2:us-east-1:111122223333:instance/i-0aaa1111bbbb22223"
EC2_B = "arn:aws:ec2:us-east-1:111122223333:instance/i-0ccc3333dddd44445"
IMAGE = "arn:aws:ecr:us-east-1:111122223333:repository/api/sha256:5b1f0c"
EC2_C = "arn:aws:ec2:us-east-1:111122223333:instance/i-0eee5555ffff66667"
VULN_SG = "SG-VULNERABILITYMANAGEMENT-001"
BASELINE_SG = "SG-CONFIGBASELINE-001"


def _safeguards() -> dict[str, dict[str, Any]]:
    payload = json.loads((REPO_ROOT / "controls" / "safeguards.json").read_text(encoding="utf-8"))
    return {row["safeguard_id"]: row for row in payload["safeguards"]}


def _mapped(name: str, table: str = IDENTITY_TABLE) -> dict[str, dict[str, Any]]:
    rows = read_fixture_table(FIXTURES, table)
    result = map_rows(_preset(name, table), rows, collected_at=COLLECTED)
    assert result.errors == []
    assert validate_raw_events(result.events) == []
    keys = [event["attributes"]["source_id"] for event in result.events]
    # a multi-column id keeps every part; a single-column id is the value itself
    return {key[0] if isinstance(key, list) else key: event for key, event in zip(keys, result.events, strict=True)}


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
    # a grant carries only tags inside SG-IDENTITY-002's crosswalk; other rows keep the preset's
    assert events["syn-acct-0001"]["controls"] == ["SOC2-CC6.2", "ISO27001-A.5.18"]
    assert events["syn-acct-0003"]["controls"] == load_preset("ocsf/account_change")["fields"]["controls"]["const"]


def test_api_activity_stays_presence_only_logging_evidence() -> None:
    rows = read_fixture_table(FIXTURES, "cloud_trail_mgmt_2_0")
    [event] = map_rows(_preset("ocsf/api_activity", "cloud_trail_mgmt_2_0"), rows, collected_at=COLLECTED).events
    assert event["status"] == "observed"
    assert "safeguard_ids" not in event
    assert load_preset("ocsf/api_activity").get("rules") is None


def test_group_management_flags_successful_membership_and_privilege_grants_for_review() -> None:
    events = _mapped("ocsf/group_management")
    assert {key: _outcome(event) for key, event in events.items()} == {
        "syn-grp-0001": ("not_evaluated", ["SG-IDENTITY-002"], "group_privilege_grant"),  # Add User
        "syn-grp-0002": ("not_evaluated", ["SG-IDENTITY-002"], "group_privilege_grant"),  # Assign Privileges
        "syn-grp-0003": ("observed", [], None),  # the add failed, so nothing changed
        "syn-grp-0004": ("observed", [], None),  # removing access is not a grant
        "syn-grp-0005": ("observed", [], None),  # creating an empty group grants nothing
    }
    assert {event["entity"]["asset_id"] for event in events.values()} == {
        "group-admins",
        "group-readers",
        "group-contractors",
    }
    assert {event["entity"]["asset_type"] for event in events.values()} == {"identity_group"}
    # nothing here is a failure: a grant is pending review, never open
    assert not any(event["status"] in {"open", "pass"} for event in events.values())
    assert events["syn-grp-0001"]["severity"] == "medium"
    assert events["syn-grp-0001"]["attributes"]["member"] == "carol@example.com"
    assert events["syn-grp-0002"]["attributes"]["privileges"] == ["s3:GetObject", "logs:GetLogEvents"]


def test_finding_rules_bind_translated_resources_to_the_fitting_safeguard() -> None:
    def outcomes(name: str) -> dict[str, tuple[str, list[str], str | None, str]]:
        events = _mapped(name, FINDING_TABLE)
        return {key: (*_outcome(event), event["entity"]["asset_type"]) for key, event in events.items()}

    assert outcomes("ocsf/vulnerability_finding") == {
        "syn-vuln-0001": ("open", [VULN_SG], "vulnerability_management", "host"),
        "syn-vuln-0002": ("pass", [VULN_SG], "vulnerability_management", "container_image"),
        # suppressed: bound, but an observation supplies no verdict
        "syn-vuln-0003": ("observed", [VULN_SG], "vulnerability_management", "host"),
        # no clear catalog equivalent: the vendor type passes through and nothing is bound
        "syn-vuln-0004": ("open", [], None, "AwsLambdaFunction"),
    }
    assert outcomes("ocsf/compliance_finding") == {
        "syn-comp-0001": ("open", [BASELINE_SG], "configuration_baseline", "host"),
        # no clear catalog equivalent for an IAM permissions policy
        "syn-comp-0002": ("pass", [], None, "AwsIamPolicy"),
        # translated, but the baseline safeguard does not list s3_bucket
        "syn-comp-0003": ("pass", [], None, "s3_bucket"),
        "syn-comp-0004": ("open", [], None, "AwsAccount"),
        "syn-comp-0005": ("observed", [BASELINE_SG], "configuration_baseline", "host"),  # Warning
        "syn-comp-0006": ("pass", [BASELINE_SG], "configuration_baseline", "host"),
    }
    # a threat detection is not a monitoring failure, so it binds nothing
    assert outcomes("ocsf/detection_finding") == {"syn-det-0001": ("open", [], None, "host")}
    assert outcomes("ocsf/api_activity") == {"syn-api-0001": ("observed", [], None, "host")}


def test_resource_typed_presets_translate_vendor_types_identically() -> None:
    maps = {name: load_preset(name)["fields"]["asset_type"]["map"] for name in RESOURCE_TYPED_PRESETS}
    reference = maps["ocsf/vulnerability_finding"]
    # one asset seen with two types is ambiguous, which invalidates every binding on it
    assert all(mapping == reference for mapping in maps.values()), maps
    catalog_types = {asset_type for row in _safeguards().values() for asset_type in row["asset_types"]}
    assert set(reference.values()) <= catalog_types
    # only specific equivalents: nothing is widened to the generic fallback type
    assert "cloud_resource" not in reference.values()
    for unmapped in ("AwsAccount", "AwsLambdaFunction", "AwsIamPolicy", "AWS::IAM::Policy"):
        assert unmapped not in reference
    for name in RESOURCE_TYPED_PRESETS:
        assert "resource_type" in load_preset(name)["attributes"], name


def _rule_asset_types(payload: dict[str, Any], rule: dict[str, Any]) -> set[str]:
    """Catalog asset types a binding rule can emit."""
    expr = payload["fields"]["asset_type"]
    if "const" in expr:
        return {expr["const"]}
    # a translated vendor type: the rule must condition on the same column and bind only mapped types
    column = expr["coalesce"][0]["column"]
    [condition] = [item for item in rule["when"] if item["column"] == column]
    assert condition["op"] == "in", rule["name"]
    assert set(condition["value"]) <= set(expr["map"]), rule["name"]
    return {expr["map"][value] for value in condition["value"]}


def test_preset_rules_bind_catalog_safeguards_that_apply_to_the_asset_type() -> None:
    safeguards = _safeguards()
    known = _catalog_control_ids()
    bound = 0
    for name in EXPECTED_PRESETS:
        payload = load_preset(name)
        for rule in payload.get("rules", []):
            for safeguard_id in rule.get("safeguard_ids", []):
                bound += 1
                # a type the safeguard does not list would be an invalid binding in the assessment
                emitted = _rule_asset_types(payload, rule)
                assert emitted <= set(safeguards[safeguard_id]["asset_types"]), (name, safeguard_id, emitted)
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
    assert bound == 6


@pytest.mark.parametrize(
    ("name", "safeguard_id"),
    [
        ("ocsf/account_change", "SG-IDENTITY-002"),
        ("ocsf/group_management", "SG-IDENTITY-002"),
        ("ocsf/vulnerability_finding", VULN_SG),
        ("ocsf/compliance_finding", BASELINE_SG),
    ],
)
def test_bound_rows_carry_only_tags_in_the_bound_safeguards_crosswalk(name: str, safeguard_id: str) -> None:
    payload = load_preset(name)
    crosswalk = {member["control_id"] for member in _safeguards()[safeguard_id]["satisfies"]}
    [rule] = [item for item in payload["rules"] if item.get("safeguard_ids")]
    assert rule["safeguard_ids"] == [safeguard_id]
    # a rule without its own tags keeps the preset's, so those must fit the crosswalk too
    tags = rule.get("controls", payload["fields"]["controls"]["const"])
    assert tags
    assert set(tags) <= crosswalk, set(tags) - crosswalk


def test_disabling_rules_restores_presence_only_mapping() -> None:
    rows = read_fixture_table(FIXTURES, IDENTITY_TABLE)
    spec = resolve_mapping_ref({"preset": "ocsf/authentication", "source": {"table": IDENTITY_TABLE}, "rules": []})
    events = map_rows(spec, rows, collected_at=COLLECTED).events
    assert {event["status"] for event in events} == {"observed"}
    assert not any("safeguard_ids" in event for event in events)


def _fresh_fixture(target: Path, table: str) -> Path:
    """Copy a fixture table with current timestamps so freshness does not decide the verdict."""
    target.mkdir()
    rows = read_fixture_table(FIXTURES, table)
    base = datetime.now(UTC) - timedelta(hours=2)
    for offset, row in enumerate(rows):
        observed = base + timedelta(minutes=offset)
        row["time_dt"] = observed.strftime("%Y-%m-%dT%H:%M:%SZ")
        if "time" in row:
            row["time"] = int(observed.timestamp() * 1000)
    (target / f"{table}.json").write_text(json.dumps(rows), encoding="utf-8")
    return target


def _assess(tmp_path: Path, table: str, presets: list[str], expected_rows: int) -> dict[str, Any]:
    """Sync presets over a fixture table through the Databricks reader, then run the pipeline."""
    lake = tmp_path / "lake"
    append_config_event(
        lake,
        connector_id="databricks-evidence-lake",
        state="enabled",
        actor="t",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={"mappings": [{"preset": name, "source": {"table": table}} for name in presets]},
    )
    synced = run_connector_sync(
        lake,
        connector_id="databricks-evidence-lake",
        fixture_dir=_fresh_fixture(tmp_path / "fixtures", table),
        materialize=False,
    )
    assert synced.evidence_count == expected_rows
    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="ocsf-test")
    return read_json(out / "gold" / "ccf_assessment.json")


def test_ocsf_rows_reach_the_ccf_assessment_through_sync_and_pipeline(tmp_path: Path) -> None:
    presets = ["ocsf/authentication", "ocsf/account_change", "ocsf/group_management"]
    assessment = _assess(tmp_path, IDENTITY_TABLE, presets, expected_rows=13)

    by_asset = {
        (row["safeguard_id"], row["asset_id"]): row
        for row in assessment["asset_results"]
        if row["safeguard_id"] in {"SG-IDENTITY-001", "SG-IDENTITY-002"}
    }
    assert {key: row["status"] for key, row in by_asset.items()} == {
        ("SG-IDENTITY-001", "user-alice"): "pass",
        ("SG-IDENTITY-001", "user-bob"): "fail",
        ("SG-IDENTITY-002", "user-build-bot"): "not_evaluated",
        ("SG-IDENTITY-002", "group-admins"): "not_evaluated",
        ("SG-IDENTITY-002", "group-readers"): "not_evaluated",
    }
    for key in [("SG-IDENTITY-002", "user-build-bot"), ("SG-IDENTITY-002", "group-admins")]:
        assert any("unknown or unevaluated" in reason for reason in by_asset[key]["reasons"])

    safeguards = {row["safeguard_id"]: row for row in assessment["safeguards"]}
    identity = safeguards["SG-IDENTITY-001"]
    assert identity["status"] == "fail"
    # carol, dave, erin, frank, build-bot, and the three groups were observed without MFA
    # evidence: never silently passed
    assert (identity["assessed_asset_count"], identity["unassessed_asset_count"]) == (2, 8)
    assert identity["invalid_binding_count"] == 0
    review = safeguards["SG-IDENTITY-002"]
    assert review["status"] == "not_evaluated"
    assert review["invalid_binding_count"] == 0

    # framework requirements come from the reviewed crosswalk, not from the preset's tags
    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    assert requirements["SOC2-CC6.1"]["status"] == "not_evaluated"
    assert requirements["SOC2-CC6.1"]["reviewed_safeguard_ids"] == []
    # a provider benchmark ignores evidence from other sources, even on a shared safeguard
    assert requirements["CIS-AWS-1.10"]["status"] == "not_evaluated"
    # a proposed mapping is never attested, even when the safeguard has evidence
    iso = requirements["ISO27001-A.8.5"]
    assert "SG-IDENTITY-001" not in iso["reviewed_safeguard_ids"]
    assert iso["pending_mapping_count"] >= 1
    assert iso["status"] != "pass"
    assert requirements["SOC2-CC6.2"]["status"] == "not_evaluated"


def test_ocsf_findings_reach_the_ccf_assessment_without_ambiguous_assets(tmp_path: Path) -> None:
    presets = [
        "ocsf/vulnerability_finding",
        "ocsf/compliance_finding",
        "ocsf/detection_finding",
        "ocsf/api_activity",
    ]
    assessment = _assess(tmp_path, FINDING_TABLE, presets, expected_rows=12)
    # the EC2 instance appears in Inspector, Security Hub, GuardDuty, and CloudTrail rows
    # under one catalog type; two types would make every binding on it invalid
    assert assessment["ambiguous_asset_count"] == 0

    by_asset = {
        (row["safeguard_id"], row["asset_id"]): row["status"]
        for row in assessment["asset_results"]
        if row["safeguard_id"] in {VULN_SG, BASELINE_SG}
    }
    assert by_asset == {
        (VULN_SG, EC2_A): "fail",
        (VULN_SG, IMAGE): "pass",
        (VULN_SG, EC2_B): "not_evaluated",  # only a suppressed finding
        (BASELINE_SG, EC2_A): "fail",
        (BASELINE_SG, EC2_B): "not_evaluated",  # only a Warning check
        (BASELINE_SG, EC2_C): "pass",
    }

    safeguards = {row["safeguard_id"]: row for row in assessment["safeguards"]}
    vulnerability, baseline = safeguards[VULN_SG], safeguards[BASELINE_SG]
    assert (vulnerability["status"], vulnerability["invalid_binding_count"]) == ("fail", 0)
    assert (baseline["status"], baseline["invalid_binding_count"]) == ("fail", 0)
    # a third instance and the S3 bucket are observed and in the vulnerability safeguard's
    # scope, but no vulnerability evidence covers them: unassessed, not passed
    assert (vulnerability["assessed_asset_count"], vulnerability["unassessed_asset_count"]) == (3, 2)
    assert (baseline["assessed_asset_count"], baseline["unassessed_asset_count"]) == (3, 0)

    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    assert VULN_SG not in requirements["SOC2-CC7.1"]["reviewed_safeguard_ids"]
    assert requirements["SOC2-CC7.1"]["status"] == "not_evaluated"
    assert requirements["NIST-CSF-PR.PS-01"]["reviewed_safeguard_ids"] == [BASELINE_SG]
    assert requirements["NIST-CSF-PR.PS-01"]["status"] == "fail"
    # the baseline safeguard's mapping to CM-6 is only proposed, so it is never attested
    cm6 = requirements["NIST-800-53-CM-6"]
    assert BASELINE_SG not in cm6["reviewed_safeguard_ids"]
    assert cm6["pending_mapping_count"] >= 1
    assert cm6["status"] != "pass"


def test_ocsf_accounts_keep_colliding_users_and_event_ids_separate_through_ccf(tmp_path: Path) -> None:
    from copy import deepcopy

    original = read_fixture_table(FIXTURES, IDENTITY_TABLE)[0]
    original["time_dt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for account, mfa in (("scope-a", True), ("scope-b", False)):
        row = deepcopy(original)
        row["cloud"]["account"]["uid"] = account
        row["is_mfa"] = mfa
        rows.append(row)
    lake = tmp_path / "lake"
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / f"{IDENTITY_TABLE}.json").write_text(json.dumps(rows))
    append_config_event(
        lake,
        connector_id="databricks-evidence-lake",
        state="enabled",
        actor="t",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={"mapping": {"preset": "ocsf/authentication", "source": {"table": IDENTITY_TABLE}}},
    )
    from security_lakehouse.io import read_jsonl

    for _ in range(2):
        synced = run_connector_sync(
            lake, connector_id="databricks-evidence-lake", fixture_dir=fixtures, materialize=False
        )
        assert synced.evidence_count == 2
        raw = read_jsonl(lake / CONNECTOR_RAW_FILE)
        assert len(raw) == len({event["event_id"] for event in raw}) == 2
        assert {event["tenant_id"] for event in raw} == {"scope-a", "scope-b"}
    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="platform-tenant")
    assessment = read_json(out / "gold/ccf_assessment.json")
    results = {
        r["source_tenant_id"]: r["status"]
        for r in assessment["asset_results"]
        if r["safeguard_id"] == "SG-IDENTITY-001"
    }
    assert results == {"scope-a": "pass", "scope-b": "fail"}


@pytest.mark.parametrize(
    "preset,table,subject",
    [
        ("ocsf/authentication", IDENTITY_TABLE, "user"),
        ("ocsf/account_change", IDENTITY_TABLE, "user"),
        ("ocsf/group_management", IDENTITY_TABLE, "group"),
        ("ocsf/vulnerability_finding", FINDING_TABLE, "resource"),
        ("ocsf/compliance_finding", FINDING_TABLE, "resource"),
    ],
)
def test_ocsf_cannot_substitute_an_account_for_a_missing_assessed_subject(preset, table, subject):
    from copy import deepcopy

    spec = _preset(preset)
    row = deepcopy(next(r for r in read_fixture_table(FIXTURES, table) if r["class_uid"] == EXPECTED_PRESETS[preset]))
    row[subject] = {}
    result = map_rows(spec, [row])
    assert result.events == []
    assert result.errors and result.errors[0]["error"] == "fields.asset_id: no value"


@pytest.mark.parametrize("missing", ["user", "cloud"])
def test_partial_ocsf_mapping_blocks_pass_and_records_a_safe_gap(tmp_path: Path, missing: str) -> None:
    from copy import deepcopy

    from security_lakehouse.ingestion.watermark import read_watermark
    from security_lakehouse.io import read_jsonl

    row = deepcopy(read_fixture_table(FIXTURES, IDENTITY_TABLE)[0])
    row["time_dt"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    bad = deepcopy(row)
    bad[missing] = {}
    bad["metadata"]["uid"] = "private-unmappable-row"
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / f"{IDENTITY_TABLE}.json").write_text(json.dumps([row, bad]))
    lake = tmp_path / "lake"
    append_config_event(
        lake,
        connector_id="databricks-evidence-lake",
        state="enabled",
        actor="t",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={"mapping": {"preset": "ocsf/authentication", "source": {"table": IDENTITY_TABLE}}},
    )
    for _ in range(2):
        sync = run_connector_sync(
            lake, connector_id="databricks-evidence-lake", fixture_dir=fixture_dir, materialize=False
        )
        assert sync.run["metadata"]["partial"] is True
        raw = read_jsonl(lake / CONNECTOR_RAW_FILE)
        assert len(raw) == 2
        assert validate_raw_events(raw) == []
        [gap] = [event for event in raw if event["attributes"].get("collection_gap")]
        assert gap["status"] == "not_evaluated"
        assert gap["entity"]["asset_type"] == "collection_scope"
        assert not gap.get("safeguard_ids") and not gap["controls"]
        assert gap["attributes"]["unmapped_rows"] == 1
        [valid] = [event for event in raw if not event["attributes"].get("collection_gap")]
        assert valid["status"] == "not_evaluated"
        assert valid["attributes"]["mapping_original_status"] == "pass"
        assert "private-unmappable-row" not in json.dumps(raw)
        assert read_watermark(lake, "databricks-evidence-lake") == valid["event_time"]
    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="platform-tenant")
    assessment = read_json(out / "gold/ccf_assessment.json")
    assert not any(item["status"] == "pass" for item in assessment["requirements"])
    identity = [item for item in assessment["asset_results"] if item["safeguard_id"] == "SG-IDENTITY-001"]
    assert identity and all(item["status"] == "not_evaluated" for item in identity)
    assert all(item["asset_id"] == "user-alice" for item in identity)


@pytest.mark.parametrize("preset", EXPECTED_PRESETS)
def test_every_ocsf_preset_requires_an_explicit_source_scope(preset: str) -> None:
    spec = _preset(preset)
    expected = "cloud.account_uid" if preset == "ocsf/security_finding" else "cloud.account.uid"
    assert spec.fields["source_account_id"].column == expected
    assert "cloud" in spec.top_level_columns()


DISCOVERY_TABLE = "ocsf_discovery_data_incidents"
OBSERVATION_PRESETS = [
    "ocsf/config_state",
    "ocsf/device_inventory",
    "ocsf/data_security_finding",
    "ocsf/incident_finding",
]
OCSF_SOURCE_REVISION = "78bf68a24b38c0d6441ddd13b9028c1b1eb53f07"


@pytest.mark.parametrize("preset", OBSERVATION_PRESETS)
def test_discovery_and_incident_states_remain_source_observations(preset: str) -> None:
    result = map_rows(_preset(preset), read_fixture_table(FIXTURES, DISCOVERY_TABLE), collected_at=COLLECTED)
    assert result.errors == []
    assert len(result.events) == 2
    assert validate_raw_events(result.events) == []
    assert {event["status"] for event in result.events} == {"observed"}
    for event in result.events:
        assert not event.get("safeguard_ids")
        assert event["tenant_id"] == "synthetic-scope-a"
        attrs = event["attributes"]
        assert attrs["ocsf_version"] == "1.5.0"
        assert attrs["ocsf_schema_release"] == "1.5.0"
        assert attrs["ocsf_schema_revision"] == OCSF_SOURCE_REVISION
        assert attrs["product_version"] == "test-1"
        assert len(attrs["raw_sha256"]) == 64
        assert attrs["source_id"] in {f"{preset.split('/')[1]}-1", f"{preset.split('/')[1]}-5"}
        if preset == "ocsf/data_security_finding":
            assert len(attrs["resources"]) == 2
            assert event["entity"]["asset_id"] == "synthetic-data-finding"
            assert event["entity"]["asset_type"] == "lake_record"
        if preset == "ocsf/incident_finding":
            assert len(attrs["finding_info_list"]) == 2
            assert event["entity"]["asset_type"] == "lake_record"


@pytest.mark.parametrize("preset", OBSERVATION_PRESETS)
@pytest.mark.parametrize("missing", ["cloud", "metadata", "time"])
def test_new_ocsf_presets_reject_missing_identity_scope_or_time(preset: str, missing: str) -> None:
    row = next(r for r in read_fixture_table(FIXTURES, DISCOVERY_TABLE) if r["class_uid"] == EXPECTED_PRESETS[preset])
    row.pop(missing)
    result = map_rows(_preset(preset), [row])
    assert not result.events
    assert len(result.errors) == 1


def test_new_ocsf_presets_replay_and_preserve_accounts_without_attestation(tmp_path: Path) -> None:
    from copy import deepcopy

    from security_lakehouse.io import read_jsonl

    fixture_dir = _fresh_fixture(tmp_path / "fixtures", DISCOVERY_TABLE)
    rows = read_fixture_table(fixture_dir, DISCOVERY_TABLE)
    other = deepcopy(rows)
    for row in other:
        row["cloud"]["account"]["uid"] = "synthetic-scope-b"
    (fixture_dir / f"{DISCOVERY_TABLE}.json").write_text(json.dumps(rows + other))
    lake = tmp_path / "lake"
    append_config_event(
        lake,
        connector_id="databricks-evidence-lake",
        state="enabled",
        actor="t",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={"mappings": [{"preset": p, "source": {"table": DISCOVERY_TABLE}} for p in OBSERVATION_PRESETS]},
    )
    for _ in range(2):
        sync = run_connector_sync(
            lake, connector_id="databricks-evidence-lake", fixture_dir=fixture_dir, materialize=False
        )
        assert sync.evidence_count == 16
        raw = read_jsonl(lake / CONNECTOR_RAW_FILE)
        assert len(raw) == len({r["event_id"] for r in raw}) == 16
        assert {r["tenant_id"] for r in raw} == {"synthetic-scope-a", "synthetic-scope-b"}
        assert {r["status"] for r in raw} == {"observed"}
    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="platform-tenant")
    assessment = read_json(out / "gold/ccf_assessment.json")
    assert assessment["ambiguous_asset_count"] == 0
    assert all(r["invalid_binding_count"] == 0 for r in assessment["safeguards"])
    assert not any(r["status"] == "pass" for r in assessment["requirements"])
    assert assessment["asset_results"] == []
    silver = read_jsonl(out / "silver/normalized_events.jsonl")
    assert {r["tenant_id"] for r in silver} == {"synthetic-scope-a", "synthetic-scope-b"}
    assert len(silver) == 16


@pytest.mark.parametrize("preset", OBSERVATION_PRESETS)
def test_new_ocsf_partial_reads_keep_the_gap_and_block_attestation(tmp_path: Path, preset: str) -> None:
    from copy import deepcopy

    from security_lakehouse.io import read_jsonl

    fixture_dir = _fresh_fixture(tmp_path / "fixtures", DISCOVERY_TABLE)
    row = next(
        r for r in read_fixture_table(fixture_dir, DISCOVERY_TABLE) if r["class_uid"] == EXPECTED_PRESETS[preset]
    )
    bad = deepcopy(row)
    bad["cloud"] = {}
    (fixture_dir / f"{DISCOVERY_TABLE}.json").write_text(json.dumps([row, bad]))
    lake = tmp_path / "lake"
    append_config_event(
        lake,
        connector_id="databricks-evidence-lake",
        state="enabled",
        actor="t",
        credentials={"host": "dbc-a1b2345c-d6e7.cloud.databricks.com"},
        options={"mapping": {"preset": preset, "source": {"table": DISCOVERY_TABLE}}},
    )
    sync = run_connector_sync(lake, connector_id="databricks-evidence-lake", fixture_dir=fixture_dir, materialize=False)
    assert sync.run["metadata"]["partial"] is True
    raw = read_jsonl(lake / CONNECTOR_RAW_FILE)
    [gap] = [r for r in raw if r["attributes"].get("collection_gap")]
    assert gap["status"] == "not_evaluated"
    assert gap["attributes"]["unmapped_rows"] == 1
    assert len(raw) == 2
    out = tmp_path / "out"
    run_pipeline(lake / CONNECTOR_RAW_FILE, out, tenant_id="platform-tenant")
    assessment = read_json(out / "gold/ccf_assessment.json")
    assert not any(r["status"] == "pass" for r in assessment["requirements"])


@pytest.mark.parametrize(
    "preset,subject",
    [
        ("ocsf/config_state", "device"),
        ("ocsf/device_inventory", "device"),
        ("ocsf/data_security_finding", "finding_info"),
    ],
)
def test_new_ocsf_presets_cannot_replace_missing_subject_with_account(preset: str, subject: str) -> None:
    row = next(r for r in read_fixture_table(FIXTURES, DISCOVERY_TABLE) if r["class_uid"] == EXPECTED_PRESETS[preset])
    row[subject] = {}
    result = map_rows(_preset(preset), [row])
    assert result.events == []
    assert result.errors == [{"row": 1, "error": "fields.asset_id: no value"}]


@pytest.mark.parametrize("preset", OBSERVATION_PRESETS)
@pytest.mark.parametrize("state", [None, 0, 3, 4, 5, 99])
def test_missing_unknown_or_closed_source_status_is_not_a_control_verdict(preset: str, state: int | None) -> None:
    row = next(r for r in read_fixture_table(FIXTURES, DISCOVERY_TABLE) if r["class_uid"] == EXPECTED_PRESETS[preset])
    if state is None:
        row.pop("status_id")
    else:
        row["status_id"] = state
    [event] = map_rows(_preset(preset), [row]).events
    assert event["status"] == "observed"
    assert event["attributes"]["source_status_id"] == state
    assert not event.get("safeguard_ids")
