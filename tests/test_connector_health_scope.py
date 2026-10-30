"""Health and ingestion alerts must use success from the saved source account."""

from security_lakehouse import connector_runner as runner
from security_lakehouse.connector_health import build_connector_health
from security_lakehouse.connector_state import append_config_event, append_run_event, list_runs
from security_lakehouse.ingestion_status import build_ingestion_status

CONNECTOR = "aws-posture"


def configure(lake, account):
    return append_config_event(
        lake, connector_id=CONNECTOR, state="enabled", actor="test", options={"account": account}
    )


def success(lake, fingerprint):
    return append_run_event(
        lake, connector_id=CONNECTOR, kind="sync", result="ok", evidence_count=5, access_fingerprint=fingerprint
    )


def health(lake):
    return next(row for row in build_connector_health(lake)["connectors"] if row["connector_id"] == CONNECTOR)


def test_new_account_cannot_borrow_old_accounts_health(tmp_path):
    first = configure(tmp_path, "example-a")
    old = success(tmp_path, first["credential_fingerprint"])
    assert health(tmp_path)["health"] == "healthy"
    second = configure(tmp_path, "example-b")
    assert health(tmp_path)["health"] == "never_succeeded"
    assert health(tmp_path)["last_success_at"] is None
    status = build_ingestion_status(tmp_path)
    assert status["summary"]["silent_connectors"] == 1
    assert any(row["action"] == "investigate_silent_connectors" for row in status["recommended_actions"])
    assert old in list_runs(tmp_path, CONNECTOR)
    success(tmp_path, second["credential_fingerprint"])
    assert health(tmp_path)["health"] == "healthy"
    assert build_ingestion_status(tmp_path)["summary"]["silent_connectors"] == 0


def test_unbound_legacy_run_cannot_establish_configured_account_health(tmp_path):
    configure(tmp_path, "example-a")
    success(tmp_path, None)
    assert health(tmp_path)["health"] == "never_succeeded"


def test_late_other_account_success_cannot_replace_current_health_clock(tmp_path):
    first = configure(tmp_path, "example-a")
    second = configure(tmp_path, "example-b")
    current = success(tmp_path, second["credential_fingerprint"])
    for _ in range(55):
        append_run_event(
            tmp_path,
            connector_id=CONNECTOR,
            kind="sync",
            result="error",
            access_fingerprint=second["credential_fingerprint"],
        )
    success(tmp_path, first["credential_fingerprint"])
    assert health(tmp_path)["last_success_at"] == current["occurred_at"]


def test_real_collection_establishes_health_only_for_its_saved_account(tmp_path, monkeypatch):
    def collect(*args, **kwargs):
        account = kwargs["options"]["account"]
        return [
            {
                "event_id": "provider-event",
                "tenant_id": account,
                "event_time": "2026-10-29T00:00:00Z",
                "source": "aws",
                "event_type": "configuration.status",
                "entity": {"id": "asset-1", "type": "service"},
                "status": "observed",
                "controls": [],
                "evidence": {"ref": "provider://record/1", "collected_at": "2026-10-29T00:00:00Z"},
            }
        ]

    monkeypatch.setattr(runner, "_collect", collect)
    configure(tmp_path, "example-a")
    runner.run_connector_sync(tmp_path, connector_id=CONNECTOR)
    assert (tmp_path / "gold/ccf_assessment.json").is_file()
    assert health(tmp_path)["health"] == "healthy"
    configure(tmp_path, "example-b")
    assert health(tmp_path)["health"] == "never_succeeded"
    runner.run_connector_sync(tmp_path, connector_id=CONNECTOR)
    assert health(tmp_path)["health"] == "healthy"
