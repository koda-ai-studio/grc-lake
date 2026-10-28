"""Source citation coverage must follow the catalog identity and explicit review state."""

import copy

import pytest

from security_lakehouse import framework_coverage
from security_lakehouse.mappings import article_mapping_reviewed, load_control_article_mappings


@pytest.mark.parametrize("state", ["rejected", "needs_changes", "unknown", "", None])
def test_unrecognized_source_review_states_do_not_count_as_reviewed(state):
    assert not article_mapping_reviewed({"articles": [{"article_id": "X", "review_status": state}]})


def test_legacy_source_review_state_requires_recorded_reviewer():
    attributed = {"article_id": "X", "reviewed_by": "maintainer", "reviewed_at": "2026-10-01"}
    assert article_mapping_reviewed({"articles": [attributed]})
    assert article_mapping_reviewed({"articles": [{"article_id": "X", "review_status": "reviewed"}]})
    assert not article_mapping_reviewed({"articles": [{"article_id": "X"}]})
    assert not article_mapping_reviewed({"articles": [{"article_id": "X", "reviewed_by": " "}]})


@pytest.mark.parametrize("mutation", ["wrong_framework", "no_articles"])
def test_invalid_citation_is_missing_not_credited_to_another_framework(monkeypatch, mutation):
    before = {r["framework_id"]: r for r in framework_coverage.build_framework_coverage()}
    mappings = copy.deepcopy(load_control_article_mappings())
    member = mappings["SOC2-CC6.1"]
    if mutation == "wrong_framework":
        member["framework_id"] = "nist-csf-2.0"
    else:
        member["articles"] = []
    monkeypatch.setattr(framework_coverage, "load_control_article_mappings", lambda _: mappings)
    after = {r["framework_id"]: r for r in framework_coverage.build_framework_coverage()}
    assert after["soc2"]["source_cited_mapping_count"] == before["soc2"]["source_cited_mapping_count"] - 1
    assert "SOC2-CC6.1" in after["soc2"]["missing_mapping_control_ids"]
    assert after["nist-csf-2.0"]["source_cited_mapping_count"] == before["nist-csf-2.0"]["source_cited_mapping_count"]
    for row in after.values():
        assert row["source_cited_mapping_count"] + row["missing_mapping_count"] == row["seeded_control_count"]
        assert row["reviewed_mapping_count"] <= row["source_cited_mapping_count"]
