"""Defender for Cloud assessment verdicts reach CCF safeguards end to end."""

from __future__ import annotations

import io
import json
import shutil
import urllib.error
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from security_lakehouse import connectors_azure
from security_lakehouse.connector_errors import CollectionGapError
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.connectors_azure import (
    DEFENDER_ASSESSMENT_SAFEGUARDS,
    ArmSecurityAssessmentReader,
    AzureCliClient,
    AzureFixtureClient,
)
from security_lakehouse.ingestion.paginate import IncompleteCollectionError
from security_lakehouse.io import read_jsonl
from security_lakehouse.safeguards import load_safeguards

FIXTURES = Path(__file__).parent / "fixtures"
SUBSCRIPTION = "11111111-1111-1111-1111-111111111111"
RG = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-app/providers"
STORAGE = f"{RG}/Microsoft.Storage/storageAccounts/evidencelake01"
VAULT = f"{RG}/Microsoft.KeyVault/vaults/kv-grclake"
VM = f"{RG}/Microsoft.Compute/virtualMachines/vm-build01"
STORAGE_ASSET = f"azure:resource:{connectors_azure._id_slug(STORAGE)}"
VAULT_ASSET = f"azure:resource:{connectors_azure._id_slug(VAULT)}"
VM_ASSET = f"azure:resource:{connectors_azure._id_slug(VM)}"
SUBSCRIPTION_ASSET = f"azure:subscription:{SUBSCRIPTION}"
SECURE_TRANSFER = "1c5de8e1-f68d-6a17-e0d2-ec259c42768c"
VAULT_DIAGNOSTICS = "88bbc99c-e5af-ddd7-6105-6150b2bfa519"
MACHINE_VULNS = "1195afff-c881-495e-9bc5-1486211ae03f"
DISABLED_OWNERS = "050ac097-3dda-4d24-ab6d-82568e7a50cf"
STORAGE_EXPOSURE = "51fd8bb1-0db4-bbf1-7e2b-cfcba7eb66a6"
ASSESSMENT = "azure.security.assessment"
TOKEN = "arm-token-must-not-leak"


