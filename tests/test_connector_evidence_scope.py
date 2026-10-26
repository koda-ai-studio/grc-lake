"""Provider exclusions and unknown fields cannot inflate passing coverage."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from security_lakehouse import connectors_aws as aws
from security_lakehouse import connectors_gcp as gcp
from security_lakehouse import connectors_google_workspace as workspace
from security_lakehouse import connectors_okta as okta

NOW = datetime(2026, 10, 6, tzinfo=UTC)


@pytest.mark.parametrize("lifecycle", ["SUSPENDED", "DEPROVISIONED", "STAGED", "LOCKED_OUT"])
def test_okta_inactive_mfa_population_is_observed_not_passed(lifecycle):
    result = okta._mfa_event("https://fixture.okta.com", "fixture", "user", {"status": lifecycle}, [], NOW, "tenant")
    assert result["status"] == "observed"
    assert result["attributes"]["mfa_applicable"] is False


@pytest.mark.parametrize("lifecycle", [None, "UNKNOWN", "new-provider-state"])
def test_unknown_okta_lifecycle_cannot_pass_even_with_enrolled_factors(lifecycle):
    result = okta._mfa_event(
        "https://fixture.okta.com",
        "fixture",
        "user",
        {"status": lifecycle},
        [{"status": "ACTIVE", "factorType": "webauthn"}],
        NOW,
        "tenant",
    )
    assert result["status"] == "not_evaluated"


@pytest.mark.parametrize("field", ["suspended", "archived"])
def test_workspace_inactive_mfa_population_is_observed(field):
    result = workspace._mfa_event("customer", "fixture", "user", {field: True, "isEnrolledIn2Sv": False}, NOW, "tenant")
    assert result["status"] == "observed"


@pytest.mark.parametrize("enrolled", [None, "false", "true"])
def test_workspace_missing_or_untyped_enrollment_is_unknown(enrolled):
    result = workspace._mfa_event(
        "customer",
        "fixture",
        "user",
        {"suspended": False, "archived": False, "isEnrolledIn2Sv": enrolled},
        NOW,
        "tenant",
    )
    assert result["status"] == "not_evaluated"


def test_aws_key_only_user_does_not_establish_mfa_pass():
    result = aws._mfa_event("123456789012", "service", {}, [], NOW, "tenant", console_access=False)
    assert result["status"] == "observed"
    assert result["attributes"]["mfa_not_applicable"] is True


@pytest.mark.parametrize(
    "name",
    [
        "iam.disableServiceAccountKeyCreation",
        "constraints/iam.disableServiceAccountKeyCreation",
        "projects/project/policies/iam.disableServiceAccountKeyCreation",
    ],
)
def test_gcp_policy_resource_names_match_the_expected_constraint(name):
    result = gcp._policy_event("project", {"constraint": name, "enforced": False}, NOW, "tenant")
    assert result["status"] == "open"
    assert result["attributes"]["constraint"] == "constraints/iam.disableServiceAccountKeyCreation"


def test_unrelated_gcp_constraint_cannot_establish_an_access_control_pass():
    result = gcp._policy_event(
        "project", {"constraint": "compute.disableSerialPortAccess", "enforced": True}, NOW, "tenant"
    )
    assert result["status"] == "observed"


@pytest.mark.parametrize("enforced", [None, "false", "true"])
def test_unknown_gcp_enforcement_remains_unknown(enforced):
    result = gcp._policy_event(
        "project", {"constraint": "constraints/compute.requireOsLogin", "enforced": enforced}, NOW, "tenant"
    )
    assert result["status"] == "not_evaluated"


def test_conditional_gcp_rules_do_not_establish_unconditional_enforcement():
    client = gcp.GCPClient.__new__(gcp.GCPClient)
    client.project_id = "project"
    policy = SimpleNamespace(
        name="projects/project/policies/compute.requireOsLogin",
        spec=SimpleNamespace(
            rules=[
                SimpleNamespace(enforce=False, condition=None),
                SimpleNamespace(enforce=True, condition=SimpleNamespace(expression="resource.matchTag('tag', 'yes')")),
            ]
        ),
    )
    client._org_policies = SimpleNamespace(list_policies=lambda **kwargs: [policy])
    collected = client.org_policies()[0]
    result = gcp._policy_event("project", collected, NOW, "tenant")
    assert result["status"] == "not_evaluated"


@pytest.mark.parametrize("enforce,expected", [(True, "pass"), (False, "open")])
def test_real_gcp_sdk_boolean_rule_retains_explicit_enforcement(enforce, expected):
    sdk = pytest.importorskip("google.cloud.orgpolicy_v2")
    client = gcp.GCPClient.__new__(gcp.GCPClient)
    client.project_id = "project"
    policy = sdk.Policy(
        name="projects/project/policies/compute.requireOsLogin",
        spec=sdk.PolicySpec(rules=[sdk.PolicySpec.PolicyRule(enforce=enforce)]),
    )
    client._org_policies = SimpleNamespace(list_policies=lambda **kwargs: [policy])
    collected = client.org_policies()[0]
    assert collected["enforced"] is enforce
    assert gcp._policy_event("project", collected, NOW, "tenant")["status"] == expected


def _effective_client(response):
    calls = []

    def get_effective_policy(**kwargs):
        calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    client = gcp.GCPClient.__new__(gcp.GCPClient)
    client.project_id = "project"
    client._org_policies = SimpleNamespace(get_effective_policy=get_effective_policy)
    return client, calls


@pytest.mark.parametrize("enforce,expected", [(True, "pass"), (False, "open")])
def test_real_gcp_sdk_effective_policy_establishes_inherited_enforcement(enforce, expected):
    sdk = pytest.importorskip("google.cloud.orgpolicy_v2")
    policy = sdk.Policy(
        name="projects/123/policies/compute.requireOsLogin",
        spec=sdk.PolicySpec(rules=[sdk.PolicySpec.PolicyRule(enforce=enforce)]),
    )
    client, calls = _effective_client(policy)
    collected = client.effective_org_policy("constraints/compute.requireOsLogin")
    assert calls == [{"name": "projects/project/policies/compute.requireOsLogin"}]
    assert collected["enforced"] is enforce
    row = gcp._policy_event("project", collected, NOW, "tenant", set_on_project=False, effective=True)
    assert row["status"] == expected
    assert row["safeguard_ids"] == ["SG-IDENTITY-001"]


def test_real_gcp_sdk_effective_policy_without_unconditional_enforcement_is_not_evaluated():
    sdk = pytest.importorskip("google.cloud.orgpolicy_v2")
    rule = sdk.PolicySpec.PolicyRule
    tagged = {"expression": "resource.matchTag('123/env', 'prod')"}
    specs = [
        sdk.PolicySpec(rules=[rule(enforce=False), rule(enforce=True, condition=tagged)]),
        sdk.PolicySpec(rules=[rule(values=rule.StringValues(allowed_values=["x"]))]),
        sdk.PolicySpec(rules=[]),
        sdk.PolicySpec(reset=True),
    ]
    for spec in specs:
        policy = sdk.Policy(name="projects/123/policies/compute.requireOsLogin", spec=spec)
        client, _calls = _effective_client(policy)
        collected = client.effective_org_policy("constraints/compute.requireOsLogin")
        assert collected["enforced"] is None
        row = gcp._policy_event("project", collected, NOW, "tenant", set_on_project=False, effective=True)
        assert row["status"] == "not_evaluated"


class _GoogleError(Exception):
    def __init__(self, message, *, code, reason=None, metadata=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.reason = reason
        self.metadata = metadata or {}


@pytest.mark.parametrize(
    "failure,reason,permission",
    [
        (_GoogleError("denied private-value", code=403), "permission_denied", "orgpolicy.policy.get"),
        (_GoogleError("not found private-value", code=404), "read_failed", None),
        (_GoogleError("backend private-value", code=500), "read_failed", None),
        (None, "read_failed", None),
        ("private-value", "read_failed", None),
    ],
    ids=["403", "404", "500", "empty-response", "malformed-response"],
)
def test_failed_effective_policy_read_is_a_named_gap_without_provider_text(failure, reason, permission):
    client, _calls = _effective_client(failure)
    with pytest.raises(gcp.CollectionGapError) as caught:
        client.effective_org_policy("constraints/iam.disableServiceAccountKeyCreation")
    gap = caught.value
    assert gap.collection == "effective_org_policies:iam.disableServiceAccountKeyCreation"
    assert gap.reason == reason
    assert gap.permission == permission
    assert "private-value" not in gap.message
    assert "/" not in gap.message
