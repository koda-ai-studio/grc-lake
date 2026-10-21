"""Portable, generation-pinned CCF coverage diagnostics without new verdicts."""

from __future__ import annotations

import hashlib
import html
import json
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from security_lakehouse.ccf_gaps import requirement_gaps
from security_lakehouse.ccf_queries import read_summary
from security_lakehouse.evidence_provenance import contains_synthetic_evidence
from security_lakehouse.generations import assert_mutable, generation_identity, pin_generation, verify_generation
from security_lakehouse.io import read_json

_STATUSES = ("pass", "fail", "stale", "not_evaluated", "unmapped")
_BOUNDARY = (
    "Catalogued requirements are the frozen GRC Lake catalog, not a claim of complete normative coverage. "
    "Reviewed mappings are not proof of control operation. Results cover observed assets only; "
    "population completeness is not established. This report is not certification or an auditor opinion."
)
_ACTIONS = {
    "mapping_review_pending": "Review proposed implementation mappings.",
    "no_reviewed_implementation": "Establish and review an implementation mapping.",
    "context_only": "Review an implementation mapping; context alone is insufficient.",
    "review_log_unverified": "Verify the review ledger and publish a new assessment.",
    "safeguard_failed": "Inspect failing safeguard asset results and remediate the observed failures.",
    "safeguard_stale": "Refresh the relevant evidence and re-evaluate.",
    "safeguard_not_evaluated": "Inspect safeguard asset results for missing or inconclusive evidence.",
    "unassessed_assets": "Collect and assess evidence for the observed applicable assets.",
    "invalid_evidence_bindings": "Repair rejected evidence-to-safeguard bindings and re-evaluate.",
    "requirement_stale": "Inspect freshness details, refresh evidence and re-evaluate.",
    "assessment_detail_missing": "Inspect the assessment detail and re-evaluate if necessary.",
}


def summarize_coverage(
    assessment: dict[str, Any], controls: dict[str, Any], *, framework_ids: list[str] | None = None
) -> dict[str, Any]:
    """Use frozen requirement rows as denominators, retaining all unknown states."""
    requirements = assessment["requirements"]
    identifiers = [row["control_id"] for row in requirements]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate assessment requirement")
    if set(identifiers) != set(controls):
        raise ValueError("assessment requirements do not match the frozen catalog")
    for row in requirements:
        if (
            row["status"] not in _STATUSES
            or not row["framework_id"]
            or row["framework_id"] != controls[row["control_id"]].get("framework_id")
        ):
            raise ValueError("invalid assessment status or framework identity")
    available = {row["framework_id"] for row in requirements}
    selected = set(framework_ids) if framework_ids else available
    if not selected or not selected <= available:
        raise ValueError("requested framework is absent from the frozen assessment")
    rows = []
    for row in requirement_gaps(assessment):
        if row["framework_id"] in selected:
            rows.append(
                {
                    **row,
                    "title": str(controls[row["control_id"]].get("title") or row["control_id"]),
                    "next_actions": sorted({_ACTIONS[code] for code in row["gap_codes"]}),
                }
            )
    frameworks = []
    for framework_id in sorted(selected):
        members = [row for row in rows if row["framework_id"] == framework_id]
        counts = Counter(row["status"] for row in members)
        assessed = counts["pass"] + counts["fail"]
        frameworks.append(
            {
                "framework_id": framework_id,
                "catalogued": len(members),
                "mapped": sum(bool(row["reviewed_safeguard_count"] or row["pending_mapping_count"]) for row in members),
                "with_reviewed_mapping": sum(row["reviewed_safeguard_count"] > 0 for row in members),
                "mapping_review_pending": sum(row["pending_mapping_count"] > 0 for row in members),
                "assessed": assessed,
                "assessed_pct": round(assessed / len(members) * 100, 1),
                "status_counts": {status: counts[status] for status in _STATUSES},
                "requirements_with_gaps": sum(row["has_gaps"] for row in members),
            }
        )
    return {"frameworks": frameworks, "requirements": rows}


