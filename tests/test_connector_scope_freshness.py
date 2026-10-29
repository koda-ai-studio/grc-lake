"""Account changes must not inherit collection readiness from a different scope."""

from pathlib import Path

import pytest

from security_lakehouse import connector_runner, connector_state

CONNECTOR = "github-security"
FIXTURE = Path(__file__).parent / "fixtures" / "github-governance"


def configure(lake, org):
    return connector_state.append_config_event(
        lake,
        connector_id=CONNECTOR,
        state="enabled",
        actor="test",
        options={"org": org, "repo": f"{org}/model-service"},
    )


def view(lake):
    return next(row for row in connector_state.build_catalog_view(lake) if row["connector_id"] == CONNECTOR)


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
    if fail:
        with pytest.raises(connector_runner.ConnectorSyncError) as error:
            connector_runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, fixture_dir=FIXTURE)
        run = error.value.run
    else:
        run = connector_runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, fixture_dir=FIXTURE).run
        assert (tmp_path / "gold" / "ccf_assessment.json").is_file()
    assert run["access_fingerprint"] == first["credential_fingerprint"]
    assert view(tmp_path)["last_sync"] is None
