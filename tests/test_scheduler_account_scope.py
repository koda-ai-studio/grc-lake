"""A source account's scheduled attempt cannot consume another account's slot."""

from datetime import UTC, datetime, timedelta

import pytest

from security_lakehouse import connector_runner, scheduler
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.io import read_jsonl

CONNECTOR = "aws-posture"
NOW = datetime(2026, 10, 29, tzinfo=UTC)


@pytest.fixture(autouse=True)
def connector_schedule_only(monkeypatch):
    monkeypatch.setattr(scheduler, "_scheduled_lake_eval", lambda lake: None)


def configure(lake, account="example-a", *, credentials=None, **options):
    return append_config_event(
        lake,
        connector_id=CONNECTOR,
        state="enabled",
        actor="test",
        credentials=credentials,
        options={"account": account, "sync_schedule": "every 1h", "split_ingest_eval": False, **options},
    )


def fire(lake, minutes, runner=None):
    return scheduler.tick(lake, now=NOW + timedelta(minutes=minutes), connector_runner=runner)


def test_new_account_runs_immediately_and_each_account_retains_its_cadence(tmp_path, monkeypatch):
    accounts = []

    def collect(*args, **kwargs):
        account = kwargs["options"]["account"]
        accounts.append(account)
        return [
            {
                "event_id": "provider-event",
                "tenant_id": account,
                "source": "aws",
                "event_time": "2026-10-29T00:00:00Z",
                "event_type": "configuration.status",
                "entity": {"id": "asset-1", "type": "service"},
                "status": "observed",
                "controls": [],
                "evidence": {"ref": "provider://record/1", "collected_at": "2026-10-29T00:00:00Z"},
            }
        ]

    monkeypatch.setattr(connector_runner, "_collect", collect)
    configure(tmp_path)
    assert fire(tmp_path, 0)[0]["result"] == "ok"
    configure(tmp_path, "example-b")
    assert fire(tmp_path, 1)[0]["result"] == "ok"
    assert fire(tmp_path, 2) == []
    assert {row["source_account_id"] for row in read_jsonl(tmp_path / "silver/normalized_events.jsonl")} == {
        "example-b"
    }
    assert (tmp_path / "gold/ccf_assessment.json").is_file()
    configure(tmp_path)
    assert fire(tmp_path, 3) == []
    assert fire(tmp_path, 60)[0]["result"] == "ok"
    assert accounts == ["example-a", "example-b", "example-a"]


@pytest.mark.parametrize("changed", ["repo", "fixture_dir", "token_env", "credentials"])
def test_collection_target_change_gets_its_own_attempt(tmp_path, changed):
    calls = []

    def run(*args, **kwargs):
        calls.append(kwargs)
        return {"result": "ok"}

    configure(tmp_path)
    fire(tmp_path, 0, run)
    updates = {changed: "example-b"}
    if changed == "credentials":
        updates = {"credentials": {"credential_ref": "env:OTHER_SOURCE"}}
    configure(tmp_path, **updates)
    assert len(fire(tmp_path, 1, run)) == 1
    assert fire(tmp_path, 2, run) == []
    assert len(calls) == 2


def test_schedule_edit_retains_attempt_time(tmp_path):
    configure(tmp_path)
    fire(tmp_path, 0, lambda *a, **kw: {"result": "ok"})
    configure(tmp_path, sync_schedule="every 2h")
    assert fire(tmp_path, 1, lambda *a, **kw: pytest.fail("schedule edit replayed collection")) == []
    assert fire(tmp_path, 60, lambda *a, **kw: pytest.fail("new interval ignored")) == []
    assert len(fire(tmp_path, 120, lambda *a, **kw: {"result": "ok"})) == 1


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_failed_or_interrupted_scope_stays_bounded_without_blocking_another(tmp_path, failure):
    configure(tmp_path)

    def fail(*args, **kwargs):
        raise failure("private provider text")

    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            fire(tmp_path, 0, fail)
    else:
        assert fire(tmp_path, 0, fail)[0]["result"] == "error"
    assert fire(tmp_path, 1, fail) == []
    configure(tmp_path, "example-b")
    assert len(fire(tmp_path, 2, lambda *a, **kw: {"result": "ok"})) == 1
    configure(tmp_path)
    assert fire(tmp_path, 3, fail) == []
    assert "private provider text" not in (tmp_path / "gold" / scheduler.STATE_FILE).read_text()


def test_legacy_attempt_keeps_its_interval_before_scoped_migration(tmp_path):
    configure(tmp_path)
    scheduler._write_state(tmp_path, target_kind="connector", target_id=CONNECTOR, fired_at=NOW, result="started")
    assert fire(tmp_path, 1, lambda *a, **kw: pytest.fail("legacy interrupted attempt replayed")) == []
    assert len(fire(tmp_path, 60, lambda *a, **kw: {"result": "ok"})) == 1
    configure(tmp_path, "example-b")
    assert len(fire(tmp_path, 61, lambda *a, **kw: {"result": "ok"})) == 1
    rows = read_jsonl(tmp_path / "gold" / scheduler.STATE_FILE)
    assert rows[0]["target_id"] == CONNECTOR
    assert len({row["target_id"] for row in rows}) == 3
    assert {row["connector_id"] for row in rows} == {CONNECTOR}


def test_distributed_attempt_keys_match_file_state_and_restore_scope_cadence(tmp_path, monkeypatch):
    from security_lakehouse.distributed import schedules

    durable = {}
    monkeypatch.setattr(schedules, "read_state", lambda: dict(durable))
    monkeypatch.setattr(schedules, "record_attempt", lambda kind, target, at: durable.update({f"{kind}:{target}": at}))
    configure(tmp_path)
    assert len(fire(tmp_path, 0, lambda *a, **kw: {"result": "ok"})) == 1
    rows = read_jsonl(tmp_path / "gold" / scheduler.STATE_FILE)
    assert set(durable) == {f"connector:{rows[-1]['target_id']}"}
    (tmp_path / "gold" / scheduler.STATE_FILE).unlink()
    assert fire(tmp_path, 1, lambda *a, **kw: pytest.fail("distributed attempt forgotten")) == []
    configure(tmp_path, "example-b")
    assert len(fire(tmp_path, 2, lambda *a, **kw: {"result": "ok"})) == 1
    assert len(durable) == 2
