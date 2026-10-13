"""Byte-level stability of the golden pipeline's clock-independent artifacts.

These artifacts do not embed wall-clock time or lake paths, so their bytes are
a pure function of the golden fixture, the shipped catalog, and evaluation
logic. Refactors must leave them unchanged. When an evaluation or catalog
change is intended, regenerate the digests with ``--write``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from security_lakehouse.assessment import verify_snapshot_chain, write_assessment_snapshot
from security_lakehouse.fixtures import find_fixture
from security_lakehouse.golden_fixture import GOLDEN_COMPANY
from security_lakehouse.pipeline import run_pipeline

EXPECTED_SHA256 = {
    "gold/asset_risk.jsonl": "8169c0b42982e106eb9a446dda5f83242e9501617767452943339e43a8c791b7",
    "gold/ccf_assessment.json": "c0d116afc05903a73ffb8d186eb3826f02facb13729f5129cabfbe645a2e2566",
    "gold/control_posture.jsonl": "45ebfddf597bf80304d4801ecb4bd4c121461ec8145c70606d007ac16d32c196",
    "gold/metrics.json": "ec2fe66d18cefe0eb4e43bef657be37e75eb3096ef517d38abaed6c017b5b4a9",
    "silver/normalized_events.jsonl": "d1dfc24759f4bcf9cb9c8ad7fce34d8e96188bf95953cd5a6ccfce3188189efd",
}


def test_golden_pipeline_artifacts_are_byte_identical(tmp_path: Path) -> None:
    fixture = find_fixture(GOLDEN_COMPANY)
    assert fixture is not None
    lake = tmp_path / "lake"
    run_pipeline(fixture.raw_path, lake)

    actual = {rel: hashlib.sha256((lake / rel).read_bytes()).hexdigest() for rel in EXPECTED_SHA256}
    assert actual == EXPECTED_SHA256, json.dumps(actual, indent=2, sort_keys=True)

    # Catalog additions establish proposed coverage, never evidence or passes.
    assessment = json.loads((lake / "gold/ccf_assessment.json").read_text())
    requirements = {row["control_id"]: row for row in assessment["requirements"]}
    for control_id in ("NIST-800-171R3-03.09.01", "NIST-800-171R3-03.12.05"):
        assert requirements[control_id]["status"] == "not_evaluated"
        assert requirements[control_id]["pending_mapping_count"] == 1

    # Round-two catalog corrections retain context without granting coverage.
    pci = requirements["PCI-DSS-8"]
    assert pci["status"] == "unmapped"
    assert pci["pending_mapping_count"] == 0
    assert pci["contextual_mappings"] == [
        {"review_state": "proposed", "role": "supporting", "safeguard_id": "SG-IDENTITY-001"}
    ]
    gdpr = requirements["GDPR-Art.33"]
    assert gdpr["reviewed_safeguard_ids"] == []
    assert gdpr["pending_mapping_count"] == 1
    assert gdpr["contextual_mappings"] == [
        {
            "review_state": "maintainer_reviewed",
            "role": "supporting",
            "safeguard_id": "SG-INCIDENTRESPONSE-001",
        }
    ]

    write_assessment_snapshot(lake, reason="stability")
    write_assessment_snapshot(lake, reason="stability-2")
    chain = verify_snapshot_chain(lake)
    assert chain["ok"] is True, chain


if __name__ == "__main__":
    import argparse
    import re
    from tempfile import TemporaryDirectory

    parser = argparse.ArgumentParser(description="Regenerate golden pipeline stability digests")
    parser.add_argument("--write", action="store_true", required=True)
    parser.parse_args()
    fixture = find_fixture(GOLDEN_COMPANY)
    assert fixture is not None
    with TemporaryDirectory() as directory:
        lake = Path(directory) / "lake"
        run_pipeline(fixture.raw_path, lake)
        hashes = {rel: hashlib.sha256((lake / rel).read_bytes()).hexdigest() for rel in EXPECTED_SHA256}
    path = Path(__file__)
    path.write_text(
        re.sub(
            r"EXPECTED_SHA256 = \{.*?\n\}",
            "EXPECTED_SHA256 = " + json.dumps(hashes, indent=4, sort_keys=True),
            path.read_text(),
            count=1,
            flags=re.S,
        )
    )
