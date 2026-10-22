"""Opt-in role policy observations retain scope and uncertainty."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from security_lakehouse.connector_errors import collection_gaps
from security_lakehouse.connectors_aws import AWSClient, AWSFixtureClient, collect_aws_evidence
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures/aws"
ACCOUNT = "123456789012"
ROLE = {"RoleName": "reader", "RoleId": "AROAEXAMPLE", "Arn": f"arn:aws:iam::{ACCOUNT}:role/team/reader"}
POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::example/*"},
        {
            "Effect": "Deny",
            "NotAction": "s3:GetObject",
            "NotResource": "arn:aws:s3:::example/*",
            "Condition": {"Bool": {"aws:SecureTransport": False}, "NumericLessThan": {"s3:TlsVersion": 1.2}},
        },
    ],
}


class Client(AWSFixtureClient):
    def roles(self):
        return [ROLE]

    def role_policies(self, role_name):
        assert role_name == "reader"
        return [{"policy_type": "inline", "policy_id": "read", "document": POLICY}]


def collect(client=None, **kwargs):
    return collect_aws_evidence(
        client or Client(FIXTURE),
        account_id=ACCOUNT,
        collected_at=datetime(2026, 10, 21, tzinfo=UTC),
        include_role_policies=True,
        **kwargs,
    )


def roles(rows):
    return [row for row in rows if row["event_type"] == "aws.iam.role_policies"]


def test_opt_in_role_policy_evidence_preserves_semantics_and_replay():
    rows = collect(tenant_id="tenant-a")
    assert validate_raw_events(rows) == []
    row = roles(rows)[0]
    assert row == roles(collect(tenant_id="tenant-a"))[0]
    assert row["entity"]["asset_id"] == ROLE["Arn"]
    assert row["tenant_id"] == "tenant-a"
    assert row["controls"] == [] and row["status"] == "observed"
    attrs = row["attributes"]
    assert attrs["policy_coverage"] == "complete"
    assert attrs["authorization_coverage"] == "not_evaluated"
    assert attrs["usage_coverage"] == "not_collected"
    deny = attrs["policies"][0]["statements"][1]
    assert deny["effect"] == "Deny"
    assert deny["not_actions"] == ["s3:GetObject"]
    assert deny["not_resources"] == ["arn:aws:s3:::example/*"]
    assert deny["conditions"] == [
        ["Bool", "aws:SecureTransport", ["false"]],
        ["NumericLessThan", "s3:TlsVersion", ["1.2"]],
    ]


def test_default_does_not_read_roles():
    client = AWSFixtureClient(FIXTURE)
    client.roles = lambda: pytest.fail("optional call without opt-in")
    assert len(collect_aws_evidence(client, account_id=ACCOUNT)) == 7


@pytest.mark.parametrize(
    "payload", [None, {}, [None], [{}], [{**ROLE, "Arn": "arn:aws:iam::999999999999:role/reader"}], [ROLE, ROLE]]
)
def test_bad_role_inventory_is_a_safe_gap(payload):
    client = Client(FIXTURE)
    client.roles = lambda: payload
    rows = collect(client)
    assert not roles(rows)
    assert collection_gaps(rows)
    assert len([r for r in rows if r["event_type"] == "aws.iam.password_policy"]) == 1


def test_policy_read_failure_retains_role_with_unknown_coverage():
    client = Client(FIXTURE)

    def denied(_):
        raise RuntimeError("private-provider-token")

    client.role_policies = denied
    rows = collect(client)
    assert roles(rows)[0]["attributes"]["policy_coverage"] == "unavailable"
    assert collection_gaps(rows)
    assert "private-provider-token" not in json.dumps(rows)


def test_successful_empty_policy_lists_are_complete():
    client = Client(FIXTURE)
    client.role_policies = lambda _: []
    rows = collect(client)
    assert roles(rows)[0]["attributes"]["policy_coverage"] == "complete"
    assert not collection_gaps(rows)


@pytest.mark.parametrize(
    "statement",
    [
        {"Effect": "Allow", "Action": ["s3:GetObject", 7], "Resource": "*"},
        {"Effect": "Allow", "Action": "s3:GetObject"},
        {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*", "Condition": {"Bool": {"x": [True, None]}}},
    ],
)
def test_malformed_statement_is_not_complete(statement):
    client = Client(FIXTURE)
    client.role_policies = lambda _: [
        {"policy_type": "inline", "policy_id": "bad", "document": {"Statement": [POLICY["Statement"][0], statement]}}
    ]
    rows = collect(client)
    assert roles(rows)[0]["attributes"]["policy_coverage"] == "partial"
    assert collection_gaps(rows)


def sdk(**calls):
    client = object.__new__(AWSClient)
    client._iam = SimpleNamespace(**calls)
    return client


def test_live_client_paginates_and_reads_managed_and_inline_documents():
    calls = []

    def list_roles(**kwargs):
        calls.append(kwargs)
        return {"Roles": [] if kwargs else [ROLE], "IsTruncated": not bool(kwargs), "Marker": "cursor"}

    client = sdk(
        list_roles=list_roles,
        list_attached_role_policies=lambda **_: {
            "AttachedPolicies": [{"PolicyArn": f"arn:aws:iam::{ACCOUNT}:policy/read"}]
        },
        get_policy=lambda **_: {"Policy": {"DefaultVersionId": "v2"}},
        get_policy_version=lambda **_: {"PolicyVersion": {"Document": POLICY}},
        list_role_policies=lambda **_: {"PolicyNames": ["inline"]},
        get_role_policy=lambda **_: {"PolicyDocument": POLICY},
    )
    assert client.roles() == [ROLE]
    assert calls == [{}, {"Marker": "cursor"}]
    result = client.role_policies("reader")
    assert {p["policy_type"] for p in result} == {"managed", "inline"}
    assert all(p["document"] == POLICY for p in result)


def test_repeated_marker_fails_without_exposing_cursor():
    from security_lakehouse.connector_errors import CollectionGapError

    client = sdk(list_roles=lambda **_: {"Roles": [ROLE], "IsTruncated": True, "Marker": "private-cursor"})
    with pytest.raises(CollectionGapError) as exc:
        client.roles()
    assert "private-cursor" not in str(exc.value)


@pytest.mark.parametrize("option", [True, "true"])
def test_runner_option_persists_scoped_replayable_evidence(tmp_path, option):
    from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
    from security_lakehouse.connector_state import append_config_event
    from security_lakehouse.io import read_jsonl
    from security_lakehouse.verification import verify_event

    append_config_event(
        tmp_path,
        connector_id="aws-posture",
        state="enabled",
        actor="test",
        credentials={"account_id": ACCOUNT},
        options={"include_role_policies": option},
    )
    first = run_connector_sync(tmp_path, connector_id="aws-posture", fixture_dir=FIXTURE)
    assert first.evidence_count == 9
    second = run_connector_sync(tmp_path, connector_id="aws-posture", fixture_dir=FIXTURE)
    assert second.evidence_count == 9
    assert len(read_jsonl(tmp_path / CONNECTOR_RAW_FILE)) == 9
    stored = [
        r for r in read_jsonl(tmp_path / "silver/normalized_events.jsonl") if r["event_type"] == "aws.iam.role_policies"
    ]
    assert len(stored) == 2
    assert {r["asset_owner"] for r in stored} == {ACCOUNT}
    assert all(verify_event(tmp_path, r["event_id"])["verified"] for r in stored)


@pytest.mark.parametrize("option", ["yes", 1, None, {}])
def test_runner_rejects_ambiguous_boolean(option):
    from security_lakehouse.connector_errors import ConnectorConfigError
    from security_lakehouse.connector_runner import _collect_aws

    with pytest.raises(ConnectorConfigError, match="include_role_policies must be true or false"):
        _collect_aws(fixture_dir=FIXTURE, env={}, options={"include_role_policies": option})


def test_permission_denial_names_read_and_omits_provider_exception():
    from security_lakehouse.connector_errors import CollectionGapError

    class Denied(Exception):
        response = {"Error": {"Code": "AccessDenied", "Message": "private-provider-token"}}

    def denied(**_):
        raise Denied("private-provider-token")

    client = sdk(list_roles=denied)
    with pytest.raises(CollectionGapError) as exc:
        client.roles()
    assert exc.value.reason == "permission_denied"
    assert exc.value.permission == "iam:ListRoles"
    assert "private-provider-token" not in str(exc.value)


@pytest.mark.parametrize(
    "response", [{}, {"Roles": None}, {"Roles": [], "IsTruncated": "false"}, {"Roles": [], "IsTruncated": True}]
)
def test_bad_pagination_is_not_empty_success(response):
    from security_lakehouse.connector_errors import CollectionGapError

    with pytest.raises(CollectionGapError):
        sdk(list_roles=lambda **_: response).roles()


def test_role_identity_is_different_in_another_account():
    first = roles(collect())[0]
    other = "999999999999"
    client = Client(FIXTURE)
    client.roles = lambda: [{**ROLE, "Arn": ROLE["Arn"].replace(ACCOUNT, other)}]
    second = roles(collect_aws_evidence(client, account_id=other, include_role_policies=True))[0]
    assert first["event_id"] != second["event_id"]
    assert first["entity"]["asset_id"] != second["entity"]["asset_id"]


def test_optional_permissions_are_off_by_default_and_read_only():
    import yaml

    from security_lakehouse.aws_role_policies import PERMISSIONS

    root = Path(__file__).parents[1]
    template = yaml.safe_load((root / "deploy/aws/grc-lake-posture-readonly-role.yaml").read_text())
    assert template["Parameters"]["IncludeRolePolicies"]["Default"] == "false"
    resource = template["Resources"]["GrcLakeRolePolicyReadOnly"]
    assert resource["Condition"] == "CollectRolePolicies"
    statements = resource["Properties"]["PolicyDocument"]["Statement"]
    assert statements[0]["Effect"] == "Allow"
    assert set(statements[0]["Action"]) == set(PERMISSIONS.values())
    terraform = (root / "deploy/aws/grc-lake-posture-readonly-role.tf").read_text()
    assert "count = var.include_role_policies ? 1 : 0" in terraform
    assert "default     = false" in terraform
    assert all(f'"{action}"' in terraform for action in PERMISSIONS.values())


def test_fixture_role_metadata_is_allowlisted():
    rows = collect(AWSFixtureClient(FIXTURE))
    assert len(roles(rows)) == 2
    assert "excluded-fixture-sentinel" not in json.dumps(rows)
