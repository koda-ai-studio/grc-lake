"""Named connections preserve any number of account snapshots independently."""

import pytest

from security_lakehouse import connections
from security_lakehouse import connector_runner as runner
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_jsonl


def event(account, version="1"):
    return {
        "event_id": "event-1",
        "tenant_id": account,
        "source": "aws",
        "event_time": "2026-10-30T00:00:00Z",
        "event_type": "configuration.status",
        "entity": {"id": "resource-1", "type": "service"},
        "status": "observed",
        "controls": [],
        "evidence": {"ref": f"provider://record/{version}", "collected_at": "2026-10-30T00:00:00Z"},
    }


def prepare(lake, name, account):
    connections.create_connection(
        lake, connection_id=name, connector_id="aws-posture", source_account_id=account, name=name
    )
    path, info = connections.connection_context(lake, name)
    append_config_event(
        path, connector_id=info["connector_id"], state="enabled", actor="test", options={"account": account}
    )
    return path


@pytest.mark.parametrize("count", [3, 7])
def test_arbitrary_accounts_survive_independent_snapshot_refresh(tmp_path, monkeypatch, count):
    for i in range(count):
        prepare(tmp_path, f"connection-{i}", f"account-{i}")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event(kw["options"]["account"])])
    for i in range(count):
        connections.sync_connection(tmp_path, f"connection-{i}", materialize=False)
    connections.evaluate_connections(tmp_path)
    rows = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assert {r["source_account_id"] for r in rows} == {f"account-{i}" for i in range(count)}
    assert len({r["event_id"] for r in rows}) == count
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [])
    connections.sync_connection(tmp_path, "connection-1", materialize=True)
    rows = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assets = [r for r in rows if r["asset_type"] != "collection_scope"]
    assert {r["source_account_id"] for r in assets} == {f"account-{i}" for i in range(count) if i != 1}
    assert (tmp_path / "gold/ccf_assessment.json").is_file()


def test_wrong_account_cannot_replace_snapshot_or_advance_run(tmp_path, monkeypatch):
    child = prepare(tmp_path, "production", "account-a")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("account-a")])
    connections.sync_connection(tmp_path, "production", materialize=False)
    before = (child / runner.CONNECTOR_RAW_FILE).read_bytes()
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("account-b")])
    with pytest.raises(runner.ConnectorSyncError):
        connections.sync_connection(tmp_path, "production", materialize=False)
    assert (child / runner.CONNECTOR_RAW_FILE).read_bytes() == before
    assert connections.list_connections(tmp_path)[0]["connector"]["last_sync"]["result"] == "error"


def test_connections_are_tenant_local_and_binding_is_immutable(tmp_path):
    prepare(tmp_path / "one", "production", "account-a")
    assert connections.list_connections(tmp_path / "two") == []
    with pytest.raises(ValueError):
        connections.create_connection(
            tmp_path / "one",
            connection_id="production",
            connector_id="aws-posture",
            source_account_id="account-b",
            name="replacement",
        )
    with pytest.raises(ValueError):
        prepare(tmp_path / "one", "duplicate", "account-a")


@pytest.mark.parametrize("name", ["../other", "/tmp/elsewhere", "a/b", "", ".hidden"])
def test_connection_ids_cannot_escape_the_lake(tmp_path, name):
    with pytest.raises(ValueError):
        prepare(tmp_path, name, "account")


def test_connection_directory_symlink_is_rejected(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    lake = tmp_path / "lake"
    lake.mkdir()
    (lake / "connections").symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError):
        prepare(lake, "production", "account")
    assert list(other.iterdir()) == []


def test_http_create_list_and_scoped_sync_do_not_touch_default_connector(tmp_path, monkeypatch):
    from security_lakehouse import api_v1
    from security_lakehouse.api_contract import required_post_scope

    status, body = api_v1.handle_post(
        "/api/v1/connections",
        {
            "connection_id": "production",
            "connector_id": "aws-posture",
            "source_account_id": "account-a",
            "name": "Production",
        },
        tmp_path,
    )
    assert status == 201
    child, _ = connections.connection_context(tmp_path, "production")
    append_config_event(child, connector_id="aws-posture", state="enabled", actor="test")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("account-a")])
    status, body = api_v1.handle_post("/api/v1/connections/production/sync", {"materialize": False}, tmp_path)
    assert status == 201
    assert body["data"]["connection_id"] == "production"
    assert required_post_scope("/api/v1/connections/production/sync") == "connector_manage"
    status, body = api_v1.handle_get("/api/v1/connections", {}, tmp_path)
    assert status == 200
    assert body["data"][0]["connection_id"] == "production"
    assert not (tmp_path / runner.CONNECTOR_RAW_FILE).exists()
    assert api_v1.handle_post("/api/v1/connections/../sync", {}, tmp_path)[0] == 400


