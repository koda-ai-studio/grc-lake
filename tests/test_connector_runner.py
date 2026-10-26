"""Connector sync runner tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from security_lakehouse.cli import main
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.io import read_jsonl
from security_lakehouse.validation import validate_raw_events

FIXTURE = Path(__file__).parent / "fixtures" / "github-governance"


def test_connector_sync_requires_enabled_connector(tmp_path: Path) -> None:
    with pytest.raises(ConnectorSyncError, match="not enabled") as exc:
        run_connector_sync(
            tmp_path,
            connector_id="github-security",
            repo="acme/model-service",
            fixture_dir=FIXTURE,
        )
    assert exc.value.run["result"] == "error"
    assert latest_run(tmp_path, "github-security", kind="sync")["result"] == "error"


def test_connector_sync_persists_sanitized_error_not_raw_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="alice")

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("connection to host 10.0.0.5 failed: /etc/secret/key unreadable")

    monkeypatch.setattr(
        "security_lakehouse.connector_runner._collect",
        boom,
    )
    with pytest.raises(ConnectorSyncError):
        run_connector_sync(
            tmp_path,
            connector_id="github-security",
            repo="acme/model-service",
            fixture_dir=FIXTURE,
        )
    run = latest_run(tmp_path, "github-security", kind="sync")
    assert run["error"] == "ValueError"
    persisted = (tmp_path / "gold" / "connector_runs.jsonl").read_text(encoding="utf-8")
    assert "/etc/secret/key" not in persisted
    assert "10.0.0.5" not in persisted


def test_github_connector_sync_writes_raw_and_materializes_lake(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="alice")
    result = run_connector_sync(
        tmp_path,
        connector_id="github-security",
        repo="acme/model-service",
        fixture_dir=FIXTURE,
    )
    assert result.result == "ok"
    assert result.evidence_count == 7
    assert result.materialized is True

    raw_rows = read_jsonl(tmp_path / CONNECTOR_RAW_FILE)
    assert validate_raw_events(raw_rows) == []
    assert len(raw_rows) == 7
    assert (tmp_path / "bronze" / "raw_events.jsonl").is_file()
    assert (tmp_path / "silver" / "normalized_events.jsonl").is_file()
    assert (tmp_path / "gold" / "current_posture.json").is_file()

    run = latest_run(tmp_path, "github-security", kind="sync")
    assert run["result"] == "ok"
    assert run["evidence_count"] == 7


def test_connector_sync_upserts_stable_event_ids(tmp_path: Path) -> None:
    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="alice")
    first = run_connector_sync(tmp_path, connector_id="github-security", repo="acme/model-service", fixture_dir=FIXTURE)
    second = run_connector_sync(
        tmp_path,
        connector_id="github-security",
        repo="acme/model-service",
        fixture_dir=FIXTURE,
        materialize=False,
    )
    assert first.evidence_count == second.evidence_count == 7
    assert len(read_jsonl(tmp_path / CONNECTOR_RAW_FILE)) == 7


def test_connector_sync_cli_runs_fixture_connector(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    credentials = json.dumps({"token": "fixture-read-token"})
    # The probe reads the same fixture the sync collects from.
    options = json.dumps({"repo": "acme/model-service", "fixture_dir": str(FIXTURE)})
    probe = main(
        [
            "connectors",
            "probe",
            "--lake",
            str(tmp_path),
            "--connector-id",
            "github-security",
            "--credentials-json",
            credentials,
            "--options-json",
            options,
        ]
    )
    assert probe == 0
    capsys.readouterr()
    configure = main(
        [
            "connectors",
            "configure",
            "--lake",
            str(tmp_path),
            "--connector-id",
            "github-security",
            "--state",
            "enabled",
            "--credentials-json",
            credentials,
            "--options-json",
            options,
        ]
    )
    assert configure == 0
    capsys.readouterr()
    code = main(
        [
            "connectors",
            "sync",
            "--lake",
            str(tmp_path),
            "--connector-id",
            "github-security",
            "--repo",
            "acme/model-service",
            "--fixture-dir",
            str(FIXTURE),
            "--no-materialize",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["connector_id"] == "github-security"
    assert payload["evidence_count"] == 7
    assert payload["materialized"] is False
    assert len(read_jsonl(tmp_path / CONNECTOR_RAW_FILE)) == 7


def test_connector_configure_cli_persists_schedule_options(tmp_path: Path, capsys, github_probe_ok) -> None:  # type: ignore[no-untyped-def]
    credentials = json.dumps({"token": "fixture-read-token"})
    options = json.dumps({"org": "acme", "repo": "acme/model-service"})
    assert (
        main(
            [
                "connectors",
                "probe",
                "--lake",
                str(tmp_path),
                "--connector-id",
                "github-security",
                "--credentials-json",
                credentials,
                "--options-json",
                options,
            ]
        )
        == 0
    )
    capsys.readouterr()
    code = main(
        [
            "connectors",
            "configure",
            "--lake",
            str(tmp_path),
            "--connector-id",
            "github-security",
            "--state",
            "enabled",
            "--credentials-json",
            credentials,
            "--options-json",
            options,
            "--sync-schedule",
            "every 15m",
            "--repo",
            "acme/model-service",
            "--fixture-dir",
            str(FIXTURE),
            "--token-env",
            "GH_READ_TOKEN",
            "--no-materialize",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    options = payload["event"]["options"]
    assert options == {
        "eval_schedule": "every 6h",
        "fixture_dir": str(FIXTURE),
        "materialize": False,
        "org": "acme",
        "repo": "acme/model-service",
        "split_ingest_eval": True,
        "sync_schedule": "every 15m",
        "token_env": "GH_READ_TOKEN",
    }


def test_connector_configure_cli_rejects_enable_without_probe(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(
        [
            "connectors",
            "configure",
            "--lake",
            str(tmp_path),
            "--connector-id",
            "github-security",
            "--state",
            "enabled",
            "--credentials-json",
            json.dumps({"token": "fixture-read-token"}),
            "--options-json",
            json.dumps({"repo": "acme/model-service"}),
        ]
    )

    assert code == 1
    assert "Test connection" in capsys.readouterr().err


def test_connector_configure_cli_requires_matching_probe(tmp_path: Path, capsys, github_probe_ok) -> None:  # type: ignore[no-untyped-def]
    assert (
        main(
            [
                "connectors",
                "probe",
                "--lake",
                str(tmp_path),
                "--connector-id",
                "github-security",
                "--credentials-json",
                json.dumps({"token": "fixture-read-token"}),
                "--options-json",
                json.dumps({"repo": "acme/model-service"}),
            ]
        )
        == 0
    )
    capsys.readouterr()

    code = main(
        [
            "connectors",
            "configure",
            "--lake",
            str(tmp_path),
            "--connector-id",
            "github-security",
            "--state",
            "enabled",
            "--credentials-json",
            json.dumps({"token": "rotated-token"}),
            "--options-json",
            json.dumps({"repo": "acme/model-service"}),
        ]
    )

    assert code == 1
    assert "exact credentials" in capsys.readouterr().err


def test_incomplete_collection_keeps_raw_watermark_and_published_view(tmp_path, monkeypatch):
    from security_lakehouse.ingestion.paginate import paginate
    from security_lakehouse.ingestion.watermark import read_watermark, write_watermark

    append_config_event(tmp_path, connector_id="github-security", state="enabled", actor="alice")
    run_connector_sync(tmp_path, connector_id="github-security", repo="acme/model-service", fixture_dir=FIXTURE)
    raw_before = (tmp_path / CONNECTOR_RAW_FILE).read_bytes()
    posture_before = (tmp_path / "gold/current_posture.json").read_bytes()
    write_watermark(tmp_path, "github-security", "previous")

    def incomplete(*args, **kwargs):
        return list(paginate(lambda c: {}, lambda p: [{"partial": True}], lambda p: "secret-cursor", max_pages=1))

    monkeypatch.setattr("security_lakehouse.connector_runner._collect", incomplete)
    with pytest.raises(ConnectorSyncError) as caught:
        run_connector_sync(tmp_path, connector_id="github-security")
    assert caught.value.run["result"] == "error"
    assert caught.value.run["error"] == "IncompleteCollectionError"
    assert "secret-cursor" not in str(caught.value)
    assert read_watermark(tmp_path, "github-security") == "previous"
    assert (tmp_path / CONNECTOR_RAW_FILE).read_bytes() == raw_before
    assert (tmp_path / "gold/current_posture.json").read_bytes() == posture_before
