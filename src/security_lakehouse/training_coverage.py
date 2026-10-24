"""Training completion joined to the HR personnel population.

After a sync that writes training assignment records or HR employment records,
the runner rebuilds one derived row per person under
:data:`TRAINING_COVERAGE_CONNECTOR_ID`, plus one program summary. Only the
person rows bind ``SG-TRAINING-001``; assignment and summary rows use asset
types outside every safeguard's scope, so they never count as unassessed
population.

Per active HR person (required assignments only):

* any overdue assignment, or a completion older than the window: open
* every due assignment completed within the window: pass
* only assignments that are not yet due: no verdict (``not_yet_due``)
* no training record, hired more than the onboarding grace ago: open
* no training record inside the onboarding grace: no verdict

Population gaps stay explicit and never pass:

* terminated or not-yet-started staff are excluded and counted
* a trained person absent from HR, or whose identifiers point at two HR
  records, is ``not_evaluated``
* without any HR evidence a completion is ``not_evaluated``; an overdue
  assignment is still open, because the training system itself reports it

Nothing is produced until a training export has been collected.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from security_lakehouse.connectors_training import (
    DEFAULT_GRACE_DAYS,
    DEFAULT_WINDOW_DAYS,
    person_key,
)
from security_lakehouse.connectors_training import (
    EVENT_TYPE as ASSIGNMENT_EVENT_TYPE,
)
from security_lakehouse.hris import PERSONNEL_SENSITIVITY, parse_hr_date
from security_lakehouse.io import canonical_sha256
from security_lakehouse.models import utc_iso
from security_lakehouse.offboarding import HRIS_EVENT_TYPE, OFFBOARDING_SOURCE

TRAINING_COVERAGE_CONNECTOR_ID = "hris-training-coverage"
PERSON_EVENT_TYPE = "correlation.personnel.training"
SUMMARY_EVENT_TYPE = "correlation.personnel.training_summary"
TRAINING_SAFEGUARD_ID = "SG-TRAINING-001"
TRAINING_PERSON_ASSET_TYPE = "user"
PROGRAM_ASSET_TYPE = "training_program"
# Reviewed members of SG-TRAINING-001's crosswalk that concern awareness
# training and its records, with no extra required evidence types.
TRAINING_CONTROLS = [
    "CMMC-3.2.1",
    "FEDRAMP-AT-2",
    "FEDRAMP-AT-4",
    "NIST-800-53-AT-2",
    "NIST-800-53-AT-4",
    "NIST-CSF-PR.AT-01",
]
MAX_LISTED_COURSES = 50
COUNTERS = (
    "completed_within_window",
    "overdue",
    "completion_expired",
    "no_training_record",
    "not_yet_due",
    "within_onboarding_grace",
    "excluded_terminated",
    "not_yet_started",
    "not_in_hr_population",
    "identity_conflict",
    "hr_population_missing",
)


def is_training_coverage_input(row: Mapping[str, Any]) -> bool:
    return str(row.get("event_type") or "") in {HRIS_EVENT_TYPE, ASSIGNMENT_EVENT_TYPE}


@dataclass
class _HrPerson:
    key: str
    source: str
    employee_id: str
    email: str | None
    terminated: bool
    hire_date: date | None
    evidence_ref: str
    identifiers: set[str] = field(default_factory=set)


@dataclass
class _Bucket:
    key: str
    population: str
    hr: _HrPerson | None = None
    assignments: list[Mapping[str, Any]] = field(default_factory=list)


def correlate_training_coverage(
    raw_rows: Iterable[Mapping[str, Any]],
    *,
    as_of: date,
    collected_at: datetime,
    tenant_id: str = "customer-managed",
) -> list[dict[str, Any]]:
    hr_rows: list[Mapping[str, Any]] = []
    assignments: list[Mapping[str, Any]] = []
    for row in raw_rows:
        event_type = row.get("event_type")
        if event_type == HRIS_EVENT_TYPE:
            hr_rows.append(row)
        elif event_type == ASSIGNMENT_EVENT_TYPE:
            assignments.append(row)
    if not assignments:
        return []

    first = _attributes(assignments[0])
    window = _int(first.get("completion_window_days"), DEFAULT_WINDOW_DAYS)
    grace = _int(first.get("new_hire_grace_days"), DEFAULT_GRACE_DAYS)
    source_account = str(assignments[0].get("tenant_id") or tenant_id)
    synthetic = any(_attributes(row).get("synthetic") is True for row in assignments)
    people = _hr_people(hr_rows, as_of)
    has_hr = bool(people)
    by_identifier: dict[str, list[_HrPerson]] = {}
    for person in people:
        for identifier in person.identifiers:
            by_identifier.setdefault(identifier, []).append(person)

    buckets: dict[str, _Bucket] = {person.key: _Bucket(key=person.key, population="hr", hr=person) for person in people}
    for row in assignments:
        attributes = _attributes(row)
        email = _email(attributes.get("person_email"))
        employee_id = _clean(attributes.get("employee_id"))
        key = person_key(email, employee_id)
        if not has_hr:
            buckets.setdefault(key, _Bucket(key=key, population="hr_population_missing")).assignments.append(row)
            continue
        matches = {
            person.key
            for identifier in (f"email:{email}" if email else None, f"id:{employee_id}" if employee_id else None)
            if identifier
            for person in by_identifier.get(identifier, [])
        }
        if len(matches) == 1:
            buckets[matches.pop()].assignments.append(row)
        elif matches:
            conflict = f"conflict:{key}"
            buckets.setdefault(conflict, _Bucket(key=conflict, population="identity_conflict")).assignments.append(row)
        else:
            buckets.setdefault(key, _Bucket(key=key, population="not_in_hr_population")).assignments.append(row)

    counts = dict.fromkeys(COUNTERS, 0)
    active_population = 0
    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        assessment = _assess(bucket.assignments, as_of=as_of, window=window)
        verdict: tuple[str, str] | None
        if bucket.hr is not None:
            person = bucket.hr
            if person.terminated:
                if bucket.assignments:
                    counts["excluded_terminated"] += 1
                continue
            if person.hire_date is not None and person.hire_date > as_of:
                counts["not_yet_started"] += 1
                continue
            active_population += 1
            if assessment.outcome is not None:
                verdict = ("open" if assessment.outcome != "completed_within_window" else "pass", assessment.outcome)
            elif assessment.pending:
                counts["not_yet_due"] += 1
                continue
            elif person.hire_date is not None and (as_of - person.hire_date).days <= grace:
                counts["within_onboarding_grace"] += 1
                continue
            else:
                verdict = ("open", "no_training_record")
        elif not assessment.required:
            continue
        elif bucket.population in {"not_in_hr_population", "identity_conflict"}:
            verdict = ("not_evaluated", bucket.population)
        elif assessment.outcome in {"overdue", "completion_expired"}:
            verdict = ("open", assessment.outcome)
        elif assessment.outcome == "completed_within_window":
            verdict = ("not_evaluated", "hr_population_missing")
        else:
            counts["not_yet_due"] += 1
            continue
        counts[verdict[1]] += 1
        out.append(
            _person_event(
                bucket,
                assessment,
                status=verdict[0],
                outcome=verdict[1],
                window=window,
                collected_at=collected_at,
                source_account=source_account,
                synthetic=synthetic,
            )
        )
    out.append(
        _summary_event(
            counts,
            active_population=active_population if has_hr else None,
            hr_sources=sorted({person.source for person in people}),
            window=window,
            grace=grace,
            collected_at=collected_at,
            source_account=source_account,
            synthetic=synthetic,
        )
    )
    return out


@dataclass
class _Assessment:
    required: int = 0
    completed: list[str] = field(default_factory=list)
    overdue: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    latest_completed_at: str | None = None

    @property
    def outcome(self) -> str | None:
        if self.overdue:
            return "overdue"
        if self.expired:
            return "completion_expired"
        if self.completed:
            return "completed_within_window"
        return None


def _assess(rows: list[Mapping[str, Any]], *, as_of: date, window: int) -> _Assessment:
    result = _Assessment()
    for row in rows:
        attributes = _attributes(row)
        if attributes.get("required") is False:
            continue
        result.required += 1
        course = str(attributes.get("course_id") or "")
        completed = parse_hr_date(attributes.get("completed_at"))
        due = parse_hr_date(attributes.get("due_at"))
        if completed is not None:
            completed_at = completed.isoformat()
            if result.latest_completed_at is None or completed_at > result.latest_completed_at:
                result.latest_completed_at = completed_at
            (result.expired if (as_of - completed).days > window else result.completed).append(course)
        elif attributes.get("training_status") == "overdue" or (due is not None and due < as_of):
            result.overdue.append(course)
        else:
            result.pending.append(course)
    return result


def _hr_people(rows: list[Mapping[str, Any]], as_of: date) -> list[_HrPerson]:
    by_key: dict[str, _HrPerson] = {}
    for row in rows:
        attributes = _attributes(row)
        employee_id = _clean(attributes.get("employee_id"))
        if employee_id is None:
            continue
        email = _email(attributes.get("work_email"))
        source = str(row.get("source") or "hris")
        key = f"email:{email}" if email else f"hr:{source}:{employee_id}"
        terminated_on = parse_hr_date(attributes.get("termination_date"))
        terminated = attributes.get("is_terminated") is True or (terminated_on is not None and terminated_on <= as_of)
        person = by_key.get(key)
        if person is None:
            person = by_key[key] = _HrPerson(
                key=key,
                source=source,
                employee_id=employee_id,
                email=email,
                terminated=terminated,
                hire_date=parse_hr_date(attributes.get("hire_date")),
                evidence_ref=str(_mapping(row.get("evidence")).get("evidence_ref") or ""),
            )
        else:
            # The same work email in two HR systems is one person, active if
            # either system says so.
            person.terminated = person.terminated and terminated
        if email:
            person.identifiers.add(f"email:{email}")
        for identifier in (employee_id, _clean(attributes.get("employee_number"))):
            if identifier:
                person.identifiers.add(f"id:{identifier}")
    return list(by_key.values())


def _person_event(
    bucket: _Bucket,
    assessment: _Assessment,
    *,
    status: str,
    outcome: str,
    window: int,
    collected_at: datetime,
    source_account: str,
    synthetic: bool,
) -> dict[str, Any]:
    first = _attributes(bucket.assignments[0]) if bucket.assignments else {}
    hr = bucket.hr
    asset_id = "training-person:" + canonical_sha256([source_account, bucket.key])[:32]
    stable = "training-coverage-v1:" + canonical_sha256([source_account, asset_id])
    evidence_ref = (
        str(_mapping(bucket.assignments[0].get("evidence")).get("evidence_ref") or "")
        if bucket.assignments
        else (hr.evidence_ref if hr else "")
    ) or asset_id
    attributes: dict[str, Any] = {
        "outcome": outcome,
        "population": bucket.population,
        "person_email": (hr.email if hr else None) or _email(first.get("person_email")),
        "employee_id": _clean(first.get("employee_id")),
        "hr_source": hr.source if hr else None,
        "hr_employee_id": hr.employee_id if hr else None,
        "required_assignment_count": assessment.required,
        "completed_course_ids": assessment.completed[:MAX_LISTED_COURSES],
        "overdue_course_ids": assessment.overdue[:MAX_LISTED_COURSES],
        "expired_course_ids": assessment.expired[:MAX_LISTED_COURSES],
        "pending_course_ids": assessment.pending[:MAX_LISTED_COURSES],
        "latest_completed_at": assessment.latest_completed_at,
        "completion_window_days": window,
        "data_sensitivity": PERSONNEL_SENSITIVITY,
    }
    if synthetic:
        attributes["synthetic"] = True
    return {
        "event_id": f"correlation-{stable}",
        "tenant_id": source_account,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": OFFBOARDING_SOURCE,
        "event_type": PERSON_EVENT_TYPE,
        "entity": {
            "asset_id": asset_id,
            "asset_type": TRAINING_PERSON_ASSET_TYPE,
            "asset_owner": str(first.get("system") or (hr.source if hr else "")),
            "environment": "prod",
            "org": str(first.get("system") or (hr.source if hr else "")),
        },
        "severity": "medium" if status == "open" else "info",
        "status": status,
        "controls": list(TRAINING_CONTROLS),
        "safeguard_ids": [TRAINING_SAFEGUARD_ID],
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": evidence_ref,
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": attributes,
    }


def _summary_event(
    counts: dict[str, int],
    *,
    active_population: int | None,
    hr_sources: list[str],
    window: int,
    grace: int,
    collected_at: datetime,
    source_account: str,
    synthetic: bool,
) -> dict[str, Any]:
    completed = counts["completed_within_window"]
    if active_population is None:
        statement = (
            f"{counts['hr_population_missing']} people in the training export completed required training "
            f"within the last {window} days; the active personnel population is not established without "
            "HR evidence."
        )
    else:
        statement = (
            f"{completed} of {active_population} active personnel completed required training "
            f"within the last {window} days."
        )
    asset_id = "training-program:" + canonical_sha256([source_account, "summary"])[:32]
    stable = "training-coverage-v1:" + canonical_sha256([source_account, asset_id])
    attributes: dict[str, Any] = {
        "statement": statement,
        "population_source": "hris" if active_population is not None else "none",
        "population_completeness": "hr_population" if active_population is not None else "not_established",
        "hr_sources": hr_sources,
        "active_population": active_population,
        **counts,
        "completion_window_days": window,
        "new_hire_grace_days": grace,
    }
    if synthetic:
        attributes["synthetic"] = True
    return {
        "event_id": f"correlation-{stable}",
        "tenant_id": source_account,
        "workspace_id": "default",
        "event_time": utc_iso(collected_at),
        "source": OFFBOARDING_SOURCE,
        "event_type": SUMMARY_EVENT_TYPE,
        "entity": {
            "asset_id": asset_id,
            "asset_type": PROGRAM_ASSET_TYPE,
            "asset_owner": "training-program",
            "environment": "prod",
            "org": "training-program",
        },
        "severity": "info",
        "status": "observed",
        "controls": [],
        "evidence": {
            "evidence_id": f"ev-{stable}",
            "evidence_ref": asset_id,
            "evidence_collected_at": utc_iso(collected_at),
        },
        "attributes": attributes,
    }


def _attributes(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(row.get("attributes"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _email(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text if "@" in text else None


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else default
