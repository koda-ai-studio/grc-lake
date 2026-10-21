"""Identity and unknown facts must survive collection and derived projections."""

import sqlite3
from datetime import UTC, date, datetime

import pytest

from security_lakehouse.asset_names import load_asset_names, with_asset_names
from security_lakehouse.connector_runner import _upsert_raw_events
from security_lakehouse.connectors_aws import _stable_suffix
from security_lakehouse.connectors_okta import _user_event
from security_lakehouse.io import read_json, read_jsonl, write_jsonl
from security_lakehouse.offboarding import correlate_offboarding
from security_lakehouse.pipeline import normalize_raw_events, run_pipeline
from security_lakehouse.validation import validate_raw_events


def observation(event_id, account, *, asset="server-1", name="Server", owner="owner"):
    return {
        "event_id": event_id,
        "tenant_id": account,
        "event_time": "2026-10-21T12:00:00Z",
        "source": "provider",
        "event_type": "configuration.status",
        "entity": {"asset_id": asset, "asset_type": "server", "asset_name": name, "asset_owner": owner},
        "severity": "high",
        "status": "open",
        "controls": ["SOC2-CC6.1"],
        "evidence": {"ref": "provider://" + event_id},
    }


def test_account_scoped_assets_survive_pipeline_mart_names_and_replay(tmp_path):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(
        raw,
        [
            observation("a", "account-a", name="Alpha", owner="Alice"),
            observation("b", "account-b", name="Beta", owner="Bob"),
        ],
    )
    result = run_pipeline(raw, lake)
    assets = read_jsonl(lake / "gold/asset_risk.jsonl")
    assert len(assets) == 2
    assert {(r["source_account_id"], r["asset_name"], r["asset_owner"], r["event_count"]) for r in assets} == {
        ("account-a", "Alpha", "Alice", 1),
        ("account-b", "Beta", "Bob", 1),
    }
    with sqlite3.connect(result.mart_path) as conn:
        assert conn.execute(
            "SELECT source_account_id, asset_id, event_count FROM asset_risk ORDER BY source_account_id"
        ).fetchall() == [("account-a", "server-1", 1), ("account-b", "server-1", 1)]
    named = with_asset_names(read_jsonl(lake / "silver/normalized_events.jsonl"), load_asset_names(lake))
    assert {r["source_account_id"]: r["asset_name"] for r in named} == {"account-a": "Alpha", "account-b": "Beta"}
    violations = read_json(lake / "gold/current_posture.json")["violations"]
    assert {r["source_account_id"]: r["asset_name"] for r in violations} == {"account-a": "Alpha", "account-b": "Beta"}
    normalize_raw_events(raw, lake, incremental=True)
    assert read_jsonl(lake / "gold/asset_risk.jsonl") == assets


@pytest.mark.parametrize("entity", [{}, {"asset_id": " "}, {"asset_id": 123}, {"id": None}])
def test_unresolved_entity_cannot_publish_a_shared_unknown_asset(tmp_path, entity):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    row = observation("one", "account-a")
    write_jsonl(raw, [row])
    run_pipeline(raw, lake)
    previous = (lake / ".active-generation").readlink()
    row["entity"] = entity
    assert any("entity" in e for e in validate_raw_events([row]))
    write_jsonl(raw, [row])
    with pytest.raises(ValueError, match="entity"):
        normalize_raw_events(raw, lake, incremental=True)
    assert (lake / ".active-generation").readlink() == previous


def test_lossy_connector_ids_do_not_merge_distinct_resources(tmp_path):
    path = tmp_path / "raw.jsonl"
    for name in ("ops+prod", "ops=prod"):
        event_id = _stable_suffix(account="123456789012", signal="iam-user", asset_id=name, dedupe_key=name)
        _upsert_raw_events(
            path, [observation(event_id, "123456789012", asset=name)], connector_id="aws", write_mode="append"
        )
    assert len(read_jsonl(path)) == 2


