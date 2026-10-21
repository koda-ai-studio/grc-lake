"""Bounded, offline import of Agent-Bom AI-BOM 1.0 finding observations.

The producer report remains the evidence source. Its framework tags, lifecycle
closures, and scan completeness are never converted into compliance assertions.
No Agent-Bom dependency, cloud credentials, or network access is required.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from security_lakehouse import strict_json
from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.generations import assert_mutable
from security_lakehouse.models import utc_iso
from security_lakehouse.validation import evidence_timestamp, validate_raw_events

MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_FINDINGS = 50_000
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:@/+~-]{1,512}\Z")
_VULNERABILITY_TYPES = frozenset({"CVE", "MALICIOUS_PACKAGE"})
_RATED_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a nonempty bounded identifier")
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def agent_bom_events(
    report: Any,
    *,
    tenant_id: str,
    asset_id: str,
    controls: list[str] | None = None,
    synthetic: bool = False,
    now: datetime | None = None,
    report_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Return a receipt and one event per finding, without silently dropping rows.

    Only CVE/malicious-package observations receive explicit control bindings.
    Active, rated findings become open; other observations remain unassessed.
    The caller binds tenant and report asset scope; report fields cannot override
    either. Raw descriptions, credentials, commands, and warnings are not copied.
    """
    strict_json.validate(report)
    if not isinstance(report, dict) or report.get("schema_version") != "1.0" or report.get("document_type") != "AI-BOM":
        raise ValueError("expected an Agent-Bom AI-BOM report with schema_version 1.0")
    tenant_id = _identifier(tenant_id, "tenant_id")
    asset_id = _identifier(asset_id, "asset_id")
    scan_id = _identifier(report.get("scan_id"), "scan_id")
    moment = evidence_timestamp(report.get("generated_at"))
    if moment > (now or datetime.now(UTC)):
        raise ValueError("report generated_at cannot be in the future")
    stamp = utc_iso(moment)
    findings = report.get("findings")
    if not isinstance(findings, list) or len(findings) > MAX_FINDINGS:
        raise ValueError("findings must be a list with at most 50000 entries")
    selected = sorted(set(controls or []))
    catalog = load_control_catalog()
    if any(control not in catalog for control in selected):
        raise ValueError("control binding contains an unknown GRC Lake control")
    for key in ("synthetic", "demo"):
        if key in report and not isinstance(report[key], bool):
            raise ValueError(f"report {key} marker must be boolean")
    marked_synthetic = synthetic or report.get("synthetic") is True or report.get("demo") is True
    digest = report_sha256 if report_sha256 is not None else _digest(report)
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("report_sha256 must be a SHA-256 digest")
    scan_run = report.get("scan_run", {})
    if not isinstance(scan_run, dict):
        raise ValueError("scan_run must be an object")
    if scan_run.get("schema_version", "1") != "1":
        raise ValueError("scan_run schema_version is unsupported")
    outcome = scan_run.get("outcome", "unknown")
    if not isinstance(outcome, str) or outcome not in {"complete", "partial", "failed", "unknown"}:
        raise ValueError("scan_run outcome is unsupported")
    warnings = report.get("warnings", [])
    if not isinstance(warnings, list):
        raise ValueError("warnings must be a list")
    common = {
        "report_sha256": digest,
        "report_schema_version": "1.0",
        "scan_id": scan_id,
        "scan_outcome": outcome,
        "synthetic": marked_synthetic,
        "provenance": "user-supplied-report; provider origin not authenticated",
    }

    def event(
        key: Any,
        event_type: str,
        attrs: dict[str, Any],
        *,
        status: str = "not_evaluated",
        severity: str = "info",
        bindings: list[str] | None = None,
        pointer: str = "",
    ) -> dict[str, Any]:
        identity = _digest(["agent-bom-import-v1", tenant_id, asset_id, scan_id, stamp, key])
        return {
            "event_id": f"agent-bom:{identity}",
            "tenant_id": tenant_id,
            "event_time": stamp,
            "source": "agent-bom-report",
            "event_type": event_type,
            "entity": {
                "asset_id": asset_id,
                "asset_type": "scan_scope",
                "asset_owner": "unassigned",
                "environment": "unknown",
            },
            "severity": severity,
            "status": status,
            "controls": bindings or [],
            "evidence": {
                "evidence_id": f"agent-bom:{identity}",
                "ref": f"urn:agent-bom:report:{digest}{pointer}",
                "collected_at": stamp,
            },
            "attributes": {**common, **attrs},
        }

    rows = [event("receipt", "agent_bom.scan_report", {"finding_count": len(findings), "warning_count": len(warnings)})]
    seen: set[str] = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValueError("each finding must be an object")
        if finding.get("schema_version", "1") != "1":
            raise ValueError("finding schema_version is unsupported")
        finding_id = _identifier(finding.get("occurrence_id") or finding.get("id"), "finding identity")
        kind = _identifier(finding.get("finding_type"), "finding_type")
        asset = finding.get("asset", {})
        if not isinstance(asset, dict):
            raise ValueError("finding asset must be an object")
        asset_digest = _digest(asset)
        finding_key = [kind, finding_id, asset_digest]
        key_digest = _digest(finding_key)
        if key_digest in seen:
            raise ValueError("duplicate finding identity in report")
        seen.add(key_digest)
        suppressed = finding.get("suppressed", False)
        if not isinstance(suppressed, bool):
            raise ValueError("finding suppressed must be boolean")
        source_status = finding.get("status")
        if source_status is None:
            source_status = "unknown"
        source_severity = finding.get("severity", "unknown")
        if not isinstance(source_status, str) or not isinstance(source_severity, str):
            raise ValueError("finding status and severity must be strings")
        # Keep unknown vocabularies visible without copying unbounded free text.
        source_status = _identifier(source_status, "finding status").lower()
        source_severity = _identifier(source_severity, "finding severity").lower()
        cve_id = finding.get("cve_id")
        cve = {"cve_id": cve_id} if isinstance(cve_id, str) and re.fullmatch(r"CVE-[0-9]{4}-[0-9]{4,}", cve_id) else {}
        vulnerability = kind in _VULNERABILITY_TYPES
        active = (
            vulnerability
            and not suppressed
            and source_status in {"new", "open", "unchanged", "reopened"}
            and source_severity in _RATED_SEVERITIES
        )
        rows.append(
            event(
                finding_key,
                "scanner.dependency" if vulnerability else "agent_bom.finding",
                {
                    "upstream_finding_id": finding_id,
                    "finding_type": kind,
                    "upstream_asset_sha256": asset_digest,
                    "upstream_status": source_status,
                    "upstream_severity": source_severity,
                    "suppressed": suppressed,
                    **cve,
                },
                status="open" if active else "not_evaluated",
                severity=source_severity if source_severity in _RATED_SEVERITIES else "info",
                bindings=selected if vulnerability else [],
                pointer=f"#/findings/{index}",
            )
        )
    errors = validate_raw_events(rows)
    if errors:
        raise ValueError("imported observations violate the raw evidence contract")
    return rows


def import_agent_bom_report(
    report_path: str | Path,
    output_path: str | Path,
    *,
    tenant_id: str,
    asset_id: str,
    controls: list[str] | None = None,
    synthetic: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a bounded report before writing a new, private JSONL file."""
    source, target = Path(report_path), Path(output_path)
    with source.open("rb") as stream:
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("report exceeds the 32 MiB import limit")
    report = strict_json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    rows = agent_bom_events(
        report,
        tenant_id=tenant_id,
        asset_id=asset_id,
        controls=controls,
        synthetic=synthetic,
        now=now,
        report_sha256=digest,
    )
    serialized = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    assert_mutable(target.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    # Publish a complete 0600 file exclusively, including against dangling symlinks.
    # A failed write/fsync/link leaves the destination untouched.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=".agent-bom-") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
        os.link(stream.name, target)
    return {
        "schema": "grc-lake.agent-bom-import.v1",
        "report_sha256": digest,
        "event_count": len(rows),
        "finding_count": len(rows) - 1,
        "bound_vulnerability_count": sum(bool(row["controls"]) for row in rows),
        "scan_outcome": rows[0]["attributes"]["scan_outcome"],
        "synthetic": rows[0]["attributes"]["synthetic"],
    }
