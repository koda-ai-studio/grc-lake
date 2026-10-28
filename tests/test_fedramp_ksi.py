"""A source-pinned KSI subset remains proposed through assessment and export."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from security_lakehouse.catalog import load_control_catalog, load_framework_registry
from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards, validate_safeguards
from test_ccf_operational_assessment import normalized

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = "fedramp-ksi-2026"
IDS = {"KSI-IAM-AAM", "KSI-IAM-APM"}


def entries():
    return [s for s in load_safeguards()["safeguards"] if s["safeguard_id"].startswith("SG-KSI-")]


def test_ksi_scope_is_source_pinned_and_separate_from_moderate():
    catalog = load_control_catalog()
    assert {cid for cid, row in catalog.items() if row["framework_id"] == FRAMEWORK} == IDS
    assert sum(row["framework_id"] == "fedramp-moderate" for row in catalog.values()) == 287
    registry = load_framework_registry()[FRAMEWORK]
    assert registry["version"] == "2026.10.13.01"
    assert "2 of 46" in registry["coverage_boundary"]
    assert validate_safeguards(load_safeguards()) == []
    coverage = coverage_by_framework(load_safeguards())["frameworks"][FRAMEWORK]
    assert (coverage["controls"], coverage["covered"], coverage["reviewed"]) == (2, 2, 0)
    assert len(entries()) == 2
    for row in entries():
        assert row["satisfies"][0]["review_status"] == "proposed"
        assert row["satisfies"][0]["control_version"] == "2026.10.13.01"
        assert row["reviewed_by"] is None


@pytest.mark.parametrize("case", ["pass", "failed", "observed", "unknown", "missing", "unbound", "wrong_type", "stale"])
def test_ksi_assessment_never_attests_a_proposed_mapping(case):
    catalog = load_control_catalog()
    assert entries()
    for safeguard in entries():
        cid = safeguard["satisfies"][0]["control_id"]
        row = normalized(
            asset_type="service",
            bindings=[] if case == "unbound" else [safeguard["safeguard_id"]],
            status=case if case in {"failed", "observed", "unknown"} else "pass",
            control_ids=[cid],
            evidence_types=["identity.mfa"] if case == "wrong_type" else safeguard["required_evidence_types"],
        )
        if case == "stale":
            row.update(event_time="2000-01-01T00:00:00Z", evidence_collected_at="2000-01-01T00:00:00Z")
        result = evaluate_safeguards(
            [] if case == "missing" else [row],
            {"review_log_verified": True, "safeguards": [safeguard]},
            {cid: catalog[cid]},
        )
        expected = {"pass": "pass", "failed": "fail", "wrong_type": "stale", "stale": "stale"}.get(
            case, "not_evaluated"
        )
        assert result["safeguards"][0]["status"] == expected
        assert result["requirements"][0]["status"] != "pass"


def test_source_replay_and_drift_fail_closed():
    from tools.sync_fedramp_ksi import PLAN, SOURCE, SOURCE_SCHEMA, build_entries, build_manifest, updated_payload

    plan = json.loads(PLAN.read_text())
    raw, schema = SOURCE.read_bytes(), SOURCE_SCHEMA.read_bytes()
    manifest = build_manifest(raw, schema, plan)
    assert manifest == json.loads((ROOT / "frameworks/packs/data/fedramp_ksi_2026.json").read_text())
    generated = build_entries(manifest, load_control_catalog())
    payload = json.loads((ROOT / "controls/safeguards.json").read_text())
    assert updated_payload(payload, generated) == payload
    with pytest.raises(ValueError, match="digest"):
        build_manifest(raw + b" ", schema, plan)
    with pytest.raises(ValueError, match="digest"):
        build_manifest(raw, schema + b" ", plan)
    changed = json.loads(raw)
    changed["info"]["version"] = "future-version"
    encoded = json.dumps(changed).encode()
    altered = deepcopy(plan)
    altered["source"]["sha256"] = hashlib.sha256(encoded).hexdigest()
    with pytest.raises(ValueError, match="version"):
        build_manifest(encoded, schema, altered)
    missing = deepcopy(plan)
    missing["rows"][0]["id"] = "KSI-IAM-NOTREAL"
    with pytest.raises(ValueError, match="unknown"):
        build_manifest(raw, schema, missing)
    duplicate = deepcopy(plan)
    duplicate["rows"][1] = duplicate["rows"][0]
    with pytest.raises(ValueError, match="distinct"):
        build_manifest(raw, schema, duplicate)
    changed_entries = deepcopy(generated)
    changed_entries[0]["objective"] = "Weaker obligation"
    with pytest.raises(ValueError, match="reconciliation"):
        updated_payload(payload, changed_entries)


def test_review_packet_is_deterministic_and_has_no_human_decision():
    from security_lakehouse.mapping_review_packet import build_review_packet

    packet = build_review_packet(framework_id=FRAMEWORK)
    assert packet == build_review_packet(framework_id=FRAMEWORK)
    assert packet == json.loads((ROOT / "docs/reviews/fedramp-ksi-packet.json").read_text())
    rows = [row for batch in packet["batches"] for row in batch["requirements"]]
    assert {r["control_id"] for r in rows} == IDS
    for row in rows:
        for candidate in row["candidates"]:
            assert candidate["decision"] is candidate["reviewer"] is candidate["rationale"] is None
            assert candidate["review_basis_sha256"]
    from security_lakehouse.graph import _framework_from_control

    assert all(_framework_from_control(cid) == FRAMEWORK for cid in IDS)


def test_ksi_fixture_exports_draft_without_framework_attestation(tmp_path):
    from security_lakehouse.audit_workpapers import build_workpaper, export_workpaper, verify_workpaper_export
    from security_lakehouse.io import canonical_sha256
    from security_lakehouse.oscal import build_assessment_results
    from security_lakehouse.pipeline import run_pipeline

    fixture = ROOT / "examples/fedramp-ksi"
    lake = tmp_path / "lake"
    run_pipeline(fixture / "events.jsonl", lake)
    assessment = json.loads((lake / "gold/ccf_assessment.json").read_text())
    requirements = [r for r in assessment["requirements"] if r["control_id"] in IDS]
    assert len(requirements) == 2
    assert all(r["status"] != "pass" for r in requirements)
    findings = build_assessment_results(lake)["assessment-results"]["results"][0]["findings"]
    assert len(findings) == 2
    assert all(f["target"]["status"]["state"] == "not-satisfied" for f in findings)
    plan = json.loads((fixture / "plan.json").read_text())
    baseline = json.loads((fixture / "baseline.json").read_text())
    content = build_workpaper(lake, plan=plan, baseline=baseline)
    assert content["narrative"]["status"] == "unreviewed"
    assert content["synthetic_fixture"] is True
    assert content["population"]["status"] != "complete"
    for control in content["assurance"]["controls"]:
        assert control["operating"]["status"] == "insufficient_evidence"
        assert control["operating"]["gaps"]
        assert all(m["effective_review_state"] == "proposed" for m in control["requirement_mappings"])
    export_workpaper(content, tmp_path / "bundle")
    verified = verify_workpaper_export(tmp_path / "bundle", expected_content_sha256=canonical_sha256(content))
    assert verified["ok"]
    assert "review identity requires server record" in verified["authentication"]


@pytest.mark.parametrize("case", ["pass", "unknown", "missing"])
def test_current_ksi_assertions_keep_unknown_and_missing_unattested_in_exports(tmp_path, case):
    from security_lakehouse.io import read_jsonl, write_jsonl
    from security_lakehouse.oscal import build_assessment_results
    from security_lakehouse.pipeline import run_pipeline
    from test_assurance_truth import event

    rows = []
    for cid in sorted(IDS):
        if case == "missing" and cid == "KSI-IAM-APM":
            continue
        rows.append(
            {
                **event("unknown" if case == "unknown" else "pass"),
                "event_id": cid,
                "event_type": cid.lower().replace("-", "_") + "_assessment",
                "entity": {"asset_id": "service-1", "asset_type": "service"},
                "controls": [cid],
                "safeguard_ids": ["SG-" + cid],
            }
        )
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, rows)
    run_pipeline(raw, lake, tenant_id="audit")
    posture = read_jsonl(lake / "gold/control_posture.jsonl")
    assert all(row["status"] == ("not_evaluated" if case == "unknown" else "pass") for row in posture)
    requirements = json.loads((lake / "gold/ccf_assessment.json").read_text())["requirements"]
    assert {r["control_id"]: r["status"] for r in requirements if r["control_id"] in IDS} == dict.fromkeys(
        IDS, "not_evaluated"
    )
    findings = build_assessment_results(lake)["assessment-results"]["results"][0]["findings"]
    assert len(findings) == len(rows)
    assert all(row["target"]["status"]["state"] == "not-satisfied" for row in findings)