def test_unknown_okta_lifecycle_is_not_proof_of_deprovisioning():
    now = datetime(2026, 10, 21, tzinfo=UTC)
    account = _user_event(
        "https://example.okta.com",
        "example.okta.com",
        {"id": "u1", "profile": {"login": "person@example.test"}},
        now,
        "account-a",
    )
    hr = {
        "event_type": "hris.personnel.employment",
        "source": "hr",
        "entity": {"asset_id": "person-1"},
        "attributes": {"work_email": "person@example.test", "termination_date": "2026-10-01"},
    }
    [finding] = correlate_offboarding([hr, account], as_of=date(2026, 10, 21), collected_at=now)
    assert finding["status"] == "not_evaluated"
    assert finding["attributes"]["outcome"] == "account_state_unknown"


@pytest.mark.parametrize("authentication", [None, "false", 0])
def test_unknown_account_state_does_not_count_as_disabled(authentication):
    now = datetime(2026, 10, 21, tzinfo=UTC)
    hr = {
        "event_type": "hris.personnel.employment",
        "entity": {"asset_id": "person-1"},
        "attributes": {"work_email": "person@example.test", "termination_date": "2026-10-01"},
    }
    account = {
        "event_type": "okta.identity.user_access",
        "entity": {"asset_id": "u1"},
        "attributes": {"login": "person@example.test", "can_authenticate": authentication},
    }
    [finding] = correlate_offboarding([hr, account], as_of=date(2026, 10, 21), collected_at=now)
    assert finding["status"] == "not_evaluated"


@pytest.mark.parametrize(
    "left,right",
    [("a+b", "a=b"), ("a/b", "a-b"), ("User", "user"), ("a%2bb", "a+b"), ("x" * 100 + "A", "x" * 100 + "a")],
)
def test_connector_encoding_preserves_distinct_source_identifiers(left, right):
    from security_lakehouse.connector_ids import stable_id_slug

    assert stable_id_slug(left, fallback="x") != stable_id_slug(right, fallback="x")


def test_warehouse_projections_keep_source_scope(tmp_path):
    from security_lakehouse.sinks import clickhouse_sink, duckdb_sink, snowflake_sink

    write_jsonl(
        tmp_path / "gold/asset_risk.jsonl",
        [
            {"asset_id": "same", "source_account_id": account, "latest_event_time": "2026-10-21T12:00:00Z"}
            for account in ("one", "two")
        ],
    )
    for module in (clickhouse_sink, duckdb_sink, snowflake_sink):
        spec = next(s for s in module.TABLE_SPECS if s.table.lower() == "asset_risk")
        assert spec.key == ("tenant_id", "source_account_id", "asset_id")
        rows = module.rows_for_spec(spec, tmp_path)
        values = [
            r["source_account_id"] if isinstance(r, dict) else r[spec.columns.index("source_account_id")] for r in rows
        ]
        assert values == ["one", "two"]


def test_confirmed_active_account_still_fails_when_another_account_is_unknown():
    now = datetime(2026, 10, 21, tzinfo=UTC)
    hr = {
        "event_type": "hris.personnel.employment",
        "entity": {"asset_id": "person-1"},
        "attributes": {"work_email": "person@example.test", "termination_date": "2026-10-01"},
    }
    accounts = [
        {
            "event_type": "okta.identity.user_access",
            "entity": {"asset_id": f"u{i}"},
            "attributes": {"login": "person@example.test", "can_authenticate": value},
        }
        for i, value in enumerate([True, None])
    ]
    [finding] = correlate_offboarding([hr, *accounts], as_of=date(2026, 10, 21), collected_at=now)
    assert finding["status"] == "open"
    assert finding["attributes"]["outcome"] == "active_after_termination"


def test_source_account_names_never_fall_back_to_an_unscoped_alias():
    rows = [{"source_account_id": "a", "asset_id": "same"}, {"source_account_id": "b", "asset_id": "same"}]
    assert with_asset_names(rows, {"same": "Ambiguous legacy name"}) == rows


def test_scoped_duckdb_export_preserves_both_assets_on_replay(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from security_lakehouse.sinks.duckdb_sink import DuckDBSink, DuckDBSinkConfig

    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, [observation("a", "account-a"), observation("b", "account-b")])
    run_pipeline(raw, lake)
    database = tmp_path / "destination.duckdb"
    sink = DuckDBSink(DuckDBSinkConfig(database=str(database)))
    assert sink.load(lake)["asset_risk"] == 2
    assert sink.load(lake)["asset_risk"] == 2
    with duckdb.connect(str(database)) as conn:
        assert conn.execute("SELECT source_account_id FROM asset_risk ORDER BY source_account_id").fetchall() == [
            ("account-a",),
            ("account-b",),
        ]