def test_failed_account_is_a_gap_in_combined_evidence(tmp_path, monkeypatch):
    for account in ["a", "b", "c"]:
        prepare(tmp_path, account, account)
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event(kw["options"]["account"])])
    connections.sync_connection(tmp_path, "a", materialize=False)
    connections.sync_connection(tmp_path, "c", materialize=False)
    connections.evaluate_connections(tmp_path)
    rows = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assert any(row["source_account_id"] == "b" and row["status"] == "not_evaluated" for row in rows)


def test_catalog_health_and_scheduler_include_all_named_accounts(tmp_path, monkeypatch):
    from security_lakehouse.connector_health import build_connector_health
    from security_lakehouse.connector_state import build_catalog_view
    from security_lakehouse.scheduler import tick

    for name in ["a", "b", "c"]:
        child = prepare(tmp_path, name, name)
        append_config_event(
            child,
            connector_id="aws-posture",
            state="enabled",
            actor="test",
            options={"account": name, "sync_schedule": "every 1h"},
        )
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event(kw["options"]["account"])])
    views = [row for row in build_catalog_view(tmp_path) if row.get("connection_id")]
    assert {row["connection_id"] for row in views} == {"a", "b", "c"}
    runs = tick(tmp_path)
    assert {row["connection_id"] for row in runs if row.get("connection_id")} == {"a", "b", "c"}
    assert build_connector_health(tmp_path)["summary"]["healthy"] == 3
    assert tick(tmp_path) == []


def test_real_aws_accounts_are_preserved_through_collection_and_ccf(tmp_path):
    from pathlib import Path

    for number in range(3):
        account = f"00000000000{number}"
        child = prepare(tmp_path, f"aws-{number}", account)
        append_config_event(
            child, connector_id="aws-posture", state="enabled", actor="test", credentials={"account_id": account}
        )
        connections.sync_connection(
            tmp_path, f"aws-{number}", materialize=False, fixture_dir=Path(__file__).parent / "fixtures/aws"
        )
    assert connections.evaluate_connections(tmp_path).result == "ok"
    rows = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assert {row["source_account_id"] for row in rows} == {f"00000000000{i}" for i in range(3)}
    assert len(rows) == 21


def test_saved_access_change_blocks_old_account_evidence(tmp_path, monkeypatch):
    child = prepare(tmp_path, "prod", "a")
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("a")])
    connections.sync_connection(tmp_path, "prod", materialize=False)
    append_config_event(
        child,
        connector_id="aws-posture",
        state="enabled",
        actor="test",
        credentials={"account_id": "a", "role_arn": "changed"},
    )
    connections.evaluate_connections(tmp_path)
    rows = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assert any(row["asset_type"] == "collection_scope" and row["status"] == "not_evaluated" for row in rows)


def test_named_account_replaces_only_matching_legacy_account_in_evaluation(tmp_path, monkeypatch):
    from security_lakehouse.io import write_jsonl

    child = prepare(tmp_path, "prod", "a")
    legacy = [{**event(account), "connector_id": "aws-posture"} for account in ["a", "b"]]
    write_jsonl(tmp_path / runner.CONNECTOR_RAW_FILE, legacy)
    monkeypatch.setattr(runner, "_collect", lambda *a, **kw: [event("a", "new")])
    connections.sync_connection(tmp_path, "prod", materialize=True)
    rows = read_jsonl(tmp_path / "silver/normalized_events.jsonl")
    assert len(rows) == 2
    assert {row["source_account_id"] for row in rows} == {"a", "b"}
    assert (child / runner.CONNECTOR_RAW_FILE).is_file()
