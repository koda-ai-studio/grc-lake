"""Lambda Cloud GPU instance exposure and access evidence (fixture-backed + fake HTTP).

Fixtures follow the Lambda Cloud API OpenAPI document (version 1.10.0, served at
``https://cloud.lambda.ai/api/v1/openapi.json``): every response is a
``{"data": ...}`` envelope; ``GET /instances`` and ``GET /api-keys`` page with
``page_size``/``page_token``; firewall rulesets, the global ruleset, and SSH keys
are unpaged. All identifiers, keys, and addresses are synthetic.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import struct
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import connector_runner, connectors_lambda, netguard
from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.connector_errors import ConnectorAccessError, collection_gaps
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.connectors_lambda import (
    LambdaCloudClient,
    LambdaCloudFixtureClient,
    collect_lambda_cloud_evidence,
    ssh_key_strength,
)
from security_lakehouse.io import read_jsonl
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures" / "lambda-cloud"
ACCOUNT = "5c8d0f6a2b3e4d1f9a7b6c5d4e3f2a10"
COLLECTED = datetime(2026, 10, 24, tzinfo=UTC)
TRAIN, INFER, DEV, BATCH, OLD = (f"0a1b2c3d4e5f40718293a4b5c6d7e8f{n}" for n in range(1, 6))
USER_A, SERVICE, USER_B = (f"7d2e1f0a3b4c5d6e7f8a9b0c1d2e3f0{n}" for n in range(1, 4))


def _rows(fixture: Path = FIXTURE) -> list[dict[str, Any]]:
    return collect_lambda_cloud_evidence(LambdaCloudFixtureClient(fixture), collected_at=COLLECTED)


def _by(rows: list[dict[str, Any]], event_type: str, key: str = "asset_id") -> dict[str, dict[str, Any]]:
    prefix = f"lambda_cloud:{ACCOUNT}:"
    matches = [r for r in rows if r["event_type"] == event_type]
    if key == "asset_id":
        return {r["entity"]["asset_id"].removeprefix(prefix): r for r in matches}
    return {r["attributes"][key]: r for r in matches}


def _safeguards() -> dict[str, dict[str, Any]]:
    payload = json.loads((Path(__file__).parents[1] / "controls" / "safeguards.json").read_text(encoding="utf-8"))
    return {row["safeguard_id"]: row for row in payload["safeguards"]}


def _copy(tmp_path: Path, *names: str) -> Path:
    for name in names:
        shutil.copy(FIXTURE / name, tmp_path / name)
    return tmp_path


def test_events_are_valid_scoped_to_the_account_and_tagged_with_catalog_controls() -> None:
    rows = _rows()

    assert validate_raw_events(rows) == []
    # 5 instances x (network exposure + SSH access) + 4 API keys.
    assert len(rows) == 14
    catalog = load_control_catalog()
    for row in rows:
        assert row["source"] == "lambda_cloud"
        assert row["entity"]["org"] == ACCOUNT
        assert row["controls"] and all(control in catalog for control in row["controls"])
    assert collection_gaps(rows) == []


@pytest.mark.parametrize(
    ("instance", "status", "severity", "reason"),
    [
        (TRAIN, "pass", "info", "inbound_restricted"),
        (INFER, "open", "medium", "service_port_open_to_internet"),
        (DEV, "open", "high", "administrative_access_open_to_internet"),
        (BATCH, "not_evaluated", "info", "firewall_not_applied_in_region"),
        (OLD, "observed", "info", "instance_not_running"),
    ],
)
def test_network_exposure_combines_global_and_attached_rulesets(
    instance: str, status: str, severity: str, reason: str
) -> None:
    row = _by(_rows(), "lambda_cloud.instance.network_exposure")[f"instance:{instance}"]

    assert (row["status"], row["severity"], row["attributes"]["finding_reason"]) == (status, severity, reason)
    assert row["entity"]["asset_type"] == "cloud_resource"
    assert row["safeguard_ids"] == ["SG-NETWORK-001"]


def test_internet_open_rules_name_their_ruleset_and_ports() -> None:
    rows = _by(_rows(), "lambda_cloud.instance.network_exposure")
    assert rows[f"instance:{INFER}"]["attributes"]["internet_open_rules"] == [
        {"ruleset": "rs-inference", "protocol": "tcp", "port_range": [8000, 8000]}
    ]
    assert rows[f"instance:{DEV}"]["attributes"]["internet_open_rules"] == [
        {"ruleset": "rs-wide-open", "protocol": "all", "port_range": None}
    ]
    # Office-only SSH and world ICMP do not count as internet-open service access.
    assert rows[f"instance:{TRAIN}"]["attributes"]["internet_open_rules"] == []
    assert rows[f"instance:{TRAIN}"]["attributes"]["effective_rule_count"] == 3


@pytest.mark.parametrize(
    ("protocol", "ports", "reason"),
    [
        ("tcp", None, "administrative_access_open_to_internet"),
        ("tcp", [20, 25], "administrative_access_open_to_internet"),
        ("udp", [3389, 3389], "administrative_access_open_to_internet"),
        ("tcp", [8080, 8090], "service_port_open_to_internet"),
        ("icmp", None, "inbound_restricted"),
    ],
)
def test_world_open_rule_classification(tmp_path: Path, protocol: str, ports: list[int] | None, reason: str) -> None:
    _copy(tmp_path, "account.json", "instances.json", "ssh_keys.json", "api_keys.json", "firewall_rulesets.json")
    rule: dict[str, Any] = {"protocol": protocol, "source_network": "0.0.0.0/0", "description": ""}
    if ports:
        rule["port_range"] = ports
    (tmp_path / "global_firewall_ruleset.json").write_text(json.dumps({"data": {"id": "global", "rules": [rule]}}))

    row = _by(_rows(tmp_path), "lambda_cloud.instance.network_exposure")[f"instance:{TRAIN}"]
    assert row["attributes"]["finding_reason"] == reason


def test_instance_without_public_ip_is_not_evaluated(tmp_path: Path) -> None:
    _copy(tmp_path, "account.json", "ssh_keys.json", "api_keys.json", "firewall_rulesets.json")
    _copy(tmp_path, "global_firewall_ruleset.json")
    instances = json.loads((FIXTURE / "instances.json").read_text())
    instances["data"] = [{k: v for k, v in instances["data"][0].items() if k != "ip"}]
    (tmp_path / "instances.json").write_text(json.dumps(instances))

    row = _by(_rows(tmp_path), "lambda_cloud.instance.network_exposure")[f"instance:{TRAIN}"]
    assert (row["status"], row["attributes"]["finding_reason"]) == ("not_evaluated", "no_public_ip_reported")


def test_instance_attributes_drop_secrets_addresses_and_free_text() -> None:
    rows = _rows()
    text = json.dumps(rows)
    for forbidden in (
        "synthetic-jupyter-token",
        "jupyter_token",
        "11.10.20.30",
        "10.19.60.24",
        "lambda.example.test",
        "research",
        "HTTPS from the VPN",
        "Synthetic Person",
        "ssh-ed25519 AAAA",
    ):
        assert forbidden not in text, forbidden
    attributes = _by(rows, "lambda_cloud.instance.network_exposure")[f"instance:{TRAIN}"]["attributes"]
    assert attributes["has_public_ip"] is True
    assert attributes["jupyter_url_present"] is True
    assert attributes["gpu_description"] == "H100 (80 GB SXM5)"
    assert attributes["region"] == "us-east-1"


@pytest.mark.parametrize(
    ("instance", "status", "severity", "reason"),
    [
        (TRAIN, "observed", "info", None),
        (INFER, "open", "medium", "weak_ssh_key"),
        (DEV, "open", "medium", "weak_ssh_key"),
        (BATCH, "observed", "info", None),
        (OLD, "observed", "info", "instance_not_running"),
    ],
)
def test_ssh_access_flags_weak_keys_but_never_passes_logical_access(
    instance: str, status: str, severity: str, reason: str | None
) -> None:
    row = _by(_rows(), "lambda_cloud.instance.ssh_access")[f"instance:{instance}"]

    assert (row["status"], row["severity"], row["attributes"]["finding_reason"]) == (status, severity, reason)
    assert row["safeguard_ids"] == ["SG-IDENTITY-001"]


def test_ssh_access_lists_key_algorithms_without_key_material() -> None:
    dev = _by(_rows(), "lambda_cloud.instance.ssh_access")[f"instance:{DEV}"]["attributes"]
    assert dev["ssh_keys"] == [
        {"name": "build-rsa", "algorithm": "ssh-rsa", "bits": 4096, "weak": False},
        {"name": "old-dsa", "algorithm": "ssh-dss", "bits": None, "weak": True},
    ]


def _ssh(kind: str, *fields: bytes) -> str:
    blob = b"".join(struct.pack(">I", len(f)) + f for f in (kind.encode(), *fields))
    return base64.b64encode(blob).decode()


EXPONENT = (65537).to_bytes(3, "big")
MODULUS_2048 = bytes([0]) + bytes([255]) * 256
MODULUS_2040 = bytes([0]) + bytes([255]) * 255


@pytest.mark.parametrize(
    ("public_key", "expected"),
    [
        (f"ssh-ed25519 {_ssh('ssh-ed25519', bytes(32))} c", ("ssh-ed25519", None, False)),
        (
            f"ecdsa-sha2-nistp256 {_ssh('ecdsa-sha2-nistp256', b'nistp256', bytes(65))}",
            ("ecdsa-sha2-nistp256", None, False),
        ),
        ("ssh-rsa " + _ssh("ssh-rsa", EXPONENT, MODULUS_2048), ("ssh-rsa", 2048, False)),
        ("ssh-rsa " + _ssh("ssh-rsa", EXPONENT, MODULUS_2040), ("ssh-rsa", 2040, True)),
        ("not-a-key", ("unknown", None, None)),
        ("ssh-rsa !!!notbase64", ("unknown", None, None)),
        # Truncated blob.
        ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL0aGVzdA==", ("unknown", None, None)),
        # Declared type and encoded type disagree: not trusted.
        (f"ssh-rsa {_ssh('ssh-ed25519', bytes(32))}", ("unknown", None, None)),
    ],
)
def test_ssh_key_strength_parsing(public_key: str, expected: tuple[str, int | None, bool | None]) -> None:
    assert ssh_key_strength(public_key) == expected


def test_unknown_key_name_leaves_the_outcome_unevaluated(tmp_path: Path) -> None:
    _copy(tmp_path, "account.json", "instances.json", "api_keys.json", "firewall_rulesets.json")
    _copy(tmp_path, "global_firewall_ruleset.json")
    (tmp_path / "ssh_keys.json").write_text(json.dumps({"data": []}))

    row = _by(_rows(tmp_path), "lambda_cloud.instance.ssh_access")[f"instance:{TRAIN}"]
    assert (row["status"], row["attributes"]["finding_reason"]) == ("not_evaluated", "ssh_key_not_listed")


@pytest.mark.parametrize(
    ("key_id", "status", "severity", "reason"),
    [
        ("ak-01", "open", "medium", "api_key_without_expiration"),
        ("ak-02", "open", "low", "api_key_unused"),
        ("ak-03", "observed", "info", None),
        ("ak-04", "observed", "info", "api_key_expired"),
    ],
)
def test_api_key_hygiene_is_evidence_against_the_owning_identity(
    key_id: str, status: str, severity: str, reason: str | None
) -> None:
    row = _by(_rows(), "lambda_cloud.identity.api_key", key="key_id")[key_id]

    assert (row["status"], row["severity"], row["attributes"]["finding_reason"]) == (status, severity, reason)
    assert row["entity"]["asset_type"] == "identity_account"
    assert row["safeguard_ids"] == ["SG-IDENTITY-001"]


def test_api_keys_attach_to_identities_not_people() -> None:
    rows = _by(_rows(), "lambda_cloud.identity.api_key", key="key_id")
    assert rows["ak-01"]["entity"]["asset_id"] == f"lambda_cloud:{ACCOUNT}:identity:{USER_A}"
    assert rows["ak-02"]["attributes"]["identity_type"] == "service"
    assert "identity_display_name" not in rows["ak-01"]["attributes"]


@pytest.mark.parametrize("missing", ["firewall_rulesets.json", "global_firewall_ruleset.json"])
def test_missing_firewall_collection_is_a_gap_and_exposure_is_not_evaluated(tmp_path: Path, missing: str) -> None:
    names = {"account.json", "instances.json", "ssh_keys.json", "api_keys.json", "firewall_rulesets.json"}
    names.add("global_firewall_ruleset.json")
    _copy(tmp_path, *(names - {missing}))

    rows = _rows(tmp_path)
    assert validate_raw_events(rows) == []
    assert [gap["collection"] for gap in collection_gaps(rows)] == [missing.removesuffix(".json")]
    exposure = _by(rows, "lambda_cloud.instance.network_exposure")[f"instance:{TRAIN}"]
    assert (exposure["status"], exposure["attributes"]["finding_reason"]) == (
        "not_evaluated",
        "firewall_rules_not_collected",
    )


def test_missing_optional_collections_keep_instance_evidence(tmp_path: Path) -> None:
    _copy(tmp_path, "account.json", "instances.json")

    rows = _rows(tmp_path)
    assert {gap["collection"] for gap in collection_gaps(rows)} == {
        "firewall_rulesets",
        "global_firewall_ruleset",
        "ssh_keys",
        "api_keys",
    }
    assert len(_by(rows, "lambda_cloud.instance.network_exposure")) == 5
    assert not _by(rows, "lambda_cloud.identity.api_key", key="key_id")


def test_missing_instances_is_not_an_empty_inventory(tmp_path: Path) -> None:
    _copy(tmp_path, "account.json")
    with pytest.raises(ValueError, match="instances"):
        _rows(tmp_path)


@pytest.mark.parametrize("bad", [{"data": {"id": 1}}, {"data": [1]}, {"nope": []}])
def test_malformed_instances_payload_fails_closed(tmp_path: Path, bad: dict[str, Any]) -> None:
    _copy(tmp_path, "account.json")
    (tmp_path / "instances.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        _rows(tmp_path)


# --- Live client over a fake HTTP layer ---------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _http_error(url: str, code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    body = io.BytesIO(json.dumps({"error": {"code": "global/forbidden", "message": "no"}}).encode())
    return urllib.error.HTTPError(url, code, "error", message, body)


class _FakeLambda:
    def __init__(self, routes: dict[str, list[Any]]) -> None:
        self.routes = routes
        self.requests: list[Any] = []

    def __call__(self, request: Any, *, timeout: float | None = None, label: str = "") -> _Response:
        self.requests.append(request)
        parsed = urllib.parse.urlsplit(request.full_url)
        queue = self.routes.get(parsed.path, [])
        if not queue:
            raise _http_error(request.full_url, 404)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Response(json.dumps(item).encode())


def _fixture(name: str) -> Any:
    return json.loads((FIXTURE / name).read_text())


def _client(monkeypatch: pytest.MonkeyPatch, routes: dict[str, list[Any]]) -> tuple[LambdaCloudClient, _FakeLambda]:
    fake = _FakeLambda({f"/api/v1{path}": queue for path, queue in routes.items()})
    monkeypatch.setattr(netguard, "open_public", fake)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    return LambdaCloudClient(api_key="synthetic-key", min_interval=0), fake


def test_live_client_uses_the_fixed_base_url_bearer_auth_and_get_only(monkeypatch: pytest.MonkeyPatch) -> None:
    client, fake = _client(
        monkeypatch,
        {
            "/account": [_fixture("account.json")],
            "/instances": [_fixture("instances.json")],
            "/firewall-rulesets": [_fixture("firewall_rulesets.json")],
            "/firewall-rulesets/global": [_fixture("global_firewall_ruleset.json")],
            "/ssh-keys": [_fixture("ssh_keys.json")],
            "/api-keys": [_fixture("api_keys.json")],
        },
    )

    rows = collect_lambda_cloud_evidence(client, collected_at=COLLECTED)

    assert len(rows) == 14
    for request in fake.requests:
        assert request.full_url.startswith("https://cloud.lambda.ai/api/v1/")
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == "Bearer synthetic-key"


def test_live_client_pages_instances_and_api_keys_by_page_token(monkeypatch: pytest.MonkeyPatch) -> None:
    instances = _fixture("instances.json")["data"]
    client, fake = _client(
        monkeypatch,
        {
            "/instances": [
                {"data": instances[:2], "page_token": "next-1"},
                {"data": instances[2:], "page_token": None},
            ]
        },
    )

    assert [row["id"] for row in client.instances()] == [row["id"] for row in instances]
    queries = [urllib.parse.parse_qs(urllib.parse.urlsplit(r.full_url).query) for r in fake.requests]
    assert queries == [
        {"page_size": [str(connectors_lambda.PAGE_SIZE)]},
        {"page_size": [str(connectors_lambda.PAGE_SIZE)], "page_token": ["next-1"]},
    ]


def test_live_client_rejects_a_repeated_page_token(monkeypatch: pytest.MonkeyPatch) -> None:
    page = {"data": [], "page_token": "same"}
    client, _ = _client(monkeypatch, {"/api-keys": [page, dict(page), dict(page)]})
    with pytest.raises(RuntimeError, match="repeated pagination cursor"):
        client.key_records()


def test_live_client_retries_rate_limits_honoring_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    url = "https://cloud.lambda.ai/api/v1/account"
    client, fake = _client(
        monkeypatch, {"/account": [_http_error(url, 429, {"Retry-After": "2"}), {"data": {"id": "a"}}]}
    )
    monkeypatch.setattr("time.sleep", sleeps.append)

    assert client.account() == {"id": "a"}
    assert sleeps == [2.0]
    assert len(fake.requests) == 2


def test_live_client_turns_forbidden_optional_reads_into_gaps(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://cloud.lambda.ai/api/v1/api-keys"
    client, _ = _client(
        monkeypatch,
        {
            "/account": [_fixture("account.json")],
            "/instances": [_fixture("instances.json")],
            "/firewall-rulesets": [_fixture("firewall_rulesets.json")],
            "/firewall-rulesets/global": [_fixture("global_firewall_ruleset.json")],
            "/ssh-keys": [_fixture("ssh_keys.json")],
            "/api-keys": [_http_error(url, 403)],
        },
    )

    rows = collect_lambda_cloud_evidence(client, collected_at=COLLECTED)
    gaps = collection_gaps(rows)
    assert [(g["collection"], g["reason"]) for g in gaps] == [("api_keys", "permission_denied")]
    assert "/" not in gaps[0]["message"]


def test_live_client_fails_the_sync_when_instances_are_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://cloud.lambda.ai/api/v1/instances"
    client, _ = _client(monkeypatch, {"/account": [_fixture("account.json")], "/instances": [_http_error(url, 403)]})
    with pytest.raises(ConnectorAccessError) as excinfo:
        collect_lambda_cloud_evidence(client, collected_at=COLLECTED)
    assert "/" not in str(excinfo.value)


def test_live_client_rejects_an_invalid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://cloud.lambda.ai/api/v1/account"
    client, _ = _client(monkeypatch, {"/account": [_http_error(url, 401)]})
    with pytest.raises(ConnectorAccessError, match="API key"):
        client.account()


def test_live_client_paces_requests_to_the_documented_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLambda({"/api/v1/account": [{"data": {"id": "a"}}, {"data": {"id": "a"}}]})
    monkeypatch.setattr(netguard, "open_public", fake)
    sleeps: list[float] = []
    clock = iter([100.0, 100.2, 101.0])
    client = LambdaCloudClient(api_key="k", min_interval=1.0, sleep=sleeps.append, clock=lambda: next(clock))

    client.account()
    client.account()
    assert sleeps == [pytest.approx(0.8)]


# --- Runner wiring ---------------------------------------------------------------------


def test_sync_requires_an_api_key_for_live_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAMBDA_API_KEY", raising=False)
    append_config_event(tmp_path, connector_id="lambda-cloud", state="enabled", actor="alice")
    with pytest.raises(connector_runner.ConnectorSyncError, match="LAMBDA_API_KEY"):
        connector_runner.run_connector_sync(tmp_path, connector_id="lambda-cloud")


def test_fixture_sync_lands_synthetic_lambda_evidence(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="lambda-cloud", state="enabled", actor="alice")

    result = connector_runner.run_connector_sync(
        tmp_path, connector_id="lambda-cloud", fixture_dir=FIXTURE, materialize=False
    )

    assert result.result == "ok"
    assert result.evidence_count == 14
    rows = read_jsonl(tmp_path / connector_runner.CONNECTOR_RAW_FILE)
    assert validate_raw_events(rows) == []
    assert all(row["attributes"]["synthetic"] is True for row in rows)


def test_bound_rows_apply_to_their_safeguards_and_carry_only_crosswalk_tags() -> None:
    safeguards = _safeguards()
    rows = [row for row in _rows() if row.get("safeguard_ids")]
    assert len(rows) == 14
    for row in rows:
        for safeguard_id in row["safeguard_ids"]:
            definition = safeguards[safeguard_id]
            assert row["entity"]["asset_type"] in definition["asset_types"]
            crosswalk = {member["control_id"] for member in definition["satisfies"]}
            assert set(row["controls"]) <= crosswalk, set(row["controls"]) - crosswalk
