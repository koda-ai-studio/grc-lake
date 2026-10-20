"""Qualify synthetic access/change evidence through frozen workpaper exports.

No provider calls or review decisions. A passed case means the observed behavior
matched its explicit expectation, not that a control is effective or reviewed.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path

from security_lakehouse.assessment import verify_snapshot_chain, write_assessment_snapshot
from security_lakehouse.audit_workpapers import build_workpaper, export_workpaper, verify_workpaper_export
from security_lakehouse.execution_mode import in_server_mode
from security_lakehouse.io import canonical_sha256, file_sha256
from security_lakehouse.pipeline import run_pipeline
from security_lakehouse.runtime_environment import runtime_env

ROOT = Path(__file__).resolve().parents[1]
SAFEGUARDS = ("SG-IDENTITY-001", "SG-CHANGEMANAGEMENT-001")
# Expectations are defined independently of the evaluator under qualification.
SCENARIOS = {
    "complete_samples": ("sample_pass", "declared_scope_reconciled"),
    "observed_failure": ("sample_fail", "declared_scope_reconciled"),
    "conflicting_observations": ("sample_fail", "declared_scope_reconciled"),
    "missing_window": ("insufficient_evidence", "declared_scope_reconciled"),
    "out_of_period_sample": ("insufficient_evidence", "declared_scope_reconciled"),
    "observed_only": ("insufficient_evidence", "declared_scope_reconciled"),
    "unavailable_evidence": ("insufficient_evidence", "declared_scope_reconciled"),
    "partial_collection": ("sample_pass", "incomplete"),
    "missing_asset": ("insufficient_evidence", "incomplete"),
    "stale_collection": ("sample_pass", "incomplete"),
}


def write_json(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def case_inputs(safeguard: str, scenario: str) -> tuple[list[dict], dict, dict]:
    if safeguard not in SAFEGUARDS or scenario not in SCENARIOS:
        raise ValueError("unknown qualification case")
    fixtures = ROOT / "examples/control-assurance"
    plan = json.loads((fixtures / "plan.json").read_text())
    plan["tenant_id"] = "qualification"
    plan["controls"] = [row for row in plan["controls"] if row["safeguard_id"] == safeguard]
    events = [
        json.loads(line)
        for line in (fixtures / "events.jsonl").read_text().splitlines()
        if safeguard in json.loads(line)["safeguard_ids"]
    ]
    for row in events:
        row["status"] = "pass"
        row["severity"] = "info"
    baseline = json.loads((fixtures / "baseline.json").read_text())
    baseline["tenant_id"] = plan["tenant_id"]
    baseline["inventory"]["accounts"][0]["asset_ids"] = [events[0]["entity"]["asset_id"]]
    baseline["collections"][0]["asset_count"] = 1
    sample = next(row for row in events if row["event_id"].startswith("day2-"))
    if scenario == "observed_failure":
        sample["status"] = "fail"
    elif scenario == "conflicting_observations":
        conflicting = copy.deepcopy(sample)
        conflicting["event_id"] += "-conflict"
        conflicting["evidence"]["evidence_id"] = conflicting["event_id"]
        conflicting["status"] = "fail"
        events.append(conflicting)
    elif scenario == "missing_window":
        events.remove(sample)
    elif scenario == "out_of_period_sample":
        sample["event_time"] = sample["evidence"]["collected_at"] = "2025-12-30T00:00:00Z"
    elif scenario == "observed_only":
        sample["status"] = "observed"
    elif scenario == "unavailable_evidence":
        sample.pop("evidence")
    elif scenario == "partial_collection":
        baseline["collections"][0]["status"] = "partial"
        baseline["collections"][0]["cursor_exhausted"] = False
    elif scenario == "missing_asset":
        baseline["inventory"]["accounts"][0]["asset_ids"].append("synthetic-missing-asset")
    elif scenario == "stale_collection":
        baseline["collections"][0]["completed_at"] = "2025-12-01T00:00:00Z"
    return events, plan, baseline


def run_case(out: Path, safeguard: str, scenario: str) -> dict:
    if in_server_mode() or runtime_env().get("GRC_LAKE_DATA_DIR"):
        raise ValueError("run qualification locally with the repository catalogs and no hosted configuration")
    out.mkdir(parents=True, exist_ok=False)
    expected_operating, expected_population = SCENARIOS[scenario]
    result = {
        "safeguard_id": safeguard,
        "scenario": scenario,
        "expected": {"design": "documented", "operating": expected_operating, "population": expected_population},
        "status": "error",
        "checks": {},
    }
    try:
        events, plan, baseline = case_inputs(safeguard, scenario)
        raw = out / "events.jsonl"
        raw.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in events))
        write_json(out / "plan.json", plan)
        write_json(out / "baseline.json", baseline)
        result["input_sha256"] = {
            name: file_sha256(out / name) for name in ("events.jsonl", "plan.json", "baseline.json")
        }
        lake = out / "lake"
        run_pipeline(raw, lake, tenant_id=plan["tenant_id"])
        content = build_workpaper(lake, plan=plan, baseline=baseline)
        control = content["assurance"]["controls"][0]
        result["observed"] = {
            "design": control["design"]["status"],
            "operating": control["operating"]["status"],
            "population": content["population"]["status"],
        }
        result["content_sha256"] = canonical_sha256(content)
        result["generation"] = content["generation"]
        export_workpaper(content, out / "workpaper")
        checks = result["checks"]
        checks["expected_outcomes"] = result["observed"] == result["expected"]
        checks["export_verified"] = verify_workpaper_export(out / "workpaper")["ok"] is True
        checks["pinned_export_verified"] = (
            verify_workpaper_export(out / "workpaper", expected_content_sha256=result["content_sha256"])["ok"] is True
        )
        checks["same_generation_replay"] = content == build_workpaper(lake, plan=plan, baseline=baseline)
        checks["human_review_pending"] = (
            content["assurance"]["review_status"] == control["conclusion"] == "pending_human_review"
            and content["narrative"]["status"] == "unreviewed"
        )
        checks["scope_not_independently_verified"] = (
            content["population"]["inventory_completeness"] == "not_independently_verified"
        )
        checks["synthetic_label"] = content["synthetic_fixture"] is True
        checks["bound_evidence_hashes"] = bool(content["evidence"]) and all(
            row.get("raw_sha256") for row in content["evidence"].values()
        )
        write_assessment_snapshot(lake, reason="Synthetic workflow qualification")
        checks["snapshot_chain_verified"] = verify_snapshot_chain(lake)["ok"] is True
        foreign_plan = {**plan, "tenant_id": "foreign"}
        foreign_baseline = {**baseline, "tenant_id": "foreign"}
        try:
            build_workpaper(lake, plan=foreign_plan, baseline=foreign_baseline)
        except ValueError:
            checks["foreign_tenant_rejected"] = True
        else:
            checks["foreign_tenant_rejected"] = False
        # Retain the deliberately damaged copy separately from the reviewable export.
        export_workpaper(content, out / "tampered-workpaper")
        with (out / "tampered-workpaper/index.html").open("a") as stream:
            stream.write("\nSynthetic tamper probe\n")
        checks["tampered_export_rejected"] = verify_workpaper_export(out / "tampered-workpaper")["ok"] is False
        # A replacement can recompute its own manifest and HTML. Only the
        # original digest retained outside that replacement detects substitution.
        replacement = copy.deepcopy(content)
        replacement["narrative"]["text"] = "Synthetic replacement: the original narrative was removed."
        export_workpaper(replacement, out / "replacement-workpaper")
        checks["replacement_export_self_consistent"] = (
            verify_workpaper_export(out / "replacement-workpaper")["ok"] is True
        )
        receipt = verify_workpaper_export(
            out / "replacement-workpaper", expected_content_sha256=result["content_sha256"]
        )
        write_json(out / "handoff-verification.json", receipt)
        checks["replacement_export_rejected_by_pin"] = (
            receipt["ok"] is False
            and receipt["bundle_integrity_verified"] is True
            and receipt["expected_content_matches"] is False
        )
        result["status"] = "passed" if all(checks.values()) else "failed"
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # Exception messages may contain operator paths or credentials. Keep the type only.
        result.update(status="error", error_type=type(exc).__name__)
    write_json(out / "result.json", result)
    return result


def qualify(out: Path) -> dict:
    if in_server_mode() or runtime_env().get("GRC_LAKE_DATA_DIR"):
        raise ValueError("run qualification locally with the repository catalogs and no hosted configuration")
    out.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": "grc.control_workflow_qualification.v1",
        "qualification_level": "synthetic_workflow_only",
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "runner_sha256": file_sha256(Path(__file__)),
        "limitations": [
            "No live provider calls, pagination qualification, or provider accuracy measurement.",
            "Fixture outcomes do not establish control effectiveness, certification, or mapping approval.",
            "A passing sample set can coexist with incomplete population or collection evidence.",
            "Replay checks repeat workpaper construction from one generation, not a fresh collection.",
            "No human review decisions are written; existing mapping states are retained in each workpaper.",
        ],
        "cases": [],
    }
    for safeguard in SAFEGUARDS:
        for scenario in SCENARIOS:
            directory = f"{safeguard}/{scenario}"
            result = run_case(out / directory, safeguard, scenario)
            report["cases"].append({**result, "directory": directory})
    report["status"] = "passed" if all(row["status"] == "passed" for row in report["cases"]) else "failed"
    write_json(out / "report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new directory; retain prior attempts")
    args = parser.parse_args(argv)
    if args.out.exists() or args.out.is_symlink():
        parser.error("choose a new output directory; prior attempts must be retained")
    try:
        report = qualify(args.out)
    except ValueError:
        return parser.error("run locally with repository catalogs; unset hosted mode and data-directory overrides")
    else:
        print(
            json.dumps(
                {"status": report["status"], "cases": len(report["cases"]), "report": str(args.out / "report.json")}
            )
        )
        return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
