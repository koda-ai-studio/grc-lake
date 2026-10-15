"""Review preparation cannot impersonate decisions or multiply coverage."""

from copy import deepcopy

import pytest

from security_lakehouse.mapping_review import list_decisions
from security_lakehouse.mapping_review_packet import build_review_packet
from security_lakehouse.safeguards import load_safeguards

# These tests exercise the original proposal state before the receipted review.
pytestmark = pytest.mark.usefixtures("proposed_source_catalog")


def test_packet_is_deterministic_read_only_and_deduplicates_requirements(tmp_path):
    first = build_review_packet(tmp_path)
    assert first == build_review_packet(tmp_path)
    assert list_decisions(tmp_path) == []
    assert not list(tmp_path.rglob("*"))
    rows = [row for batch in first["batches"] for row in batch["requirements"]]
    assert len(rows) == len({row["control_id"] for row in rows})
    assert len(rows) == first["summary"]["distinct_requirements_in_packet"]
    assert first["summary"]["reviewed_target"] == 1126
    assert first["summary"]["additional_reviewed_needed"] == 787
    assert all(c["decision"] is c["reviewer"] is c["rationale"] is None for row in rows for c in row["candidates"])
    assert all(c["review_basis_sha256"] for row in rows for c in row["candidates"])
    assert all(batch["requirement_count"] <= 25 for batch in first["batches"])


def test_framework_filter_does_not_change_the_global_milestone_denominator():
    packet = build_review_packet(framework_id="nist-csf-2.0", batch_size=20)
    rows = [row for batch in packet["batches"] for row in batch["requirements"]]
    assert len(rows) == 106
    assert {row["framework_id"] for row in rows} == {"nist-csf-2.0"}
    assert packet["summary"]["catalog_requirements"] == 2252


def test_missing_sources_are_visible_and_do_not_become_approved_or_verified():
    payload = deepcopy(load_safeguards())
    for entry in payload["safeguards"]:
        entry.pop("mapping_source", None)
        for member in entry["satisfies"]:
            member.pop("mapping_source", None)
    before = deepcopy(payload)
    packet = build_review_packet(payload=payload)
    assert packet["summary"]["requirements_with_source_references"] == 0
    assert packet["summary"]["reviewed_requirements"] == 339
    assert payload == before


def test_cli_packet_and_version_bound_decision_round_trip(tmp_path, capsys):
    import json

    from security_lakehouse.cli import main

    packet_path = tmp_path / "review.json"
    lake = tmp_path / "lake"
    assert main(["frameworks", "review", "packet", "--framework", "nist-csf-2.0", "--out", str(packet_path)]) == 0
    packet = json.loads(packet_path.read_text())
    item = packet["batches"][0]["requirements"][0]["candidates"][0]
    command = [
        "frameworks",
        "review",
        "needs-changes",
        "--lake",
        str(lake),
        "--safeguard",
        item["safeguard_id"],
        "--framework",
        item["framework_id"],
        "--control",
        item["control_id"],
        "--rationale",
        "Synthetic test requests explicit scope.",
        "--reviewer",
        "reviewer@example.test",
        "--review-basis",
        item["review_basis_sha256"],
        "--expected-decision-id",
        "none",
    ]
    assert main(command) == 0
    before = list_decisions(lake)
    assert len(before) == 1
    assert main(command) == 1
    assert "history changed" in capsys.readouterr().err
    assert list_decisions(lake) == before
    command[-1] = before[0]["decision_id"]
    assert main(command) == 0
    assert len(list_decisions(lake)) == 2


def test_invalid_batch_size_does_not_create_an_output(tmp_path):
    from security_lakehouse.cli import main

    out = tmp_path / "invalid.json"
    assert main(["frameworks", "review", "packet", "--batch-size", "0", "--out", str(out)]) == 1
    assert not out.exists()
