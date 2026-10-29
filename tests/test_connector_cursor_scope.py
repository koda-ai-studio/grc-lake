"""Incremental cursors belong to a saved scope and effective collection target."""

import pytest

from security_lakehouse import connector_runner as runner
from security_lakehouse.connector_state import append_config_event
from security_lakehouse.ingestion.watermark import read_watermark, write_watermark

CONNECTOR = "github-security"


def configure(lake, org, **kwargs):
    return append_config_event(
        lake,
        connector_id=CONNECTOR,
        state="enabled",
        actor="test",
        credentials=kwargs.get("credentials"),
        options={"org": org, **kwargs.get("options", {})},
    )


def event(at, index=0, partial=False):
    return {
        "event_id": f"event-{index}",
        "tenant_id": "example",
        "event_time": at,
        "source": "provider",
        "event_type": "configuration.status",
        "entity": {"id": f"asset-{index}", "type": "service"},
        "status": "observed",
        "controls": [],
        "evidence": {"ref": "provider://record/42", "collected_at": at},
        "attributes": {"collection_gap": True} if partial else {},
    }


def test_account_cursors_resume_independently_without_borrowing_legacy_state(tmp_path, monkeypatch):
    write_watermark(tmp_path, CONNECTOR, "2026-10-29T00:00:00Z")
    seen = []
    times = iter(["2026-10-20T00:00:00Z", "2026-10-19T00:00:00Z", "2026-10-21T00:00:00Z"])

    def collect(*args, **kwargs):
        seen.append(kwargs["since"])
        return [event(next(times), len(seen))]

    monkeypatch.setattr(runner, "_collect", collect)
    cursors = []
    for org in ["example-a", "example-b", "example-a"]:
        configure(tmp_path, org)
        cursors.append(runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, materialize=False).watermark_cursor)
    assert read_watermark(tmp_path, CONNECTOR) == "2026-10-29T00:00:00Z"
    assert seen == [None, None, "2026-10-20T00:00:00Z"]
    assert cursors == ["2026-10-20T00:00:00Z", "2026-10-19T00:00:00Z", "2026-10-21T00:00:00Z"]


@pytest.mark.parametrize("override", ["repo", "fixture_dir", "token_env", "credentials"])
def test_effective_collection_target_change_starts_without_a_cursor(tmp_path, monkeypatch, override):
    configure(tmp_path, "example-a")
    seen = []

    def collect(*args, **kwargs):
        seen.append(kwargs["since"])
        return [event("2026-10-20T00:00:00Z", len(seen))]

    monkeypatch.setattr(runner, "_collect", collect)
    runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, materialize=False)
    overrides = {override: "example-b"}
    if override == "credentials":
        configure(tmp_path, "example-a", credentials={"credential_ref": "env:OTHER_TOKEN"})
        overrides = {}
    runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, materialize=False, **overrides)
    assert seen == [None, None]


def test_schedule_change_keeps_cursor_and_partial_collection_holds_it(tmp_path, monkeypatch):
    configure(tmp_path, "example-a", options={"sync_schedule": "every 15m"})
    seen = []

    def collect(*args, **kwargs):
        seen.append(kwargs["since"])
        return [event("2026-10-20T00:00:00Z" if len(seen) == 1 else "2026-10-21T00:00:00Z", len(seen), len(seen) > 1)]

    monkeypatch.setattr(runner, "_collect", collect)
    first = runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, materialize=False)
    configure(tmp_path, "example-a", options={"sync_schedule": "every 1h"})
    second = runner.run_connector_sync(tmp_path, connector_id=CONNECTOR, materialize=False)
    assert seen == [None, first.watermark_cursor]
    assert second.watermark_cursor == first.watermark_cursor
