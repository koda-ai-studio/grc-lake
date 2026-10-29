"""Combined assessments cannot ignore an uncollected account of a bound provider."""

import pytest

from security_lakehouse.ccf_evaluation import evaluate_safeguards
from security_lakehouse.io import read_json, write_jsonl
from security_lakehouse.pipeline import run_pipeline
from test_assurance_truth import event
from test_ccf_operational_assessment import assessment, normalized


@pytest.mark.parametrize("status,expected", [("pass", "not_evaluated"), ("open", "fail")])
def test_other_account_gap_blocks_combined_pass_without_masking_failure(status, expected):
    rows = [
        normalized(status=status, tenant_id="source-a", source="aws"),
        normalized(
            "gap",
            status="not_evaluated",
            tenant_id="source-b",
            source="aws",
            asset_type="collection_scope",
            bindings=[],
        ),
    ]
    result = assessment(rows)
    assert result["safeguards"][0]["status"] == expected
    assert result["requirements"][0]["status"] == expected
    assert result["asset_results"][0]["source_tenant_id"] == "source-a"
    assert result["asset_results"][0]["status"] == ("pass" if status == "pass" else "fail")
    assert result["safeguards"][0]["assessed_asset_count"] == 1


def test_account_gap_does_not_block_an_unrelated_provider_benchmark():
    payload = {
        "review_log_verified": True,
        "safeguards": [
            {
                "safeguard_id": "SG-0",
                "title": "Access",
                "asset_types": ["iam_role"],
                "evaluation_rule": "fail_when_open_violation",
                "satisfies": [
                    {"control_id": key, "framework_id": framework, "review_status": "reviewed"}
                    for key, framework in [("AWS", "aws-fixture"), ("GCP", "gcp-fixture"), ("ALL", "all-fixture")]
                ],
            }
        ],
    }
    result = evaluate_safeguards(
        [
            normalized(tenant_id="aws-a", source="aws"),
            normalized(tenant_id="gcp-a", source="gcp"),
            normalized(
                "gap",
                status="not_evaluated",
                tenant_id="gcp-b",
                source="gcp",
                asset_type="collection_scope",
                bindings=[],
            ),
        ],
        payload,
        {
            key: {"framework_id": framework}
            for key, framework in [("AWS", "aws-fixture"), ("GCP", "gcp-fixture"), ("ALL", "all-fixture")]
        },
        provider_sources={"aws-fixture": ["aws"], "gcp-fixture": ["gcp"]},
    )
    assert {row["control_id"]: row["status"] for row in result["requirements"]} == {
        "AWS": "pass",
        "GCP": "not_evaluated",
        "ALL": "not_evaluated",
    }


def test_pipeline_preserves_account_asset_results_but_blocks_combined_safeguard(tmp_path):
    raw, lake = tmp_path / "raw.jsonl", tmp_path / "lake"
    good = {**event(), "tenant_id": "source-a", "source": "aws", "safeguard_ids": ["SG-IDENTITY-001"]}
    gap = {
        **event("not_evaluated"),
        "tenant_id": "source-b",
        "source": "aws",
        "event_id": "gap-b",
        "entity": {"asset_id": "collection-b", "asset_type": "collection_scope"},
        "controls": [],
        "attributes": {"collection_gap": True},
    }
    write_jsonl(raw, [good, gap])
    run_pipeline(raw, lake, tenant_id="platform-org")
    result = read_json(lake / "gold/ccf_assessment.json")
    safeguard = next(row for row in result["safeguards"] if row["safeguard_id"] == "SG-IDENTITY-001")
    assert safeguard["status"] == "not_evaluated"
    [asset] = [row for row in result["asset_results"] if row["safeguard_id"] == "SG-IDENTITY-001"]
    assert asset["source_tenant_id"] == "source-a"
    assert asset["status"] == "pass"
    assert result["population_completeness"] == "not_established"