def build_framework_report(
    lake: str | Path, *, tenant_id: str, framework_ids: list[str] | None = None, expected_generation: str | None = None
) -> dict[str, Any]:
    """Verify and pin one generation; never substitute a live catalog or verdict."""
    root = Path(lake).resolve()
    with pin_generation(root) as generation:
        if generation is None or (expected_generation is not None and generation.name != expected_generation):
            raise ValueError("sealed generation unavailable or changed")
        verify_generation(generation)
        manifest = read_json(generation / "manifest.json")
        if not tenant_id or manifest.get("tenant_id") != tenant_id:
            raise ValueError("assessment tenant does not match the requested tenant")
        summary = read_summary(root)
        if summary is None:
            raise ValueError("generation has no supported CCF summary; re-evaluate the lake")
        catalog_rows = read_json(generation / "catalog/control_map.json")["controls"]
        controls = {row["control_id"]: row for row in catalog_rows}
        if len(controls) != len(catalog_rows):
            raise ValueError("duplicate frozen catalog requirement")
        projection = summarize_coverage(summary, controls, framework_ids=framework_ids)
        return {
            "schema_version": "grc-lake.framework-report.v1",
            "tenant_id": tenant_id,
            "generation": generation_identity(root),
            "scope": summary["scope"],
            "population_completeness": summary["population_completeness"],
            "review_log_verified_at_assessment": summary["review_log_verified"],
            "observed_asset_count": summary["asset_count"],
            "contains_synthetic_evidence": contains_synthetic_evidence(root),
            "evidence_origin": "Source markers are not producer authentication.",
            "assessment_generated_at": read_json(generation / "gold/dashboard_data.json")["generated_at"],
            "integrity": "Generation file hashes verified at export; hashes are not signatures.",
            "boundary": _BOUNDARY,
            **projection,
        }


