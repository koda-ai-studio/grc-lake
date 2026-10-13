"""Source citation identity must agree across validation and read projections."""

import json
from copy import deepcopy

import pytest

from security_lakehouse import framework_coverage, framework_detail, mappings


def write_mappings(tmp_path, rows):
    path = tmp_path / "mappings.json"
    path.write_text(json.dumps({"mappings": rows}))
    return path


def record():
    return deepcopy(mappings.load_control_article_mappings()["SOC2-CC6.1"])


@pytest.mark.parametrize("kind", ["duplicate", "empty_id", "not_object", "articles_not_list", "article_not_object"])
def test_loader_rejects_ambiguous_or_malformed_records(tmp_path, kind):
    row = record()
    rows = [row]
    if kind == "duplicate":
        rows.append(deepcopy(row))
    elif kind == "empty_id":
        row["control_id"] = ""
    elif kind == "not_object":
        rows = [None]
    elif kind == "articles_not_list":
        row["articles"] = {"article_id": "X"}
    else:
        row["articles"] = [None]
    path = write_mappings(tmp_path, rows)
    with pytest.raises(ValueError, match="mapping"):
        mappings.load_control_article_mappings(path)
    assert mappings.validate_control_article_mappings(path)


@pytest.mark.parametrize("kind", ["unknown_control", "wrong_framework", "unknown_review_state"])
def test_validator_rejects_invalid_catalog_or_review_identity(tmp_path, kind):
    row = record()
    if kind == "unknown_control":
        row["control_id"] = "MISSING"
    elif kind == "wrong_framework":
        row["framework_id"] = "nist-csf-2.0"
    else:
        row["articles"][0]["review_status"] = "invented"
    assert mappings.validate_control_article_mappings(write_mappings(tmp_path, [row]))


@pytest.mark.parametrize("kind", ["wrong_framework", "no_articles"])
def test_coverage_crosswalk_and_detail_exclude_the_same_invalid_mapping(tmp_path, monkeypatch, kind):
    original = mappings.load_control_article_mappings()
    before = mappings.build_reviewed_crosswalk()
    before_count = next(row["mapping_count"] for row in before["matrix"] if row["framework_id"] == "soc2")
    changed = deepcopy(original)
    if kind == "wrong_framework":
        changed["SOC2-CC6.1"]["framework_id"] = "nist-csf-2.0"
    else:
        changed["SOC2-CC6.1"]["articles"] = []
    for module in (mappings, framework_coverage, framework_detail):
        monkeypatch.setattr(module, "load_control_article_mappings", lambda *args: changed)
    ledger = {row["framework_id"]: row for row in framework_coverage.build_framework_coverage()}
    crosswalk = {row["framework_id"]: row for row in mappings.build_reviewed_crosswalk()["matrix"]}
    from security_lakehouse.io import write_jsonl

    for relative in (
        "gold/control_posture.jsonl",
        "gold/control_tests.jsonl",
        "gold/evidence_freshness.jsonl",
        "silver/normalized_events.jsonl",
    ):
        write_jsonl(tmp_path / relative, [])
    detail = framework_detail.build_framework_detail("soc2", tmp_path)
    control = next(row for row in detail["controls"] if row["control_id"] == "SOC2-CC6.1")
    assert control["articles"] == []
    assert detail["summary"]["mapped_control_count"] == before_count - 1
    assert crosswalk["soc2"]["mapping_count"] == before_count - 1
    for framework_id, row in crosswalk.items():
        assert row["mapping_count"] == ledger[framework_id]["source_cited_mapping_count"]
    assert "SOC2-CC6.1" in ledger["soc2"]["missing_mapping_control_ids"]
    assert changed["SOC2-CC6.1"] != original["SOC2-CC6.1"]


def test_shipped_catalog_still_validates_and_preserves_proposed_attribution():
    assert mappings.validate_control_article_mappings() == []
    rows = mappings.load_control_article_mappings()
    proposed = [
        article for row in rows.values() for article in row["articles"] if article.get("review_status") == "proposed"
    ]
    assert proposed
    assert all(article.get("source_reconciled_by") and not article.get("reviewed_by") for article in proposed)
