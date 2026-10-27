"""Oversized provider replies fail explicitly without publishing incomplete evidence."""

import io
import urllib.request
from types import SimpleNamespace

import pytest

from security_lakehouse import http_response, netguard, repo_governance
from security_lakehouse.commercial.billing import _stripe_request
from security_lakehouse.connectors_azure import ArmSecurityAssessmentReader
from security_lakehouse.connectors_bamboohr import BambooHRClient
from security_lakehouse.connectors_clickhouse import ClickHouseClient
from security_lakehouse.connectors_crowdstrike import CrowdStrikeClient
from security_lakehouse.connectors_databricks import DatabricksClient
from security_lakehouse.connectors_google_workspace import GoogleOAuthTokenSource, GoogleWorkspaceClient
from security_lakehouse.connectors_jamf import JamfProClient
from security_lakehouse.connectors_jira import JiraClient
from security_lakehouse.connectors_lambda import LambdaCloudClient
from security_lakehouse.connectors_okta import OktaClient
from security_lakehouse.connectors_rippling import RipplingClient
from security_lakehouse.connectors_snyk import SnykClient
from security_lakehouse.connectors_workday import WorkdayReportClient
from security_lakehouse.ingestion.http_export import CursorExportClient
from security_lakehouse.ingestion.microsoft_graph import MicrosoftGraphClient
from security_lakehouse.ingestion.oauth import ClientCredentialsToken

URL = "https://provider.example/data"
REQUEST = urllib.request.Request(URL)
CLIENT = SimpleNamespace(
    timeout=3,
    label="synthetic",
    token="synthetic",
    _token="synthetic",
    email="reader@example.test",
    _token_provider=lambda: "synthetic",
    _pace=lambda: None,
    dataset_url=URL,
    report_url=URL,
    _auth="Basic synthetic",
    base_url="https://provider.example",
    database="synthetic",
    user="synthetic",
    password="synthetic",
)

READS = [
    lambda: repo_governance._guarded_page(REQUEST, timeout=3, label="synthetic"),
    lambda: BambooHRClient._post_json(CLIENT, {}),
    lambda: WorkdayReportClient._get_json(CLIENT),
    lambda: ClickHouseClient._query_json_each_row(CLIENT, "SELECT 1 FORMAT JSONEachRow"),
    lambda: GoogleOAuthTokenSource(
        refresh_token="synthetic", client_id="synthetic", client_secret="synthetic"
    ).refresh(),
    lambda: _stripe_request("GET", "/synthetic"),
    lambda: DatabricksClient._open(CLIENT, REQUEST),
    lambda: SnykClient._open(CLIENT, REQUEST),
    lambda: LambdaCloudClient._open(CLIENT, REQUEST),
    lambda: ArmSecurityAssessmentReader._open(CLIENT, REQUEST),
    lambda: CrowdStrikeClient._open(CLIENT, REQUEST),
    lambda: JamfProClient._open(CLIENT, REQUEST),
    lambda: ClientCredentialsToken._open(CLIENT, REQUEST),
    lambda: MicrosoftGraphClient._get_json(CLIENT, URL),
    lambda: GoogleWorkspaceClient._open_json(CLIENT, URL, "synthetic"),
    lambda: RipplingClient._get_json(CLIENT, URL),
    lambda: JiraClient._json(CLIENT, URL),
    lambda: OktaClient("https://provider.example", token="synthetic")._json_list(URL),
    lambda: CursorExportClient._fetch_json(SimpleNamespace(timeout=3, token="synthetic", url_label="synthetic"), URL),
]


