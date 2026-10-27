"""Incomplete provider responses must not become smaller successful inventories."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from security_lakehouse import (
    connectors_bamboohr as bamboohr,
)
from security_lakehouse import (
    connectors_crowdstrike as crowdstrike,
)
from security_lakehouse import (
    connectors_google_workspace as workspace,
)
from security_lakehouse import (
    connectors_intune as intune,
)
from security_lakehouse import (
    connectors_jamf as jamf,
)
from security_lakehouse import (
    connectors_rippling as rippling,
)
from security_lakehouse import (
    connectors_runtime as runtime,
)
from security_lakehouse import (
    connectors_siem as siem,
)
from security_lakehouse import (
    connectors_snyk as snyk,
)
from security_lakehouse import (
    connectors_workday as workday,
)
from security_lakehouse.connectors_aws import AWSClient
from security_lakehouse.connectors_clickhouse import ClickHouseClient
from security_lakehouse.connectors_jira import JiraClient
from security_lakehouse.connectors_kubernetes import KubernetesClient
from security_lakehouse.connectors_okta import OktaClient
from security_lakehouse.repo_governance import GitLabGovernanceClient, GovernanceRepoSpec


class Response:
    def __init__(self, body, headers=None):
        self.body, self.headers = json.dumps(body).encode(), headers or {}

    def read(self, size=-1):
        if size < 0:
            result, self.body = self.body, b""
        else:
            result, self.body = self.body[:size], self.body[size:]
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.parametrize(
    "provider",
    ["bamboohr", "rippling", "intune", "workspace", "jamf", "crowdstrike", "snyk", "siem", "runtime", "workday"],
)
@pytest.mark.parametrize("bad", [[{"id": "good"}, "malformed"], {"not": "an array"}])
def test_provider_lists_reject_malformed_rows(monkeypatch, provider, bad):
    if provider == "bamboohr":
        adapter = object.__new__(bamboohr.BambooHRClient)
        monkeypatch.setattr(adapter, "_post_json", lambda body: {"data": bad})
        collect = adapter.employees
    elif provider == "rippling":
        adapter = object.__new__(rippling.RipplingClient)
        monkeypatch.setattr(adapter, "_get_json", lambda url: {"results": bad})
        collect = adapter.workers
    elif provider == "intune":
        adapter = object.__new__(intune.IntuneClient)
        monkeypatch.setattr(adapter, "_get_json", lambda url: {"value": bad})
        collect = adapter.managed_devices
    elif provider == "workspace":
        adapter = object.__new__(workspace.GoogleWorkspaceClient)
        monkeypatch.setattr(adapter, "_get_json", lambda url: {"users": bad})

        def collect():
            return adapter._json_collection("https://admin.googleapis.com/users?x=1", key="users")

    elif provider == "jamf":
        adapter = object.__new__(jamf.JamfProClient)
        monkeypatch.setattr(adapter, "_get", lambda url: {"results": bad, "totalCount": 1})
        collect = adapter.computers
    elif provider == "crowdstrike":

        def collect():
            return crowdstrike._resources({"resources": bad})

    elif provider == "snyk":
        adapter = snyk.SnykClient("SNYK-US-01", token="fixture")
        monkeypatch.setattr(adapter, "_get", lambda path, query, **kwargs: {"data": bad, "links": {}})

        def collect():
            return adapter.orgs()

    elif provider == "siem":

        def collect():
            return siem.SiemClient._extract_items(bad, "https://siem.example")

    elif provider == "runtime":

        def collect():
            return runtime.RuntimeGatewayClient._extract_items(bad, "https://runtime.example")

    else:

        def collect():
            return workday._report_rows({"Report_Entry": bad})

    with pytest.raises(ValueError):
        collect()


@pytest.mark.parametrize("method", ["issues", "projects"])
@pytest.mark.parametrize("malformed", [False, True])
def test_jira_cannot_satisfy_total_with_repeated_or_malformed_pages(monkeypatch, method, malformed):
    adapter = JiraClient("https://acme.atlassian.net", email="fixture", token="fixture")
    field = "issues" if method == "issues" else "values"
    monkeypatch.setattr(adapter, "_json", lambda url: {field: ["bad"] if malformed else [{"id": "same"}], "total": 2})
    with pytest.raises(ValueError):
        getattr(adapter, method)()


@pytest.mark.parametrize("next_url", ["https://evil.example/next", "https://acme.okta.com/api/v1/users?limit=200"])
def test_okta_rejects_foreign_or_repeated_continuation_before_request(monkeypatch, next_url):
    calls = []

    def get(request, **kwargs):
        calls.append(request.full_url)
        return Response([{"id": "user"}], {"Link": f'<{next_url}>; rel="next"'} if len(calls) == 1 else {})

    monkeypatch.setattr("security_lakehouse.netguard.open_public", get)
    with pytest.raises(ValueError):
        OktaClient("https://acme.okta.com", token="fixture").users()
    assert len(calls) == 1


def test_kubernetes_repeated_cursor_is_bounded():
    calls = []

    def listing(**kwargs):
        calls.append(kwargs)
        assert len(calls) <= 2, "unbounded repeated continuation"
        return {"items": [{"metadata": {"name": "ns"}}], "metadata": {"continue": "same"}}

    adapter = KubernetesClient(cluster_name="fixture", apis={"core": SimpleNamespace(list_namespace=listing)})
    with pytest.raises(RuntimeError, match="incomplete"):
        adapter.namespaces()


def test_kubernetes_rejects_malformed_items():
    adapter = KubernetesClient(
        cluster_name="fixture", apis={"core": SimpleNamespace(list_namespace=lambda **kw: {"items": ["bad"]})}
    )
    with pytest.raises(ValueError):
        adapter.namespaces()


def test_clickhouse_repeated_keyset_cannot_be_followed_by_false_completion(monkeypatch):
    adapter = ClickHouseClient("https://clickhouse.example", user="fixture", password="fixture")
    page = [{"event_time": "2026-01-01T00:00:00Z", "event_id": str(i)} for i in range(2)]
    pages = iter([page, page, []])
    monkeypatch.setattr(adapter, "_query_json_each_row", lambda *args, **kwargs: next(pages))
    with pytest.raises(ValueError, match="cursor"):
        adapter.normalized_events(page_size=2)


def test_s3_inventory_uses_all_sdk_pages(monkeypatch):
    adapter = object.__new__(AWSClient)
    api = SimpleNamespace(
        list_buckets=lambda: {"Buckets": [{"Name": "one"}], "ContinuationToken": "next"},
        get_paginator=lambda name: SimpleNamespace(
            paginate=lambda **kwargs: iter(
                [
                    {"Buckets": [{"Name": "one"}]},
                    {"Buckets": [{"Name": "two"}]},
                ]
            )
        ),
    )
    monkeypatch.setattr(adapter, "service_client", lambda *args, **kwargs: api)
    assert adapter.inventory("s3", region_name="us-east-1") == [{"id": "one"}, {"id": "two"}]


@pytest.mark.parametrize("method", ["collaborators", "teams", "branch_protection"])
def test_gitlab_follows_continuation_to_later_governance_records(monkeypatch, method):
    requests = []

    def get(request, **kwargs):
        requests.append(request.full_url)
        page = int(parse_qs(urlsplit(request.full_url).query).get("page", ["1"])[0])
        if page == 1:
            return Response(
                [{"id": 1, "username": "one", "name": "other"}], {"Link": f'<{request.full_url}&page=2>; rel="next"'}
            )
        return Response([{"id": 2, "username": "two", "name": "main", "required_approving_review_count": 2}])

    monkeypatch.setattr("security_lakehouse.netguard.open_public", get)
    adapter = GitLabGovernanceClient(GovernanceRepoSpec("gitlab", "acme", "api"), token="fixture")
    if method == "branch_protection":
        result = adapter.branch_protection("main")
        assert result["required_pull_request_reviews"]["required_approving_review_count"] == 2
    else:
        assert len(getattr(adapter, method)()) == 2
    assert len(requests) == 2


@pytest.mark.parametrize("method", ["hosts", "prevention_policies"])
def test_crowdstrike_empty_page_cannot_hide_reported_remaining_records(monkeypatch, method):
    adapter = object.__new__(crowdstrike.CrowdStrikeClient)
    monkeypatch.setattr(
        adapter,
        "_request",
        lambda *args, **kwargs: {
            "resources": [],
            "meta": {"pagination": {"total": 2, "offset": 0}},
        },
    )
    with pytest.raises(ValueError, match="incomplete"):
        getattr(adapter, method)()


@pytest.mark.parametrize("link", ["https://foreign.example/page", "https://gitlab.com/api/v4/other"])
def test_gitlab_rejects_continuation_to_another_endpoint(monkeypatch, link):
    calls = []

    def get(request, **kwargs):
        calls.append(request.full_url)
        return Response([{"id": 1}], {"Link": f'<{link}>; rel="next"'})

    monkeypatch.setattr("security_lakehouse.netguard.open_public", get)
    adapter = GitLabGovernanceClient(GovernanceRepoSpec("gitlab", "acme", "api"), token="fixture")
    with pytest.raises(ValueError, match="endpoint"):
        adapter.collaborators()
    assert len(calls) == 1


def test_gitlab_full_pages_without_headers_are_bounded(monkeypatch):
    adapter = GitLabGovernanceClient(GovernanceRepoSpec("gitlab", "acme", "api"), token="fixture")
    calls = []

    def page(url):
        calls.append(url)
        return [{"id": len(calls) * 100 + i} for i in range(100)], ""

    monkeypatch.setattr(adapter, "_request_page", page)
    with pytest.raises(RuntimeError, match="incomplete"):
        adapter._json_list("https://gitlab.com/api/v4/projects/acme/members", max_pages=2)
    assert len(calls) == 2
    assert parse_qs(urlsplit(calls[-1]).query)["page"] == ["2"]


def test_jamf_repeated_page_cannot_satisfy_total(monkeypatch):
    adapter = object.__new__(jamf.JamfProClient)
    monkeypatch.setattr(adapter, "_get", lambda url: {"results": [{"id": "same"}], "totalCount": 2})
    with pytest.raises(ValueError, match="incomplete"):
        adapter.computers()


def test_s3_inventory_uses_sdk_continuation_contract(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    stubber_module = pytest.importorskip("botocore.stub")
    api = boto3.client("s3", region_name="us-east-1", aws_access_key_id="fixture", aws_secret_access_key="fixture")
    adapter = object.__new__(AWSClient)
    monkeypatch.setattr(adapter, "service_client", lambda *args, **kwargs: api)
    with stubber_module.Stubber(api) as stubber:
        stubber.add_response(
            "list_buckets", {"Buckets": [{"Name": "one"}], "ContinuationToken": "next"}, {"MaxBuckets": 1000}
        )
        stubber.add_response(
            "list_buckets", {"Buckets": [{"Name": "two"}]}, {"MaxBuckets": 1000, "ContinuationToken": "next"}
        )
        assert adapter.inventory("s3", region_name="us-east-1") == [{"id": "one"}, {"id": "two"}]
        stubber.assert_no_pending_responses()