def test_legacy_duckdb_destination_requires_explicit_rebuild_without_data_loss(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from security_lakehouse.sinks.duckdb_sink import DuckDBSink, DuckDBSinkConfig

    database = tmp_path / "legacy.duckdb"
    lake = tmp_path / "lake"
    lake.mkdir()
    for relative in ("silver/normalized_events.jsonl", "gold/control_posture.jsonl", "gold/asset_risk.jsonl"):
        write_jsonl(lake / relative, [])
    with duckdb.connect(str(database)) as conn:
        DuckDBSink._claim_owner(conn, lake)
        conn.execute("CREATE TABLE asset_risk (tenant_id VARCHAR, asset_id VARCHAR)")
        conn.execute("INSERT INTO asset_risk VALUES ('owner', 'retained')")
    with pytest.raises(ValueError, match="legacy asset_risk.*new.*destination"):
        DuckDBSink(DuckDBSinkConfig(database=str(database))).load(lake)
    with duckdb.connect(str(database)) as conn:
        assert conn.execute("SELECT * FROM asset_risk").fetchall() == [("owner", "retained")]


def test_hr_and_derived_offboarding_ids_preserve_distinct_employees():
    from security_lakehouse.hris import EmploymentRecord, employment_event

    now = datetime(2026, 10, 21, tzinfo=UTC)
    rows = [
        employment_event(
            EmploymentRecord(identity, None, "person@example.test", None, None, "2026-10-01", None, None),
            vendor="hr",
            org="example",
            evidence_ref="hr://record",
            collected_at=now,
            tenant_id="account-a",
        )
        for identity in ("ops+prod", "ops=prod", "employee" * 20 + "one", "employee" * 20 + "two")
    ]
    assert len({row["event_id"] for row in rows}) == 4
    account = {
        "event_type": "okta.identity.user_access",
        "entity": {"asset_id": "u1"},
        "attributes": {"login": "person@example.test", "can_authenticate": True},
    }
    derived = correlate_offboarding([*rows, account], as_of=now.date(), collected_at=now)
    assert len({row["event_id"] for row in derived}) == 4


def test_offboarding_observations_keep_the_hr_source_account():
    now = datetime(2026, 10, 21, tzinfo=UTC)
    hr = [
        {
            "tenant_id": account,
            "event_type": "hris.personnel.employment",
            "entity": {"asset_id": "same"},
            "attributes": {"work_email": "person@example.test", "termination_date": "2026-10-01"},
        }
        for account in ("hr-a", "hr-b")
    ]
    idp = {
        "event_type": "okta.identity.user_access",
        "entity": {"asset_id": "u1"},
        "attributes": {"login": "person@example.test", "can_authenticate": True},
    }
    rows = correlate_offboarding([*hr, idp], as_of=now.date(), collected_at=now)
    assert {row["tenant_id"] for row in rows} == {"hr-a", "hr-b"}
    assert len({row["event_id"] for row in rows}) == 2


def test_snapshot_refresh_replaces_lossy_ids_and_keeps_historical_evidence(tmp_path):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    legacy = observation("123:iam-user:ops-prod", "123", asset="ops+prod")
    _upsert_raw_events(raw, [legacy], connector_id="aws", write_mode="snapshot")
    _upsert_raw_events(raw, [observation("other", "other-account")], connector_id="other", write_mode="append")
    run_pipeline(raw, lake)
    previous = (lake / ".active-generation").resolve()
    before = (previous / "silver/normalized_events.jsonl").read_bytes()
    fresh = [
        observation(
            _stable_suffix(account="123", signal="iam-user", asset_id=asset, dedupe_key=asset), "123", asset=asset
        )
        for asset in ("ops+prod", "ops=prod")
    ]
    _upsert_raw_events(raw, fresh, connector_id="aws", write_mode="snapshot")
    normalize_raw_events(raw, lake, incremental=True)
    current = read_jsonl(lake / "silver/normalized_events.jsonl")
    assert len(current) == 3
    assert {r["asset_id"] for r in current if r["connector_id"] == "aws"} == {"ops+prod", "ops=prod"}
    assert all(r["source_event_id"] != legacy["event_id"] for r in current)
    assert (previous / "silver/normalized_events.jsonl").read_bytes() == before