@pytest.mark.parametrize(
    "name,read",
    zip(
        [
            "github",
            "bamboohr",
            "workday",
            "clickhouse",
            "google-oauth",
            "billing",
            "databricks",
            "snyk",
            "lambda",
            "azure",
            "crowdstrike",
            "jamf",
            "oauth",
            "graph",
            "google",
            "rippling",
            "jira",
            "okta",
            "export",
        ],
        READS,
        strict=True,
    ),
)
def test_provider_reads_enforce_shared_ceiling_and_close(monkeypatch, name, read):
    monkeypatch.setenv("GRC_LAKE_STRIPE_SECRET_KEY", "synthetic-stripe-key")
    monkeypatch.setattr(http_response, "MAX_RESPONSE_BYTES", 16)
    body = b'{"data":"' + b"x" * 32 + b'"}'
    response = io.BytesIO(b"[" + body + b"]" if name == "okta" else body)
    response.headers = {}
    response.status = 200
    calls = []

    def opened(*args, **kwargs):
        calls.append(1)
        return response

    monkeypatch.setattr(netguard, "open_public", opened)
    monkeypatch.setattr(netguard, "open_guarded", opened)
    with pytest.raises(http_response.ResponseLimitError):
        read()
    assert response.closed
    assert len(calls) == 1


@pytest.mark.parametrize("aggregate", [False, True])
def test_oversized_sync_records_gap_and_preserves_generation(tmp_path, monkeypatch, aggregate):
    from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
    from security_lakehouse.connector_state import append_config_event
    from security_lakehouse.ingestion.watermark import read_watermark, write_watermark
    from test_connector_runner import FIXTURE

    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="test")
    run_connector_sync(tmp_path, connector_id="github-security", repo="synthetic/repo", fixture_dir=FIXTURE)
    paths = [tmp_path / CONNECTOR_RAW_FILE, tmp_path / "gold/ccf_assessment.json"]
    before = [p.read_bytes() for p in paths]
    write_watermark(tmp_path, "github-security", "previous")
    monkeypatch.setattr(http_response, "MAX_RESPONSE_BYTES", 1024 if aggregate else 16)
    monkeypatch.setattr(http_response, "MAX_RUN_RESPONSE_BYTES", 16 if aggregate else 1024)
    body = b'{"ok":1}' if aggregate else b'{"data":"' + b"x" * 32 + b'"}'
    monkeypatch.setattr(netguard, "open_public", lambda *a, **k: io.BytesIO(body))

    def collect(*args, **kwargs):
        for _ in range(3):
            repo_governance._guarded_page(REQUEST, timeout=3, label="synthetic")
        return []

    monkeypatch.setattr("security_lakehouse.connector_runner._collect", collect)
    with pytest.raises(ConnectorSyncError) as caught:
        run_connector_sync(tmp_path, connector_id="github-security")
    run = caught.value.run
    assert run["result"] == "error"
    assert run["metadata"]["partial"] is True
    assert run["metadata"]["coverage_gaps"][0]["reason"] == (
        "run_response_byte_limit" if aggregate else "response_byte_limit"
    )
    assert [p.read_bytes() for p in paths] == before
    assert read_watermark(tmp_path, "github-security") == "previous"


def test_oversized_http_error_body_is_not_read_unbounded():
    import urllib.error

    body = io.BytesIO(b"x" * (http_response.MAX_RESPONSE_BYTES + 1))
    error = urllib.error.HTTPError(URL, 403, "denied", {}, body)
    with pytest.raises(http_response.ResponseLimitError):
        repo_governance._http_error_message(error)
    assert body.closed


def test_okta_oversized_second_page_does_not_return_first_page(monkeypatch):
    monkeypatch.setattr(http_response, "MAX_RESPONSE_BYTES", 64)
    first = io.BytesIO(b'[{"id":"first"}]')
    first.headers = {"Link": '<https://provider.example/data?after=next>; rel="next"'}
    second = io.BytesIO(b'[{"id":"' + b"x" * 65 + b'"}]')
    second.headers = {}
    responses = iter([first, second])
    monkeypatch.setattr(netguard, "open_public", lambda *a, **k: next(responses))
    with pytest.raises(http_response.ResponseLimitError):
        OktaClient("https://provider.example", token="synthetic")._json_list(URL)
    assert first.closed and second.closed
