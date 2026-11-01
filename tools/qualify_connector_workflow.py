"""Retain an offline GitHub/Okta/Jira collection-to-export qualification receipt.

This exercises provider-shaped fixtures, not live access or cross-vendor identity
correlation. Collection is batched without sinks; the shared pipeline then
materializes all three sources into one local assessment generation.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path

from security_lakehouse.assessment import verify_snapshot_chain, write_assessment_snapshot
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, ConnectorSyncError, run_connector_sync
from security_lakehouse.connector_state import append_config_event, latest_run, list_runs
from security_lakehouse.dashboard import render_dashboard
from security_lakehouse.execution_mode import in_server_mode
from security_lakehouse.io import file_sha256, read_json, read_jsonl
from security_lakehouse.oscal import build_assessment_results
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.runtime_environment import runtime_env
from security_lakehouse.verification import verify_event, verify_lake_integrity

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"github-security": "github-governance", "okta-identity": "okta", "jira-ticketing": "jira"}
EXPECTED_COUNTS = {"github-repo-governance": 7, "okta": 8, "jira": 8}


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def collect(lake: Path, fixtures: Path, connector_id: str):
    return run_connector_sync(
        lake,
        connector_id=connector_id,
        repo="acme/model-service" if connector_id == "github-security" else None,
        fixture_dir=fixtures / SOURCES[connector_id],
        materialize=False,
        actor="synthetic-qualification",
    )


def _collect_receipt(lake: Path, fixtures: Path, connector_id: str) -> tuple[dict, bool]:
    before = list_runs(lake, connector_id)
    result = collect(lake, fixtures, connector_id)
    run = result.run
    metadata = run.get("metadata") or {}
    complete = (
        list_runs(lake, connector_id) == [run, *before]
        and run.get("connector_id") == connector_id
        and run.get("kind") == "sync"
        and run.get("result") == result.result == "ok"
        and not run.get("error")
        and not metadata.get("partial")
        and not metadata.get("coverage_gaps")
        and not result.coverage_gaps
        and run.get("evidence_count") == result.evidence_count
        and result.evidence_count
        == sum(row.get("connector_id") == connector_id for row in read_jsonl(lake / CONNECTOR_RAW_FILE))
    )
    return run, bool(complete)


def qualify(out: Path) -> dict:
    if in_server_mode() or runtime_env().get("GRC_LAKE_DATA_DIR"):
        raise ValueError("run qualification locally with repository catalogs and no hosted configuration")
    out.mkdir(parents=True, exist_ok=False)
    report: dict = {
        "schema_version": "grc_lake.connector_workflow_qualification.v1",
        "qualification_level": "synthetic_connector_workflow_only",
        "status": "error",
        "checks": {},
        "limitations": [
            "No live provider calls, permissions, pagination, capacity or availability qualification.",
            "No inferred cross-vendor identity joins or ticket-to-finding remediation links.",
            "Collection is batched without sinks; the shared pipeline performs local materialization.",
            "Recollection checks stable event identity and outcomes, not byte-identical observation timestamps.",
            "No control-effectiveness, mapping-review, certification or human-approval claim.",
        ],
    }
    try:
        report["source_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["source_tree_dirty"] = bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
        )
        report["runner_sha256"] = file_sha256(Path(__file__))
        fixtures = out / "inputs"
        for fixture in SOURCES.values():
            shutil.copytree(ROOT / "tests/fixtures" / fixture, fixtures / fixture)
        report["input_sha256"] = {
            str(path.relative_to(out)): file_sha256(path) for path in sorted(fixtures.rglob("*.json"))
        }
        lake = out / "lake"
        report["runs"] = []
        checks = report["checks"]
        checks["initial_runs_recorded"] = True
        for connector_id in SOURCES:
            append_config_event(lake, connector_id=connector_id, state="enabled", actor="synthetic-qualification")
            run, complete = _collect_receipt(lake, fixtures, connector_id)
            report["runs"].append(run)
            checks["initial_runs_recorded"] = checks["initial_runs_recorded"] and complete
        raw_path = lake / CONNECTOR_RAW_FILE
        rows = read_jsonl(raw_path)
        report["observed_counts"] = dict(Counter(row["source"] for row in rows))
        checks["expected_source_counts"] = report["observed_counts"] == EXPECTED_COUNTS
        ids = {row["event_id"] for row in rows}
        checks["distinct_event_ids"] = len(ids) == sum(EXPECTED_COUNTS.values())
        checks["synthetic_raw_records"] = bool(rows) and all(row["attributes"].get("synthetic") is True for row in rows)
        # Known fixture outcomes are independent of evaluator summaries. A closed
        # Jira issue must not erase a separate active identity deviation.
        statuses = {(row["event_type"], row["entity"]["asset_id"]): row["status"] for row in rows}
        expected_statuses = {
            ("okta.identity.mfa_enrollment", "okta:user:00u1mfaenrolled01"): "pass",
            ("okta.identity.mfa_enrollment", "okta:user:00u2nomfa00000002"): "open",
            ("okta.identity.mfa_enrollment", "okta:user:00u3deprovision03"): "observed",
            ("jira.workflow.ticket", "jira:issue:SEC-101"): "observed",
            ("jira.workflow.ticket", "jira:issue:SEC-102"): "open",
            ("repository.governance.change_approval", "github:repo:acme/model-service#default-branch"): "pass",
        }
        checks["fixture_outcomes_preserved"] = all(
            statuses.get(key) == value for key, value in expected_statuses.items()
        )
        run_pipeline(raw_path, lake, tenant_id="connector-qualification")
        silver = read_jsonl(lake / "silver/normalized_events.jsonl")
        checks["normalized_source_counts"] = dict(Counter(row["source"] for row in silver)) == EXPECTED_COUNTS
        posture = read_json(lake / "gold/current_posture.json")
        sources = {row["source"]: row for row in posture["evidence_freshness"]["sources"]}
        checks["provider_freshness_slos"] = all(
            sources.get(source, {}).get("connector_id") == connector
            and sources.get(source, {}).get("freshness_slo_minutes") == minutes
            for source, connector, minutes in (
                ("github-repo-governance", "github-security", 60),
                ("okta", "okta-identity", 60),
                ("jira", "jira-ticketing", 240),
            )
        )
        evaluated = {row["control_id"]: row["status"] for row in read_jsonl(lake / "gold/control_posture.jsonl")}
        checks["evaluated_deviations_retained"] = all(
            evaluated.get(cid) == "fail" for cid in ("SOC2-CC6.1", "SOC2-CC7.2")
        )
        checks["normalized_outcomes_preserved"] = {
            (row["event_type"], row["asset_id"]): row["status"] for row in silver
        } == statuses
        verification = {
            "lake": verify_lake_integrity(lake),
            "events": [verify_event(lake, row["event_id"]) for row in silver],
        }
        write_json(out / "verification.json", verification)
        checks["lake_integrity_verified"] = verification["lake"]["ok"] is True
        checks["raw_to_silver_hashes_verified"] = bool(silver) and all(
            row["verified"] for row in verification["events"]
        )
        snapshot = write_assessment_snapshot(lake, reason="Synthetic connector workflow qualification")
        snapshot_hash = file_sha256(snapshot)
        render_dashboard(lake, out / "evidence.html")
        oscal = build_assessment_results(lake, snapshot_id=snapshot.stem)
        write_json(out / "assessment-results.json", oscal)
        props = oscal["assessment-results"]["results"][0].get("props", [])
        checks["synthetic_exports_labeled"] = "synthetic demonstration" in (
            out / "evidence.html"
        ).read_text().lower() and any(
            prop["name"] == "trustops-synthetic-evidence" and prop["value"] == "true" for prop in props
        )
        # Recollect through every adapter, retaining both run events and the
        # original frozen snapshot. Observation times may legitimately advance.
        report["recollection_runs"] = []
        checks["recollection_runs_recorded"] = True
        for connector_id in SOURCES:
            run, complete = _collect_receipt(lake, fixtures, connector_id)
            report["recollection_runs"].append(run)
            checks["recollection_runs_recorded"] = checks["recollection_runs_recorded"] and complete
        replay = read_jsonl(raw_path)
        checks["replay_preserves_event_ids"] = len(replay) == len(rows) and {row["event_id"] for row in replay} == ids
        checks["replay_preserves_outcomes"] = {
            (row["event_type"], row["entity"]["asset_id"]): row["status"] for row in replay
        } == statuses
        run_pipeline(raw_path, lake, tenant_id="connector-qualification")
        checks["replay_integrity_verified"] = verify_lake_integrity(lake)["ok"] is True
        checks["snapshot_frozen_after_recollection"] = file_sha256(snapshot) == snapshot_hash
        checks["snapshot_chain_verified"] = verify_snapshot_chain(lake)["ok"] is True
        # Malformed provider-shaped input must not replace the last successful
        # combined inventory. Retain the failed input separately for inspection.
        broken = out / "failed-inputs"
        shutil.copytree(fixtures / "jira", broken / "jira")
        (broken / "jira/issues.json").write_text("{invalid-json\n")
        before_raw = file_sha256(raw_path)
        before_posture = file_sha256(lake / "gold/current_posture.json")
        failed_run = None
        try:
            collect(lake, broken, "jira-ticketing")
        except ConnectorSyncError:
            failed_run = latest_run(lake, "jira-ticketing", kind="sync")
            checks["failed_collection_recorded"] = bool(failed_run and failed_run["result"] == "error")
        else:
            checks["failed_collection_recorded"] = False
        checks["failed_collection_preserves_evidence"] = before_raw == file_sha256(
            raw_path
        ) and before_posture == file_sha256(lake / "gold/current_posture.json")
        report["failed_run"] = failed_run
        report["recovery_run"], checks["recovery_run_recorded"] = _collect_receipt(lake, fixtures, "jira-ticketing")
        recovered = read_jsonl(raw_path)
        checks["recovery_preserves_event_ids"] = (
            len(recovered) == len(rows) and {row["event_id"] for row in recovered} == ids
        )
        run_pipeline(raw_path, lake, tenant_id="connector-qualification")
        recovered_silver = read_jsonl(lake / "silver/normalized_events.jsonl")
        checks["recovery_preserves_outcomes"] = (
            len(recovered_silver) == len(silver)
            and {(row["event_type"], row["asset_id"]): row["status"] for row in recovered_silver} == statuses
            and {row["control_id"]: row["status"] for row in read_jsonl(lake / "gold/control_posture.jsonl")}
            == evaluated
        )
        checks["failed_run_retained_after_recovery"] = failed_run is not None and failed_run in list_runs(
            lake, "jira-ticketing"
        )
        checks["recovery_integrity_verified"] = verify_lake_integrity(lake)["ok"] is True
        checks["snapshot_frozen_after_recovery"] = file_sha256(snapshot) == snapshot_hash
        checks["recovery_snapshot_chain_verified"] = verify_snapshot_chain(lake)["ok"] is True
        report["artifacts_sha256"] = {
            name: file_sha256(out / name) for name in ("verification.json", "evidence.html", "assessment-results.json")
        }
        report["snapshot"] = {"path": str(snapshot.relative_to(out)), "sha256": snapshot_hash}
        report["status"] = "passed" if all(checks.values()) else "failed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        report.update(status="error", error_type=type(exc).__name__)
    write_json(out / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new output directory; prior attempts are retained")
    args = parser.parse_args(argv)
    if args.out.exists() or args.out.is_symlink():
        parser.error("choose a new output directory")
    try:
        report = qualify(args.out)
    except ValueError:
        parser.error("run locally; unset hosted mode and data-directory overrides")
    else:
        print(json.dumps({"status": report["status"], "report": str(args.out / "report.json")}))
        return 0 if report["status"] == "passed" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
