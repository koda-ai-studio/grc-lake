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
        row["time_dt"] = (base + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    assert requirements["SOC2-CC6.1"]["status"] == "fail"
    assert requirements["SOC2-CC6.1"]["reviewed_safeguard_ids"] == ["SG-IDENTITY-001"]
    assert requirements["CIS-AWS-1.10"]["status"] == "fail"  # tagged nowhere in the preset
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
    assert VULN_SG in requirements["SOC2-CC7.1"]["reviewed_safeguard_ids"]
    assert requirements["SOC2-CC7.1"]["status"] == "fail"
    assert requirements["NIST-CSF-PR.PS-01"]["reviewed_safeguard_ids"] == [BASELINE_SG]
    assert requirements["NIST-CSF-PR.PS-01"]["status"] == "fail"
    # the baseline safeguard's mapping to CM-6 is only proposed, so it is never attested
    cm6 = requirements["NIST-800-53-CM-6"]
    assert BASELINE_SG not in cm6["reviewed_safeguard_ids"]
    assert cm6["pending_mapping_count"] >= 1
    assert cm6["status"] != "pass"
