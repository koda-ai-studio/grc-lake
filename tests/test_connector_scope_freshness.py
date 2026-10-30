"""Account changes must not inherit collection readiness from a different scope."""

from pathlib import Path

import pytest

from security_lakehouse import connector_runner, connector_state

CONNECTOR = "github-security"
FIXTURE = Path(__file__).parent / "fixtures" / "github-governance"


def configure(lake, org, connector=CONNECTOR):
    return connector_state.append_config_event(
        lake,
        connector_id=connector,
        state="enabled",
        actor="test",
        options={"org": org, "repo": f"{org}/model-service"},
    )


def view(lake, connector=CONNECTOR):
    return next(row for row in connector_state.build_catalog_view(lake) if row["connector_id"] == connector)


def sync(lake, fingerprint, result="ok"):
    return connector_state.append_run_event(
        lake,
        connector_id=CONNECTOR,
        kind="sync",
        result=result,
        access_fingerprint=fingerprint,
        evidence_count=7,
    )


def test_account_switch_requires_its_own_sync_but_preserves_history(tmp_path):
    first = configure(tmp_path, "example-a")
    old = sync(tmp_path, first["credential_fingerprint"])
    assert view(tmp_path)["freshness_state"] == "fresh"
    second = configure(tmp_path, "example-b")
    entry = view(tmp_path)
    assert entry["last_sync"] is None
    assert entry["last_successful_sync"] is None
    assert entry["freshness_state"] == "never_synced"
    assert connector_state.list_runs(tmp_path, CONNECTOR) == [old]
    current = sync(tmp_path, second["credential_fingerprint"])
    assert view(tmp_path)["last_successful_sync"] == current
    assert view(tmp_path)["freshness_state"] == "fresh"


def test_late_old_account_completion_cannot_hide_current_failure(tmp_path):
    first = configure(tmp_path, "example-a")
    second = configure(tmp_path, "example-b")
    current = sync(tmp_path, second["credential_fingerprint"])
    failure = sync(tmp_path, second["credential_fingerprint"], "error")
    sync(tmp_path, first["credential_fingerprint"])
    entry = view(tmp_path)
    assert entry["last_sync"] == failure
    assert entry["last_successful_sync"] == current


def test_unbound_legacy_sync_cannot_prove_configured_account_freshness(tmp_path):
    configure(tmp_path, "example-a")
    sync(tmp_path, None)
    assert view(tmp_path)["freshness_state"] == "never_synced"


@pytest.mark.parametrize("fail", [False, True])
def test_runner_records_starting_scope_even_when_config_changes(tmp_path, monkeypatch, fail):
    first = configure(tmp_path, "example-a")
    original = connector_runner._collect

    def collect(*args, **kwargs):
        configure(tmp_path, "example-b")
        if fail:
            raise ValueError("synthetic collection failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(connector_runner, "_collect", collect)
    with pytest.raises(connector_runner.ConnectorSyncError) as error:
        connector_runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, fixture_dir=FIXTURE)
    run = error.value.run
    assert not (tmp_path / "gold" / "ccf_assessment.json").exists()
    assert run["access_fingerprint"] == first["credential_fingerprint"]
    assert view(tmp_path)["last_sync"] is None


@pytest.mark.parametrize("collect_other", [False, True])
def test_returning_to_previous_account_requires_a_new_sync(tmp_path, collect_other):
    first = configure(tmp_path, "example-a")
    old = sync(tmp_path, first["credential_fingerprint"])
    second = configure(tmp_path, "example-b")
    if collect_other:
        sync(tmp_path, second["credential_fingerprint"])
    restored = configure(tmp_path, "example-a")
    assert restored["credential_fingerprint"] == first["credential_fingerprint"]
    entry = view(tmp_path)
    assert entry["last_sync"] is None
    assert entry["last_successful_sync"] is None
    assert entry["freshness_state"] == "never_synced"
    assert old in connector_state.list_runs(tmp_path, CONNECTOR)
    fresh = sync(tmp_path, restored["credential_fingerprint"])
    assert view(tmp_path)["last_successful_sync"] == fresh
    assert view(tmp_path)["freshness_state"] == "fresh"


def test_resaving_same_scope_and_changing_schedule_retains_freshness(tmp_path):
    first = configure(tmp_path, "example-a")
    collected = sync(tmp_path, first["credential_fingerprint"])
    configure(tmp_path, "example-a")
    connector_state.append_config_event(
        tmp_path,
        connector_id="aws-posture",
        state="enabled",
        actor="test",
        options={"account": "example-b"},
    )
    updated = connector_state.append_config_event(
        tmp_path,
        connector_id=CONNECTOR,
        state="enabled",
        actor="test",
        options={"org": "example-a", "repo": "example-a/model-service", "sync_schedule": "0 * * * *"},
    )
    assert updated["credential_fingerprint"] == first["credential_fingerprint"]
    assert view(tmp_path)["last_successful_sync"] == collected
    assert view(tmp_path)["freshness_state"] == "fresh"


def test_returning_to_account_cannot_claim_other_accounts_snapshot_is_fresh(tmp_path, monkeypatch):
    from security_lakehouse.io import read_jsonl

    def collect(*args, **kwargs):
        account = kwargs["options"]["org"]
        return [
            {
                "event_id": f"event-{account}",
                "tenant_id": account,
                "event_time": "2026-10-28T00:00:00Z",
                "source": "provider",
                "event_type": "configuration.status",
                "entity": {"id": "asset-1", "type": "service"},
                "status": "passed",
                "controls": [],
                "evidence": {"ref": "provider://record/42", "collected_at": "2026-10-28T00:00:00Z"},
            }
        ]

    monkeypatch.setattr(connector_runner, "_collect", collect)
    for account in ["example-a", "example-b"]:
        configure(tmp_path, account, "aws-posture")
        connector_runner.run_connector_sync(tmp_path, connector_id="aws-posture")
    assert {row["source_account_id"] for row in read_jsonl(tmp_path / "silver/normalized_events.jsonl")} == {
        "example-b"
    }
    assessment = (tmp_path / "gold/ccf_assessment.json").read_bytes()
    configure(tmp_path, "example-a", "aws-posture")
    assert view(tmp_path, "aws-posture")["freshness_state"] == "never_synced"
    assert (tmp_path / "gold/ccf_assessment.json").read_bytes() == assessment
    connector_runner.run_connector_sync(tmp_path, connector_id="aws-posture")
    assert view(tmp_path, "aws-posture")["freshness_state"] == "fresh"
    assert {row["source_account_id"] for row in read_jsonl(tmp_path / "silver/normalized_events.jsonl")} == {
        "example-a"
    }