def _assessment(resource_id: str, key: str, code: str | None, *, cause: str | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {"statusChangeDate": "2026-10-20T09:00:00Z"}
    if code is not None:
        status["code"] = code
    if cause:
        status["cause"] = cause
    return {
        "id": f"{resource_id}/providers/Microsoft.Security/assessments/{key}",
        "name": key,
        "type": "Microsoft.Security/assessments",
        "properties": {
            "resourceDetails": {"source": "Azure", "id": resource_id},
            "displayName": f"assessment {key[:8]}",
            "status": status,
        },
    }


def _resource(resource_id: str) -> dict[str, Any]:
    return {"id": resource_id, "name": resource_id.rsplit("/", 1)[-1], "type": "Microsoft.Test/things"}


def _fixture(tmp_path: Path, **files: object) -> Path:
    target = tmp_path / "azure_defender"
    shutil.copytree(FIXTURES / "azure_defender", target)
    for name, payload in files.items():
        (target / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    return target


def _sync(lake: Path, fixture: Path) -> Any:
    append_config_event(
        lake,
        connector_id="azure-posture",
        state="enabled",
        actor="alice",
        credentials={"subscription_id": SUBSCRIPTION},
    )
    result = run_connector_sync(lake, connector_id="azure-posture", fixture_dir=fixture)
    assert result.result == "ok"
    return result


def _assessment_rows(lake: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = read_jsonl(lake / CONNECTOR_RAW_FILE)
    return {
        (row["entity"]["asset_id"], row["attributes"]["assessment_key"]): row
        for row in rows
        if row["event_type"] == ASSESSMENT
    }


def _safeguard(lake: Path, safeguard_id: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    assessment = json.loads((lake / "gold" / "ccf_assessment.json").read_text(encoding="utf-8"))
    safeguard = next(row for row in assessment["safeguards"] if row["safeguard_id"] == safeguard_id)
    results = {row["asset_id"]: row for row in assessment["asset_results"] if row["safeguard_id"] == safeguard_id}
    return safeguard, results


def test_unhealthy_assessment_stays_open_without_attesting_an_untyped_safeguard(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, FIXTURES / "azure_defender")

    rows = _assessment_rows(lake)
    # Defender returned the storage account ID in a different case; the verdict
    # lands on the inventoried resource asset, not a second asset.
    secure_transfer = rows[(STORAGE_ASSET, SECURE_TRANSFER)]
    assert secure_transfer["status"] == "open"
    assert secure_transfer["safeguard_ids"] == ["SG-DATAPROTECTION-001"]
    assert secure_transfer["entity"]["asset_type"] == "cloud_resource"

    safeguard, results = _safeguard(lake, "SG-DATAPROTECTION-001")
    assert results[STORAGE_ASSET]["status"] == "not_evaluated"
    assert results[STORAGE_ASSET]["reasons"] == ["The safeguard has no declared evidence-type contract."]
    assert safeguard["status"] == "not_evaluated"

    logging, logging_results = _safeguard(lake, "SG-LOGGING-001")
    assert rows[(VAULT_ASSET, VAULT_DIAGNOSTICS)]["status"] == "pass"
    assert logging_results[VAULT_ASSET]["status"] == "not_evaluated"
    # Two other resources are inventoried but not assessed for logging.
    assert logging["status"] == "not_evaluated"

    identity, identity_results = _safeguard(lake, "SG-IDENTITY-001")
    assert rows[(SUBSCRIPTION_ASSET, DISABLED_OWNERS)]["status"] == "pass"
    assert identity_results[SUBSCRIPTION_ASSET]["status"] == "not_evaluated"
    assert rows[(SUBSCRIPTION_ASSET, DISABLED_OWNERS)]["entity"]["asset_type"] == "account_config"
    assert identity["status"] != "pass"


def test_unmapped_assessments_keep_their_verdict_but_never_bind(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _sync(lake, FIXTURES / "azure_defender")

    public_access = _assessment_rows(lake)[(STORAGE_ASSET, STORAGE_EXPOSURE)]
    assert public_access["status"] == "pass"
    assert not public_access.get("safeguard_ids")
    assert public_access["controls"] == []


def test_healthy_population_needs_a_declared_safeguard_contract(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        resources=[_resource(STORAGE)],
        security_assessments={"value": [_assessment(STORAGE, SECURE_TRANSFER, "Healthy")]},
    )
    lake = tmp_path / "lake"
    _sync(lake, fixture)

    safeguard, results = _safeguard(lake, "SG-DATAPROTECTION-001")
    assert _assessment_rows(lake)[(STORAGE_ASSET, SECURE_TRANSFER)]["status"] == "pass"
    assert results[STORAGE_ASSET]["status"] == "not_evaluated"
    assert results[STORAGE_ASSET]["reasons"] == ["The safeguard has no declared evidence-type contract."]
    assert safeguard["status"] == "not_evaluated"
    assert safeguard["assessed_asset_count"] == safeguard["applicable_asset_count"] == 1


def test_healthy_assessment_does_not_pass_while_other_resources_are_unassessed(tmp_path: Path) -> None:
    fixture = _fixture(
        tmp_path,
        resources=[_resource(STORAGE), _resource(VAULT)],
        security_assessments={"value": [_assessment(STORAGE, SECURE_TRANSFER, "Healthy")]},
    )
    lake = tmp_path / "lake"
    _sync(lake, fixture)

    safeguard, results = _safeguard(lake, "SG-DATAPROTECTION-001")
    assert _assessment_rows(lake)[(STORAGE_ASSET, SECURE_TRANSFER)]["status"] == "pass"
    assert results[STORAGE_ASSET]["status"] == "not_evaluated"
    assert results[STORAGE_ASSET]["reasons"] == ["The safeguard has no declared evidence-type contract."]
    assert safeguard["status"] == "not_evaluated"
    assert safeguard["unassessed_asset_count"] == 1


@pytest.mark.parametrize(
    ("code", "raw_status", "bound"),
    [("NotApplicable", "observed", False), ("Retired", "not_evaluated", True), (None, "not_evaluated", True)],
)
def test_not_applicable_and_unknown_codes_never_pass(
    tmp_path: Path, code: str | None, raw_status: str, bound: bool
) -> None:
    fixture = _fixture(
        tmp_path,
        resources=[_resource(STORAGE)],
        security_assessments={"value": [_assessment(STORAGE, SECURE_TRANSFER, code, cause="OffByPolicy")]},
    )
    lake = tmp_path / "lake"
    _sync(lake, fixture)

    row = _assessment_rows(lake)[(STORAGE_ASSET, SECURE_TRANSFER)]
    assert row["status"] == raw_status
    assert bool(row.get("safeguard_ids")) is bound
    safeguard, _ = _safeguard(lake, "SG-DATAPROTECTION-001")
    assert safeguard["status"] == "not_evaluated"


def test_mapped_key_on_the_wrong_scope_stays_unbound(tmp_path: Path) -> None:
    # A subscription-scoped key reported on a resource (or the reverse) is not
    # the subject the mapping was reviewed for.
    fixture = _fixture(
        tmp_path,
        resources=[_resource(STORAGE)],
        security_assessments={
            "value": [
                _assessment(STORAGE, DISABLED_OWNERS, "Unhealthy"),
                _assessment(f"/subscriptions/{SUBSCRIPTION}", SECURE_TRANSFER, "Unhealthy"),
            ]
        },
    )
    lake = tmp_path / "lake"
    _sync(lake, fixture)

    rows = _assessment_rows(lake)
    assert rows[(STORAGE_ASSET, DISABLED_OWNERS)]["status"] == "open"
    assert not rows[(STORAGE_ASSET, DISABLED_OWNERS)].get("safeguard_ids")
    assert not rows[(SUBSCRIPTION_ASSET, SECURE_TRANSFER)].get("safeguard_ids")


def test_forbidden_security_read_is_a_coverage_gap_and_other_evidence_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(self: AzureFixtureClient) -> list[dict[str, Any]]:
        reader = ArmSecurityAssessmentReader(SUBSCRIPTION, token_provider=lambda: TOKEN, sleep=lambda _s: None)
        reader._open = lambda request: (_ for _ in ()).throw(_http_error(request.full_url, 403))  # type: ignore[method-assign]
        return reader.assessments()

    monkeypatch.setattr(AzureFixtureClient, "security_assessments", forbidden)
    lake = tmp_path / "lake"
    result = _sync(lake, FIXTURES / "azure_defender")

    assert [gap["collection"] for gap in result.coverage_gaps] == ["security_assessments"]
    assert result.coverage_gaps[0]["reason"] == "permission_denied"
    assert "Microsoft.Security/assessments/read" in result.coverage_gaps[0]["permission"]
    assert latest_run(lake, "azure-posture", kind="sync")["metadata"]["partial"] is True
    rows = read_jsonl(lake / CONNECTOR_RAW_FILE)
    assert {row["event_type"] for row in rows} == {"azure.cloud.resource", "azure.collection_gap"}
    gap = next(row for row in rows if row["event_type"] == "azure.collection_gap")
    assert gap["entity"]["asset_type"] == "collection_scope"
    assert gap["entity"]["asset_id"] not in {SUBSCRIPTION_ASSET, STORAGE_ASSET}
    assert not gap.get("safeguard_ids")
    assert TOKEN not in json.dumps(rows)
    for safeguard_id in ("SG-DATAPROTECTION-001", "SG-LOGGING-001", "SG-IDENTITY-001"):
        assert _safeguard(lake, safeguard_id)[0]["status"] != "pass"


def _http_error(url: str, code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return urllib.error.HTTPError(url, code, "error", message, io.BytesIO(b'{"error":{"message":"secret detail"}}'))


class _Pages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.requests: list[Any] = []

    def __call__(self, request: Any) -> Any:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _reader(pages: _Pages, *, max_pages: int = 5, sleeps: list[float] | None = None) -> ArmSecurityAssessmentReader:
    reader = ArmSecurityAssessmentReader(
        SUBSCRIPTION,
        token_provider=lambda: TOKEN,
        max_pages=max_pages,
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )
    reader._open = pages  # type: ignore[method-assign]
    return reader


ARM = "https://management.azure.com"
LIST_PATH = f"/subscriptions/{SUBSCRIPTION}/providers/Microsoft.Security/assessments"


def test_reader_follows_same_host_next_links_with_the_documented_api_version() -> None:
    next_link = f"{ARM}{LIST_PATH}?api-version=2021-06-01&$skipToken=page2"
    pages = _Pages(
        [
            {"value": [_assessment(STORAGE, SECURE_TRANSFER, "Healthy")], "nextLink": next_link},
            {"value": [_assessment(VAULT, VAULT_DIAGNOSTICS, "Unhealthy")]},
        ]
    )
    rows = _reader(pages).assessments()

    assert [row["name"] for row in rows] == [SECURE_TRANSFER, VAULT_DIAGNOSTICS]
    assert pages.requests[0].full_url == f"{ARM}{LIST_PATH}?api-version=2021-06-01"
    assert pages.requests[1].full_url == next_link
    assert all(request.get_method() == "GET" for request in pages.requests)
    assert all(request.get_header("Authorization") == f"Bearer {TOKEN}" for request in pages.requests)


@pytest.mark.parametrize(
    "next_link",
    [
        f"https://attacker.example{LIST_PATH}?api-version=2021-06-01",
        f"http://management.azure.com{LIST_PATH}?api-version=2021-06-01",
        f"https://management.azure.com.attacker.example{LIST_PATH}",
        f"https://user@management.azure.com{LIST_PATH}",
    ],
)
def test_reader_refuses_a_next_link_off_the_arm_host(next_link: str) -> None:
    pages = _Pages([{"value": [], "nextLink": next_link}])
    with pytest.raises(ValueError, match="Azure security assessments collection incomplete") as exc:
        _reader(pages).assessments()
    assert len(pages.requests) == 1
    assert "attacker" not in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_reader_page_budget_is_bounded() -> None:
    pages = _Pages(
        [{"value": [], "nextLink": f"{ARM}{LIST_PATH}?api-version=2021-06-01&$skipToken={n}"} for n in range(3)]
    )
    with pytest.raises(IncompleteCollectionError):
        _reader(pages, max_pages=2).assessments()
    assert len(pages.requests) == 2


def test_reader_honors_retry_after_on_429() -> None:
    url = f"{ARM}{LIST_PATH}?api-version=2021-06-01"
    pages = _Pages([_http_error(url, 429, {"Retry-After": "3"}), {"value": []}])
    sleeps: list[float] = []
    assert _reader(pages, sleeps=sleeps).assessments() == []
    assert sleeps == [3.0]
    assert len(pages.requests) == 2


@pytest.mark.parametrize(("code", "reason"), [(401, "unauthorized"), (403, "permission_denied"), (404, "not_found")])
def test_reader_maps_refusals_to_safe_gaps(code: int, reason: str) -> None:
    pages = _Pages([_http_error(f"{ARM}{LIST_PATH}", code)])
    with pytest.raises(CollectionGapError) as exc:
        _reader(pages).assessments()
    assert exc.value.collection == "security_assessments"
    assert exc.value.reason == reason
    assert "secret detail" not in str(exc.value)
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize("payload", [None, [], {"value": None}, {"value": [7]}, {"value": [], "nextLink": 7}])
def test_reader_rejects_malformed_pages(payload: Any) -> None:
    with pytest.raises(ValueError, match="Azure security assessments collection incomplete"):
        _reader(_Pages([payload])).assessments()


def test_malformed_security_page_becomes_a_gap_not_an_empty_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def malformed(self: AzureFixtureClient) -> list[dict[str, Any]]:
        return _reader(_Pages([{"value": [], "nextLink": "https://attacker.example/next"}])).assessments()

    monkeypatch.setattr(AzureFixtureClient, "security_assessments", malformed)
    lake = tmp_path / "lake"
    result = _sync(lake, FIXTURES / "azure_defender")
    assert [(gap["collection"], gap["reason"]) for gap in result.coverage_gaps] == [
        ("security_assessments", "invalid_data")
    ]
    assert "attacker" not in json.dumps(read_jsonl(lake / CONNECTOR_RAW_FILE))


def test_cli_client_lists_assessments_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> SimpleNamespace:
        calls.append(cmd)
        return SimpleNamespace(stdout=json.dumps([{"name": SECURE_TRANSFER}]), stderr="")

    monkeypatch.setattr("security_lakehouse.connectors_azure.shutil.which", lambda _: "/usr/bin/az")
    monkeypatch.setattr("security_lakehouse.connectors_azure.subprocess.run", fake_run)
    assert AzureCliClient("sub").security_assessments() == [{"name": SECURE_TRANSFER}]
    assert calls == [["/usr/bin/az", "security", "assessment", "list", "--subscription", "sub", "--output", "json"]]


def test_cli_authorization_failure_is_a_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    def denied(cmd: list[str], **_kwargs: Any) -> SimpleNamespace:
        raise subprocess.CalledProcessError(1, cmd, stderr="(AuthorizationFailed) secret detail")

    monkeypatch.setattr("security_lakehouse.connectors_azure.shutil.which", lambda _: "/usr/bin/az")
    monkeypatch.setattr("security_lakehouse.connectors_azure.subprocess.run", denied)
    rows = connectors_azure.collect_azure_evidence(_CliOnlyAssessments(AzureCliClient("sub")))
    gap = next(row for row in rows if row["event_type"] == "azure.collection_gap")
    assert gap["attributes"]["reason"] == "permission_denied"
    assert "secret detail" not in json.dumps(gap)


class _CliOnlyAssessments:
    def __init__(self, cli: AzureCliClient) -> None:
        self.subscription_id = cli.subscription_id
        self.security_assessments = cli.security_assessments

    def role_assignments(self) -> list[dict[str, Any]]:
        return []

    def role_definitions(self) -> list[dict[str, Any]]:
        return []

    def policy_assignments(self) -> list[dict[str, Any]]:
        return []

    def resources(self) -> list[dict[str, Any]]:
        return []


def test_cli_resource_details_casing_is_accepted() -> None:
    # The az CLI serializes resourceDetails with capitalized keys.
    row = {
        "id": f"{STORAGE}/providers/Microsoft.Security/assessments/{SECURE_TRANSFER}",
        "name": SECURE_TRANSFER,
        "displayName": "Secure transfer to storage accounts should be enabled",
        "resourceDetails": {"Id": STORAGE, "Source": "Azure", "source": None},
        "status": {"code": "Unhealthy"},
    }
    client = SimpleNamespace(
        subscription_id=SUBSCRIPTION,
        role_assignments=list,
        role_definitions=list,
        policy_assignments=list,
        resources=lambda: [_resource(STORAGE)],
        security_assessments=lambda: [row],
    )
    rows = connectors_azure.collect_azure_evidence(client)  # type: ignore[arg-type]
    verdict = next(r for r in rows if r["event_type"] == ASSESSMENT)
    assert verdict["entity"]["asset_id"] == STORAGE_ASSET
    assert verdict["safeguard_ids"] == ["SG-DATAPROTECTION-001"]


def test_assessment_mapping_stays_inside_each_safeguard_definition() -> None:
    definitions = {row["safeguard_id"]: row for row in load_safeguards()["safeguards"]}
    assert DEFENDER_ASSESSMENT_SAFEGUARDS
    for key, mapping in DEFENDER_ASSESSMENT_SAFEGUARDS.items():
        assert key == key.lower() and len(key) == 36
        definition = definitions[mapping.safeguard_id]
        assert mapping.asset_type in definition["asset_types"], key
        crosswalk = {member["control_id"] for member in definition["satisfies"]}
        assert mapping.controls and set(mapping.controls) <= crosswalk, key
