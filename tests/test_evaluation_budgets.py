"""Resource admission fails before assessment publication and preserves evidence."""

import pytest

from security_lakehouse.generations import active_generation
from security_lakehouse.io import read_jsonl, write_jsonl
from security_lakehouse.pipeline import run_pipeline, run_pipeline_incremental
from test_assurance_truth import complete_events


@pytest.mark.parametrize("runner", [run_pipeline, run_pipeline_incremental])
def test_input_budget_rejects_new_work_without_replacing_generation(tmp_path, monkeypatch, runner):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, complete_events())
    run_pipeline(raw, lake)
    previous = active_generation(lake)
    monkeypatch.setenv("GRC_LAKE_EVALUATION_INPUT_BYTES", "1")
    with pytest.raises(ValueError, match="input byte budget"):
        runner(raw, lake)
    assert active_generation(lake) == previous


def test_source_account_alias_preserves_legacy_identity(tmp_path):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    write_jsonl(raw, complete_events())
    run_pipeline(raw, lake, tenant_id="platform-owner")
    rows = read_jsonl(lake / "silver/normalized_events.jsonl")
    assert all(r["source_account_id"] == r["tenant_id"] == "audit" for r in rows)


@pytest.mark.parametrize(
    "setting,value,match",
    [
        ("GRC_LAKE_EVALUATION_RELATIONS", "1", "relation budget"),
        ("GRC_LAKE_EVALUATION_INPUT_BYTES", "zero", "positive integer"),
        ("GRC_LAKE_EVALUATION_INPUT_BYTES", "0", "between"),
    ],
)
def test_admission_rejects_fanout_and_invalid_configuration(tmp_path, monkeypatch, setting, value, match):
    from security_lakehouse.evaluation_budget import bounded_raw_events

    raw = tmp_path / "raw.jsonl"
    write_jsonl(raw, [{"controls": ["A", "B"], "safeguard_ids": []}])
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError, match=match):
        list(bounded_raw_events(raw))


def test_identity_alias_disagreement_is_rejected():
    from security_lakehouse.domain_identity import source_asset_key

    with pytest.raises(ValueError, match="aliases disagree"):
        source_asset_key({"tenant_id": "a", "source_account_id": "b", "asset_id": "same"})
