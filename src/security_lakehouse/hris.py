"""Vendor-neutral HRIS employment records.

Each HRIS connector (BambooHR today) maps its vendor payload onto
:class:`EmploymentRecord` and emits the same ``hris.personnel.employment``
event, so downstream consumers never branch on the HR vendor.

PII boundary: an employment record holds identifiers, work email (the join key
to identity-provider accounts), employment status, hire/termination dates,
department, and manager id. Names, dates of birth, government identifiers,
compensation, addresses, and personal contact details are out of scope and must
never be requested from a vendor. Event attributes carry
``data_sensitivity: confidential`` so :func:`data_policy.redact_payload` hides
them from auditor and public-share roles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from security_lakehouse.connector_ids import stable_id_slug
from security_lakehouse.models import utc_iso

# Controls verified to exist in controls/catalog.json. All are satisfied by
# current personnel-lifecycle evidence (missing/stale-evidence rules).
PERSONNEL_CONTROLS = [
    "FEDRAMP-PS-4",
    "FEDRAMP-PS-5",
    "ISO27001-A.6.5",
    "CMMC-3.9.2",
    "HIPAA-164.308(a)(3)",
]

PERSONNEL_SENSITIVITY = "confidential"


@dataclass(frozen=True)
class EmploymentRecord:
    employee_id: str
    employee_number: str | None
    work_email: str | None
    employment_status: str | None
    hire_date: str | None
    termination_date: str | None
    department: str | None
    manager_id: str | None

    def is_terminated(self, as_of: date) -> bool:
        parsed = parse_hr_date(self.termination_date)
        return parsed is not None and parsed <= as_of


def parse_hr_date(value: Any) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` HR date; empty and zero dates are ``None``."""
    text = str(value or "").strip()[:10]
    if not text or text.startswith("0000"):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def clean_hr_date(value: Any) -> str | None:
    parsed = parse_hr_date(value)
    return parsed.isoformat() if parsed else None


def employment_event(
    record: EmploymentRecord,
    *,
    vendor: str,
    org: str,
    evidence_ref: str,
    collected_at: datetime,
    tenant_id: str,
) -> dict[str, Any]:
    stable = stable_id_slug(f"{org}:employment:{record.employee_id}", fallback="hris")
    return {
        "event_id": f"{vendor}-{stable}",
        "tenant_id": tenant_id,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": vendor,
        "event_type": "hris.personnel.employment",
        "entity": {
            "asset_id": f"{vendor}:employee:{record.employee_id}",
            "asset_type": "hris_employee",
            "asset_owner": org,
            "environment": "prod",
            "org": org,
        },
        "severity": "info",
        "status": "observed",
        "controls": PERSONNEL_CONTROLS,
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": {
            "employee_id": record.employee_id,
            "employee_number": record.employee_number,
            "work_email": record.work_email,
            "employment_status": record.employment_status,
            "hire_date": record.hire_date,
            "termination_date": record.termination_date,
            "is_terminated": record.is_terminated(collected_at.date()),
            "department": record.department,
            "manager_id": record.manager_id,
            "data_sensitivity": PERSONNEL_SENSITIVITY,
        },
    }