def render_framework_report(report: dict[str, Any]) -> str:
    """Self-contained, escaped HTML; no scripts, external resources or lake paths."""

    def esc(value: Any) -> str:
        return html.escape(str(value), quote=True)

    overview = []
    details = []
    for framework in report["frameworks"]:
        framework_id = framework["framework_id"]
        overview.append(
            "<tr>"
            + "".join(
                f"<td>{esc(value)}</td>"
                for value in (
                    framework_id,
                    framework["catalogued"],
                    framework["mapped"],
                    framework["with_reviewed_mapping"],
                    f"{framework['assessed']} / {framework['catalogued']} ({framework['assessed_pct']}%)",
                    framework["status_counts"]["pass"],
                    framework["status_counts"]["fail"],
                    framework["requirements_with_gaps"],
                )
            )
            + "</tr>"
        )
        rows = []
        for row in report["requirements"]:
            if row["framework_id"] != framework_id:
                continue
            actions = (
                "<ul>" + "".join(f"<li>{esc(action)}</li>" for action in row["next_actions"]) + "</ul>"
                if row["next_actions"]
                else "No blockers retained in this assessment."
            )
            blockers = ", ".join(
                f"{item['safeguard_id']} ({item['status']}; unassessed assets: {item['unassessed_asset_count']}; invalid bindings: {item['invalid_binding_count']})"
                for item in row["blocking_safeguards"]
            )
            rows.append(f"""<tr><td><strong>{esc(row["control_id"])}</strong><br>{esc(row["title"])}</td>
<td><span class="badge">{esc(row["status"].replace("_", " "))}</span></td>
<td>{actions}<details><summary>Recorded gap details</summary><p>{esc(", ".join(row["gap_codes"]) or "None")}</p>
<p>Reviewed safeguard mappings: {esc(row["reviewed_safeguard_count"])} · Pending: {esc(row["pending_mapping_count"])} · Contextual: {esc(row["contextual_mapping_count"])}</p><p>{esc(blockers)}</p></details></td></tr>""")
        details.append(f"""<details class="framework"><summary>{esc(framework_id)} <span>{esc(framework["catalogued"])} requirements · {esc(framework["requirements_with_gaps"])} with gaps</span></summary>
<div class="scroll"><table><thead><tr><th>Requirement</th><th>Stored result</th><th>Next review actions</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>""")
    marker = (
        "Synthetic evidence is present."
        if report["contains_synthetic_evidence"]
        else "No explicit synthetic marker found; provider origin is not authenticated."
    )
    review = (
        "Verified at assessment time"
        if report["review_log_verified_at_assessment"]
        else "Unverified — review decisions need verification"
    )
    review_notice = (
        ""
        if report["review_log_verified_at_assessment"]
        else "<p><strong>Review ledger was unverified at assessment time.</strong></p>"
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>GRC Lake · Framework coverage report</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f2f5f7;color:#172c3b;font:15px/1.6 system-ui,sans-serif}}main{{max-width:1240px;margin:0 auto;padding:40px 24px}}header{{background:#102d3b;color:#fff;padding:32px;border-radius:16px}}.eyebrow{{text-transform:uppercase;letter-spacing:.14em;font-size:12px;color:#8ce3d1}}h1{{font-size:34px;line-height:1.2;margin:10px 0}}h2{{font-size:22px;margin:30px 0 12px}}p{{margin:10px 0}}.subtle{{color:#c6d8e0}}.notice{{padding:18px 22px;background:#fff5d9;border:1px solid #dbc47c;border-radius:12px;margin:20px 0}}.card,.framework{{background:white;border:1px solid #d6e0e5;border-radius:12px;margin:14px 0;overflow:hidden}}.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;text-align:left}}th{{background:#eaf1f4;font-size:12px;letter-spacing:.03em}}th,td{{padding:14px 16px;border-bottom:1px solid #e3e9ed;vertical-align:top}}td:first-child{{min-width:200px}}td{{overflow-wrap:anywhere}}th{{white-space:nowrap}}.framework>summary{{padding:18px 22px;font-weight:650;cursor:pointer}}.framework>summary span{{font-weight:400;color:#4b6473;margin-left:12px}}.badge{{display:inline-block;padding:3px 9px;border:1px solid #bdcdd6;background:#eef3f6;border-radius:6px;white-space:nowrap}}ul{{margin:0;padding-left:18px}}td details{{font-size:13px;margin-top:10px;color:#4b6473}}.provenance{{padding:20px;font-size:13px;overflow-wrap:anywhere}}footer{{font-size:13px;color:#4b6473;margin-top:24px}}@media(max-width:600px){{main{{padding:16px 10px}}header{{padding:24px 18px}}h1{{font-size:27px}}.framework>summary span{{display:block;margin-left:0}}.framework thead{{display:none}}.framework table,.framework tbody,.framework tr,.framework td{{display:block;width:100%}}.framework tr{{border-bottom:2px solid #d6e0e5;padding:8px 0}}.framework td{{border:0;padding:8px 16px;min-width:0}}.framework td:nth-child(3)::before{{content:"Next review actions";display:block;font-weight:650;margin-bottom:8px}}}}@media print{{body{{background:white}}main{{max-width:none;padding:0}}header{{background:white;color:#172c3b}}.subtle,.eyebrow{{color:#172c3b}}}}
</style></head><body><main><header><div class="eyebrow">GRC Lake / Assessment review</div><h1>Framework coverage report</h1><p class="subtle">Catalog, mapping review, and observed evidence — separately accounted for.</p><p>Assessment tenant: {esc(report["tenant_id"])}<br>Assessment generated: {esc(report["assessment_generated_at"])}</p></header>
<div class="notice"><strong>{esc(marker)}</strong>{review_notice}<p>{esc(report["boundary"])}</p></div>
<h2>Coverage at this generation</h2><p>Assessed means a stored pass or fail. Stale, not evaluated, and unmapped requirements remain in the denominator. A reviewed mapping count means at least one recorded reviewed implementation mapping. On narrow screens, scroll the overview table horizontally.</p>
<div class="card scroll"><table><thead><tr><th>Framework</th><th>Catalogued</th><th>Mapped</th><th>With reviewed mapping</th><th>Assessed / catalogued</th><th>Pass</th><th>Fail</th><th>With gaps</th></tr></thead><tbody>{"".join(overview)}</tbody></table></div>
<h2>Requirements and next actions</h2><p>Expand a framework to inspect every frozen requirement. Actions explain recorded gaps; they do not change decisions or create evidence requests.</p>{"".join(details)}
<h2>Provenance</h2><div class="card provenance"><p>Generation: {esc(report["generation"]["generation_id"])}<br>Generation manifest SHA-256: {esc(report["generation"]["manifest_sha256"])}</p><p>Review ledger: {esc(review)}<br>Observed assets: {esc(report["observed_asset_count"])}<br>Population completeness: {esc(report["population_completeness"])}</p><p>{esc(report["integrity"])}</p></div><footer>Read alongside coverage.json and manifest.json. Evidence freshness and review decisions are frozen at assessment time; export does not re-evaluate them. Expand sections before printing.</footer></main></body></html>"""


def export_framework_report(report: dict[str, Any], output: str | Path) -> dict[str, Any]:
    """Publish a private, complete archive exclusively; never overwrite a path."""
    target = Path(output)
    assert_mutable(target.resolve())
    files = {
        "coverage.json": (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
        "index.html": render_framework_report(report).encode(),
    }
    manifest = {
        "schema_version": "grc-lake.framework-report-bundle.v1",
        "entrypoint": "index.html",
        "generation": report["generation"],
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".framework-report-") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
        stream.flush()
        os.fsync(stream.fileno())
        os.link(stream.name, target)
    return manifest
