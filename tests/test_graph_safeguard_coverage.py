"""Safeguard inspection explains the frozen assessment without inventing coverage."""

import json
from pathlib import Path

from security_lakehouse.investigation_graph import investigation_graph


def _lake(path: Path, assessed: bool) -> Path:
    (path / "catalog").mkdir()
    (path / "gold").mkdir()
    (path / "catalog/safeguards.json").write_text(
        json.dumps(
            {
                "safeguards": [
                    {
                        "safeguard_id": "SG-TEST",
                        "title": "Synthetic safeguard",
                        "asset_types": ["host"],
                        "required_evidence_types": ["host.backup"],
                        "satisfies": [],
                    }
                ]
            }
        )
    )
    if assessed:
        (path / "gold/ccf_assessment.json").write_text(
            json.dumps(
                {
                    "safeguards": [
                        {
                            "safeguard_id": "SG-TEST",
                            "status": "not_evaluated",
                            "applicable_asset_count": 3,
                            "assessed_asset_count": 1,
                            "unassessed_asset_count": 2,
                            "invalid_binding_count": 1,
                        }
                    ]
                }
            )
        )
    return path


def test_graph_projects_frozen_safeguard_coverage(tmp_path: Path) -> None:
    result = investigation_graph(_lake(tmp_path, True), root="safeguard:SG-TEST")
    node = next(n for n in result["nodes"] if n["id"] == "safeguard:SG-TEST")
    assert node["status"] == "not_evaluated"
    assert node["required_evidence_types"] == ["host.backup"]
    assert node["applicable_asset_count"] == 3
    assert node["assessed_asset_count"] == 1
    assert node["unassessed_asset_count"] == 2
    assert node["invalid_binding_count"] == 1


def test_missing_assessment_does_not_invent_zero_coverage(tmp_path: Path) -> None:
    result = investigation_graph(_lake(tmp_path, False), root="safeguard:SG-TEST")
    node = next(n for n in result["nodes"] if n["id"] == "safeguard:SG-TEST")
    assert node["required_evidence_types"] == ["host.backup"]
    assert node["status"] == "not_evaluated"
    for field in ("applicable_asset_count", "assessed_asset_count", "unassessed_asset_count", "invalid_binding_count"):
        assert field not in node
