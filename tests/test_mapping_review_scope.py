"""Review packets select mappings without inventing approval or independence."""

from copy import deepcopy

import pytest

from security_lakehouse.mapping_review_packet import build_review_packet
from security_lakehouse.safeguards import coverage_by_framework, load_safeguards

TARGETS = ["SOC2-CC8.1", "ISO27001-A.8.32"]


def test_explicit_safeguard_selection_includes_pending_alternatives_without_extra_coverage():
    payload = deepcopy(load_safeguards())
    for entry in payload["safeguards"]:
        if entry["safeguard_id"] == "SG-CHANGEMANAGEMENT-001":
            for member in entry["satisfies"]:
                if member["control_id"] in TARGETS:
                    member["review_status"] = "reviewed"
    before = coverage_by_framework(payload)
    packet = build_review_packet(payload=payload, control_ids=TARGETS, safeguard_ids=["SG-CHANGEAPPROVAL-001"])
    rows = [r for b in packet["batches"] for r in b["requirements"]]
    assert {r["control_id"] for r in rows} == set(TARGETS)
    assert {c["safeguard_id"] for r in rows for c in r["candidates"]} == {"SG-CHANGEAPPROVAL-001"}
    assert all(c["decision"] is c["reviewer"] is c["rationale"] is None for r in rows for c in r["candidates"])
    assert packet["summary"]["reviewed_requirements"] == before["reviewed"]
    assert packet["summary"]["additional_coverage_candidates"] == 0
    assert all(r["requirement"]["source_url"].startswith("https://") for r in rows)
    assert coverage_by_framework(payload) == before


@pytest.mark.parametrize(
    "controls,safeguards",
    [
        (TARGETS, []),
        (TARGETS, ["missing"]),
        (TARGETS, ["SG-CHANGEAPPROVAL-001", "missing"]),
        (["SOC2-CC6.1"], ["SG-CHANGEAPPROVAL-001"]),
    ],
)
def test_unavailable_mapping_selections_fail_without_silent_omission(controls, safeguards):
    with pytest.raises(ValueError):
        build_review_packet(control_ids=controls, safeguard_ids=safeguards)


def test_cli_can_prepare_exact_change_approval_candidates(tmp_path):
    import json

    from security_lakehouse.cli import main

    out = tmp_path / "packet.json"
    assert (
        main(
            [
                "frameworks",
                "review",
                "packet",
                "--safeguard",
                "SG-CHANGEAPPROVAL-001",
                "--control",
                TARGETS[0],
                "--control",
                TARGETS[1],
                "--out",
                str(out),
            ]
        )
        == 0
    )
    packet = json.loads(out.read_text())
    assert packet["safeguard_filter"] == ["SG-CHANGEAPPROVAL-001"]


def test_coverage_counts_recorded_reviewers_without_claiming_independence():
    coverage = coverage_by_framework()
    reviewers = coverage["reviewer_provenance"]
    assert reviewers["multiple_reviewers"] == 0
    assert reviewers["by_reviewer"] == {"msaad00": reviewers["single_reviewer"]}
    assert sum(reviewers["by_receipt"].values()) == reviewers["single_reviewer"]
    assert reviewers["unattributed"] + reviewers["single_reviewer"] == coverage["maintainer_reviewed_mappings"]
    assert reviewers["independence"] == "not_established"


def test_same_name_does_not_count_twice_and_stale_or_rejected_reviews_do_not_count():
    payload = deepcopy(load_safeguards())
    entry = next(e for e in payload["safeguards"] if e["satisfies"][0].get("maintainer_review_ref"))
    member = entry["satisfies"][0]
    entry["satisfies"] = [member]
    payload["safeguards"] = [entry]
    member["reviewed_by"] = "reviewer-a"
    member["org_review"] = {"decision": "approve", "reviewer": "reviewer-a"}
    assert coverage_by_framework(payload)["reviewer_provenance"]["single_reviewer"] == 1
    member["org_review"]["reviewer"] = "reviewer-b"
    provenance = coverage_by_framework(payload)["reviewer_provenance"]
    assert provenance["multiple_reviewers"] == 1
    assert provenance["by_reviewer"] == {"reviewer-a": 1, "reviewer-b": 1}
    assert provenance["independence"] == "not_established"
    member["effective_review_state"] = "rejected"
    assert coverage_by_framework(payload)["reviewer_provenance"]["by_reviewer"] == {}
    member.pop("effective_review_state")
    member["current_control_version"] = "stale"
    assert coverage_by_framework(payload)["reviewer_provenance"]["by_reviewer"] == {}
