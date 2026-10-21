"""Run with Agent-Bom f95700c's Python environment to regenerate report.json.

GRC Lake's normal tests consume the JSON; they do not import Agent-Bom.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agent_bom.finding import Asset, Finding, FindingSource, FindingType
from agent_bom.models import AIBOMReport
from agent_bom.output.json_fmt import to_json

report = AIBOMReport(
    findings=[
        Finding(
            finding_type=FindingType.CVE,
            source=FindingSource.SBOM,
            asset=Asset(name="example-package", asset_type="package", identifier="pkg:pypi/example-package@1.0.0"),
            severity="high",
            cve_id="CVE-2099-0001",
            lifecycle_status="new",
        ),
        Finding(
            finding_type=FindingType.CIS_ERROR,
            source=FindingSource.CLOUD_CIS,
            asset=Asset(name="example-resource", asset_type="cloud_resource", identifier="example-resource"),
            severity="info",
        ),
    ],
    scan_id="00000000-0000-4000-8000-000000000001",
    generated_at=datetime(2026, 10, 21, 11, tzinfo=UTC),
    tool_version="0.0.0-fixture",
    scan_sources=["sbom"],
)
with (
    patch("socket.socket.connect", side_effect=AssertionError("fixture generation must stay offline")),
    patch("agent_bom.mitre_fetch.get_catalog_metadata", return_value={"source": "synthetic-fixture"}),
):
    payload = to_json(report)
# Keep the report envelope and full serialized findings; omit unrelated inventory/summary sections.
payload = {
    key: payload[key]
    for key in [
        "schema_version",
        "document_type",
        "scan_id",
        "ai_bom_version",
        "generated_at",
        "scan_run",
        "warnings",
        "findings",
    ]
}
Path(__file__).with_name("report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
