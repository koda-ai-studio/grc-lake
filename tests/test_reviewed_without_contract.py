"""A reviewed mapping on a safeguard with no evidence contract is disclosed, never counted as evaluable."""

import json
from copy import deepcopy

from security_lakehouse import framework_coverage, safeguards
from security_lakehouse.ccf_contracts import evidence_contract_inventory
from security_lakehouse.cli import main

REVIEWED = {
    "role": "primary",
    "review_status": "reviewed",
    "reviewed_by": "reviewer-fixture",
    "reviewed_at": "2026-10-14T00:00:00Z",
    "maintainer_review_ref": "controls/reviews/fixture.json",
}
PAYLOAD = {
    "schema": "trustops.safeguards.v1",
    "safeguards": [
        {
            "safeguard_id": "SG-TEST-CONTRACT",
            "title": "Access review with a contract",
            "risk_domain": "identity",
            "asset_types": ["iam_role"],
            "required_evidence_types": ["identity.access_review"],
            "evaluation_rule": "fail_when_open_violation",
            "satisfies": [{"control_id": "SOC2-CC6.1", "framework_id": "soc2", **REVIEWED}],
        },
        {
            "safeguard_id": "SG-TEST-FAMILY",
            "title": "Family safeguard without a contract",
            "risk_domain": "identity",
            "asset_types": ["iam_role", "identity_user"],
            "evaluation_rule": "fail_when_open_violation",
            "satisfies": [
                {"control_id": "SOC2-CC6.1", "framework_id": "soc2", **REVIEWED},
                {"control_id": "SOC2-CC6.2", "framework_id": "soc2", **REVIEWED},
                {"control_id": "SOC2-CC6.3", "framework_id": "soc2", "role": "primary", "review_status": "proposed"},
            ],
        },
    ],
}


def test_reviewed_requirement_is_without_contract_only_when_every_reviewed_safeguard_lacks_one() -> None:
    coverage = safeguards.coverage_by_framework(deepcopy(PAYLOAD))
    soc2 = coverage["frameworks"]["soc2"]
    assert soc2["reviewed"] == 2
    # CC6.1 is also reviewed through the contracted safeguard; CC6.2 is not.
    assert soc2["reviewed_without_contract"] == 1
    # The proposed CC6.3 mapping is not reviewed, so it is not reported here.
    assert coverage["reviewed_without_contract"] == 1
    assert coverage["safeguards_without_contract"] == 1
    assert coverage["reviewed_without_contract"] <= coverage["reviewed"]


def test_shipped_ledger_discloses_the_reviewed_requirements_that_cannot_be_evaluated() -> None:
    rows = framework_coverage.build_framework_coverage()
    summary = framework_coverage.framework_coverage_summary(rows)
    without = summary["reviewed_without_contract_requirement_count"]
    assert 0 < without <= summary["attestable_requirement_count"]
    assert summary["contractless_safeguard_count"] > 0
    by_id = {row["framework_id"]: row for row in rows}
    for row in rows:
        assert 0 <= row["reviewed_without_contract_requirement_count"] <= row["attestable_requirement_count"]
    # Audit finding of 2026-11-01: every reviewed DORA requirement sits only on
    # contract-less family safeguards. Pinned so the disclosure stays honest until
    # a maintainer re-review defines those contracts.
    dora = by_id["dora-2022-2554"]
    assert dora["reviewed_without_contract_requirement_count"] == dora["attestable_requirement_count"] > 0
    assert "contract" in framework_coverage.render_framework_coverage_markdown(rows, []).lower()


def test_evidence_contract_inventory_lists_each_contractless_safeguard_with_its_review_exposure() -> None:
    inventory = evidence_contract_inventory(deepcopy(PAYLOAD))
    assert inventory["summary"] == {
        "safeguards_without_contract": 1,
        "reviewed_requirements_without_contract": 1,
        "reviewed_mappings_without_contract": 2,
    }
    (entry,) = inventory["safeguards"]
    assert entry["safeguard_id"] == "SG-TEST-FAMILY"
    assert entry["asset_types"] == ["iam_role", "identity_user"]
    assert entry["reviewed_mappings"] == {"soc2": ["SOC2-CC6.1", "SOC2-CC6.2"]}
    assert entry["reviewed_requirements_without_contract"] == ["SOC2-CC6.2"]
    assert entry["maintainer_review_refs"] == ["controls/reviews/fixture.json"]
    assert "required_evidence_types" not in entry or entry["required_evidence_types"] in (None, [])
    assert inventory["proposes_contracts"] is False


def test_frameworks_contracts_command_prints_the_shipped_inventory(capsys) -> None:
    assert main(["frameworks", "contracts"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["safeguards_without_contract"] == len(payload["safeguards"]) > 0
    assert payload["proposes_contracts"] is False
    ids = [row["safeguard_id"] for row in payload["safeguards"]]
    assert ids == sorted(ids)
    assert all(row["maintainer_review_refs"] for row in payload["safeguards"] if row["reviewed_mappings"])
