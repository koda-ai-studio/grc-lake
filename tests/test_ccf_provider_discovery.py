"""Discovered assets block assessment only in their observed provider scope."""

import pytest

from security_lakehouse.ccf_evaluation import evaluate_safeguards
from test_ccf_operational_assessment import normalized


def _evaluate(rows):
    frameworks = {"AWS": "aws-fixture", "GCP": "gcp-fixture", "ALL": "all-fixture"}
    return evaluate_safeguards(
        rows,
        {
            "review_log_verified": True,
            "safeguards": [
                {
                    "safeguard_id": "SG-0",
                    "title": "Access",
                    "asset_types": ["iam_role"],
                    "evaluation_rule": "fail_when_open_violation",
                    "satisfies": [
                        {"control_id": key, "framework_id": framework, "review_status": "reviewed"}
                        for key, framework in frameworks.items()
                    ],
                }
            ],
        },
        {key: {"framework_id": framework} for key, framework in frameworks.items()},
        provider_sources={"aws-fixture": ["aws"], "gcp-fixture": ["gcp"]},
    )


@pytest.mark.parametrize("gap_kind", ["unbound", "ambiguous", "invalid"])
@pytest.mark.parametrize("incomplete_source", ["aws", "gcp"])
def test_discovered_incomplete_assets_only_block_their_provider(gap_kind, incomplete_source):
    rows = [normalized(tenant_id="aws-account", source="aws"), normalized(tenant_id="gcp-account", source="gcp")]
    gap = normalized(
        "discovered", status="observed", bindings=[], tenant_id=f"{incomplete_source}-other", source=incomplete_source
    )
    if gap_kind == "ambiguous":
        rows.append({**gap, "asset_type": "repository", "event_id": "other-type"})
    elif gap_kind == "invalid":
        gap.update(asset_type="repository", safeguard_ids=["SG-0"])
    rows.append(gap)
    result = _evaluate(rows)
    statuses = {row["control_id"]: row["status"] for row in result["requirements"]}
    assert statuses == {
        "AWS": "not_evaluated" if incomplete_source == "aws" else "pass",
        "GCP": "not_evaluated" if incomplete_source == "gcp" else "pass",
        "ALL": "not_evaluated",
    }
    assert result["safeguards"][0]["status"] == "not_evaluated"
    assert result["population_completeness"] == "not_established"
    assert result["asset_count"] == 3


def test_incomplete_discovery_never_masks_failure_or_borrows_provider_evidence():
    rows = [
        normalized(tenant_id="aws-account", source="aws", status="open"),
        normalized("unbound", tenant_id="gcp-account", source="gcp", status="observed", bindings=[]),
    ]
    result = _evaluate(rows)
    assert {row["control_id"]: row["status"] for row in result["requirements"]} == {
        "AWS": "fail",
        "GCP": "not_evaluated",
        "ALL": "fail",
    }
