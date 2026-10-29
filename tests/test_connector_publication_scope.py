"""In-flight reads cannot publish after their saved configuration is replaced."""

import subprocess
import sys

import pytest

from security_lakehouse import connector_runner as runner
from security_lakehouse.connector_state import append_config_event, build_catalog_view
from security_lakehouse.io import read_jsonl


def configure(lake, connector, account, state="enabled"):
    return append_config_event(lake, connector_id=connector, state=state, actor="test", options={"account": account})


def event(account):
    return {
        "event_id": f"event-{account}",
        "tenant_id": account,
        "event_time": "2026-10-28T00:00:00Z",
        "source": "provider",
        "event_type": "configuration.status",
        "entity": {"id": f"asset-{account}", "type": "service"},
        "status": "passed",
        "controls": [],
        "evidence": {"ref": "provider://record/42", "collected_at": "2026-10-28T00:00:00Z"},
    }


@pytest.mark.parametrize("connector", ["aws-posture", "okta-system-log"])
def test_late_account_run_preserves_current_raw_cursor_and_assessment(tmp_path, monkeypatch, connector):
    first = configure(tmp_path, connector, "example-a")
    published = {}
    fired = []
    monkeypatch.setattr(runner, "_fire_evidence_changed", lambda *args: fired.append(True))

    def collect(*args, **kwargs):
        account = kwargs["options"]["account"]
        if account == "example-a":
            configure(tmp_path, connector, "example-b")
            runner.run_connector_sync(tmp_path, connector_id=connector)
            published["raw"] = (tmp_path / runner.CONNECTOR_RAW_FILE).read_bytes()
            published["generation"] = (tmp_path / ".active-generation").resolve()
            published["assessment"] = (tmp_path / "gold/ccf_assessment.json").read_bytes()
            watermark = tmp_path / "gold/watermarks.jsonl"
            published["cursor"] = watermark.read_bytes() if watermark.exists() else None
        return [event(account)]

    monkeypatch.setattr(runner, "_collect", collect)
    with pytest.raises(runner.ConnectorSyncError, match="configuration changed") as error:
        runner.run_connector_sync(tmp_path, connector_id=connector)
    assert error.value.run["access_fingerprint"] == first["credential_fingerprint"]
    assert error.value.run["result"] == "error"
    assert (tmp_path / runner.CONNECTOR_RAW_FILE).read_bytes() == published["raw"]
    assert (tmp_path / ".active-generation").resolve() == published["generation"]
    assert (tmp_path / "gold/ccf_assessment.json").read_bytes() == published["assessment"]
    watermark = tmp_path / "gold/watermarks.jsonl"
    assert (watermark.read_bytes() if watermark.exists() else None) == published["cursor"]
    assert fired == [True]
    current = next(row for row in build_catalog_view(tmp_path) if row["connector_id"] == connector)
    assert current["freshness_state"] == "fresh"
    assert {row["tenant_id"] for row in read_jsonl(tmp_path / runner.CONNECTOR_RAW_FILE)} == {"example-b"}


@pytest.mark.parametrize("change", ["disable", "replace-and-restore"])
def test_configuration_revision_change_blocks_first_publication(tmp_path, monkeypatch, change):
    configure(tmp_path, "aws-posture", "example-a")

    def collect(*args, **kwargs):
        if change == "disable":
            configure(tmp_path, "aws-posture", "example-a", state="disabled")
        else:
            configure(tmp_path, "aws-posture", "example-b")
            configure(tmp_path, "aws-posture", "example-a")
        return [event("example-a")]

    monkeypatch.setattr(runner, "_collect", collect)
    with pytest.raises(runner.ConnectorSyncError, match="configuration changed"):
        runner.run_connector_sync(tmp_path, connector_id="aws-posture")
    assert not (tmp_path / runner.CONNECTOR_RAW_FILE).exists()
    assert not (tmp_path / ".active-generation").exists()


def test_configuration_lock_is_held_through_assessment_publication(tmp_path, monkeypatch):
    configure(tmp_path, "aws-posture", "example-a")
    monkeypatch.setattr(runner, "_collect", lambda *args, **kwargs: [event("example-a")])
    original = runner._materialize_after_sync

    def materialize(*args, **kwargs):
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sys
from pathlib import Path
from security_lakehouse.ledger import chain_lock
try:
    with chain_lock(Path(sys.argv[1]) / 'gold/connector_config.jsonl', blocking=False):
        print('acquired')
except BlockingIOError:
    print('blocked')
""",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        assert probe.stdout.strip() == "blocked"
        return original(*args, **kwargs)

    monkeypatch.setattr(runner, "_materialize_after_sync", materialize)
    result = runner.run_connector_sync(tmp_path, connector_id="aws-posture")
    assert result.result == "ok"
    configure(tmp_path, "aws-posture", "example-b")


def test_publication_ignores_stale_request_history(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from security_lakehouse.connector_state import connector_state_reader

    configure(tmp_path, "aws-posture", "example-a")

    def collect(*args, **kwargs):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(configure, tmp_path, "aws-posture", "example-b").result(timeout=10)
        return [event("example-a")]

    monkeypatch.setattr(runner, "_collect", collect)
    cached_request = connector_state_reader(runner.run_connector_sync)
    with pytest.raises(runner.ConnectorSyncError, match="configuration changed"):
        cached_request(tmp_path, connector_id="aws-posture")
    assert not (tmp_path / runner.CONNECTOR_RAW_FILE).exists()
