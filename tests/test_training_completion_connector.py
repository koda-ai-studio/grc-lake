"""Vendor-neutral training-completion exports, joined to the HR population."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from security_lakehouse import connector_runner, connectors_training, local_paths
from security_lakehouse.catalog import load_control_catalog
from security_lakehouse.connector_state import append_config_event, latest_run
from security_lakehouse.connectors_training import (
    CONNECTOR_ID,
    TrainingExportError,
    TrainingExportSettings,
    collect_training_evidence,
    read_training_export,
)
from security_lakehouse.execution_mode import server_execution
from security_lakehouse.hris import EmploymentRecord, employment_event
from security_lakehouse.io import read_json, read_jsonl
from security_lakehouse.safeguards import load_safeguards
from security_lakehouse.training_coverage import (
    TRAINING_CONTROLS,
    TRAINING_COVERAGE_CONNECTOR_ID,
    TRAINING_PERSON_ASSET_TYPE,
    TRAINING_SAFEGUARD_ID,
    correlate_training_coverage,
)
from security_lakehouse.validation import validate_raw_events

FIXTURES = Path(__file__).parent / "fixtures" / "training_completion"
CSV_DIR = FIXTURES / "csv"
JSON_DIR = FIXTURES / "json"
AS_OF = date(2026, 6, 3)
COLLECTED = datetime(2026, 6, 3, 12, tzinfo=UTC)
HEADER = "person_email,employee_id,course_id,course_name,assigned_at,due_at,completed_at,status,score,required\n"


def _assignments(path: Path = CSV_DIR, **settings: Any) -> list[dict[str, Any]]:
    return collect_training_evidence(
        path, settings=TrainingExportSettings.from_options(settings), collected_at=COLLECTED, tenant_id="t"
    )


def _hr(employee_id: str, email: str, *, hired: str = "2023-01-09", terminated: str | None = None) -> dict:
    record = EmploymentRecord(
        employee_id=employee_id,
        employee_number=f"E-{employee_id}",
        work_email=email,
        employment_status=None,
        hire_date=hired,
        termination_date=terminated,
        department=None,
        manager_id=None,
    )
    return employment_event(
        record, vendor="bamboohr", org="acme.bamboohr.com", evidence_ref="ref", collected_at=COLLECTED, tenant_id="t"
    )


HR_POPULATION = [
    _hr("101", "ada@example.com"),
    _hr("102", "grace@example.com", terminated="2026-05-15"),
    _hr("103", "alan@example.com"),
    _hr("104", "linus@example.com"),
    _hr("105", "barbara@example.com"),
    _hr("106", "margaret@example.com", hired="2026-05-20"),
    _hr("107", "katherine@example.com"),
]


def _by_email(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        row["attributes"]["person_email"]: row for row in rows if row["event_type"] == "correlation.personnel.training"
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    [summary] = [row for row in rows if row["event_type"] == "correlation.personnel.training_summary"]
    return summary


# --- column contract -------------------------------------------------------------


def test_csv_export_maps_the_column_contract_and_drops_other_columns() -> None:
    records = read_training_export(CSV_DIR, settings=TrainingExportSettings(), collected_at=COLLECTED)
    ada = next(r for r in records if r.person_email == "ada@example.com" and r.course_id == "SAT-2026")
    assert ada.employee_id == "101"
    assert ada.course_name == "Annual security awareness"
    assert (ada.assigned_at, ada.due_at, ada.completed_at) == ("2026-01-05", "2026-02-05", "2026-01-20")
    assert (ada.status, ada.score, ada.required) == ("completed", 92.0, True)
    contractor = next(r for r in records if r.person_email == "contractor@example.com")
    # vendor aliases normalize; a UTC timestamp keeps its calendar date
    assert (contractor.status, contractor.completed_at, contractor.employee_id) == ("completed", "2026-01-12", None)
    phish = next(r for r in records if r.course_id == "PHISH-101")
    assert (phish.status, phish.required) == ("overdue", False)

    rows = _assignments()
    assert validate_raw_events(rows) == []
    assert {row["event_type"] for row in rows} == {"training.assignment.record"}
    assert all(row["status"] == "observed" and not row.get("safeguard_ids") for row in rows)
    serialized = json.dumps(rows)
    assert "manager_name" not in serialized and "Not stored" not in serialized
    assert all(row["attributes"]["data_sensitivity"] == "confidential" for row in rows)
    assert all(len(row["attributes"]["export_sha256"]) == 64 for row in rows)


def test_json_export_accepts_a_records_envelope_and_a_bare_list(tmp_path: Path) -> None:
    from_envelope = read_training_export(JSON_DIR, settings=TrainingExportSettings(), collected_at=COLLECTED)
    assert [(r.person_email, r.status, r.completed_at) for r in from_envelope] == [
        ("ada@example.com", "completed", "2026-01-20"),
        ("alan@example.com", "overdue", None),
    ]
    bare = tmp_path / "export.json"
    bare.write_text(json.dumps(json.loads((JSON_DIR / "training_export.json").read_text())["records"]))
    from_list = read_training_export(bare, settings=TrainingExportSettings(), collected_at=COLLECTED)
    assert [replace(r, source_file="", export_sha256="") for r in from_list] == [
        replace(r, source_file="", export_sha256="") for r in from_envelope
    ]


def test_column_map_renames_vendor_headers(tmp_path: Path) -> None:
    export = tmp_path / "lms.csv"
    export.write_text("User Email,Course,Status,Completion Date\nada@example.com,SAT,Passed,2026-05-01\n")
    settings = TrainingExportSettings.from_options(
        {
            "column_map": {
                "person_email": "User Email",
                "course_id": "Course",
                "status": "Status",
                "completed_at": "Completion Date",
            }
        }
    )
    [record] = read_training_export(export, settings=settings, collected_at=COLLECTED)
    assert (record.person_email, record.course_id, record.status, record.completed_at) == (
        "ada@example.com",
        "SAT",
        "completed",
        "2026-05-01",
    )


def test_repeated_attempts_keep_the_latest_completion(tmp_path: Path) -> None:
    export = tmp_path / "attempts.csv"
    export.write_text(
        HEADER
        + "ada@example.com,101,SAT,,,,2025-05-01,completed,,\n"
        + "ADA@example.com,101,SAT,,,,2026-05-01,completed,,\n"
        + "ada@example.com,101,SAT,,2026-04-01,2026-07-01,,in_progress,,\n"
    )
    [record] = read_training_export(export, settings=TrainingExportSettings(), collected_at=COLLECTED)
    assert record.completed_at == "2026-05-01"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "no header"),
        (HEADER, "no training records"),
        ("person_email,course_id\nada@example.com,SAT\n", "missing required column: status"),
        ("course_id,status\nSAT,completed\n", "person_email or employee_id"),
        ("person_email,person_email,course_id,status\na@example.com,a@example.com,SAT,completed\n", "duplicate"),
        (HEADER + "ada@example.com,101,SAT,,,,,finished-ish,,\n", "row 2: unknown status"),
        (HEADER + "ada@example.com,101,SAT,,,,,completed,,\n", "row 2: completed without completed_at"),
        (HEADER + "ada@example.com,101,SAT,,,,2026-05-01,in_progress,,\n", "row 2: completed_at set"),
        (HEADER + "ada@example.com,101,SAT,,,,05/01/2026,completed,,\n", "row 2: invalid completed_at"),
        (HEADER + "ada@example.com,101,SAT,,,,2030-01-01,completed,,\n", "row 2: completed_at is in the future"),
        (HEADER + "not-an-email,101,SAT,,,,,not_started,,\n", "row 2: invalid person_email"),
        (HEADER + ",,SAT,,,,,not_started,,\n", "row 2: needs person_email or employee_id"),
        (HEADER + "ada@example.com,101,,,,,,not_started,,\n", "row 2: missing course_id"),
        (HEADER + "ada@example.com,101,SAT,,,,2026-05-01,completed,140,\n", "row 2: invalid score"),
        (HEADER + "ada@example.com,101,SAT,,,,2026-05-01,completed,,maybe\n", "row 2: invalid required"),
        (HEADER + "ada@example.com,101,SAT,,,,2026-05-01,completed,,true,extra\n", "row 2: has more fields"),
    ],
)
def test_malformed_csv_is_rejected_with_a_row_level_error_and_no_pii(
    tmp_path: Path, content: str, message: str
) -> None:
    export = tmp_path / "bad.csv"
    export.write_text(content)
    with pytest.raises(TrainingExportError, match=message) as caught:
        read_training_export(export, settings=TrainingExportSettings(), collected_at=COLLECTED)
    assert "ada@example.com" not in str(caught.value)
    assert "not-an-email" not in str(caught.value)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("{not json", "not valid JSON"),
        ('{"rows": []}', "list of records"),
        ("[]", "no training records"),
        ('["ada@example.com"]', "record 1: must be an object"),
        ('[{"person_email": "ada@example.com", "course_id": "SAT", "status": {"x": 1}}]', "record 1: status"),
        ('[{"person_email": "ada@example.com", "course_id": "SAT"}]', "record 1: missing status"),
    ],
)
def test_malformed_json_is_rejected(tmp_path: Path, payload: str, message: str) -> None:
    export = tmp_path / "bad.json"
    export.write_text(payload)
    with pytest.raises(TrainingExportError, match=message) as caught:
        read_training_export(export, settings=TrainingExportSettings(), collected_at=COLLECTED)
    assert "ada@example.com" not in str(caught.value)


def test_error_lists_are_bounded(tmp_path: Path) -> None:
    export = tmp_path / "bad.csv"
    export.write_text(HEADER + "".join(f"u{i}@example.com,{i},SAT,,,,,bogus,,\n" for i in range(50)))
    with pytest.raises(TrainingExportError) as caught:
        read_training_export(export, settings=TrainingExportSettings(), collected_at=COLLECTED)
    text = str(caught.value)
    assert "50 invalid rows" in text
    assert text.count("unknown status") == connectors_training.MAX_REPORTED_ERRORS


def test_oversized_binary_and_unknown_files_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = TrainingExportSettings()
    big = tmp_path / "big" / "export.csv"
    big.parent.mkdir()
    big.write_text(HEADER + "ada@example.com,101,SAT,,,,2026-05-01,completed,,\n")
    monkeypatch.setattr(connectors_training, "MAX_FILE_BYTES", 64)
    with pytest.raises(TrainingExportError, match="exceeds"):
        read_training_export(big, settings=settings, collected_at=COLLECTED)
    monkeypatch.undo()

    binary = tmp_path / "latin.csv"
    binary.write_bytes(HEADER.encode() + "jos\xe9@example.com,1,SAT,,,,,not_started,,\n".encode("latin-1"))
    with pytest.raises(TrainingExportError, match="UTF-8"):
        read_training_export(binary, settings=settings, collected_at=COLLECTED)

    other = tmp_path / "export.xlsx"
    other.write_text("x")
    with pytest.raises(TrainingExportError, match=r"\.csv or \.json"):
        read_training_export(other, settings=settings, collected_at=COLLECTED)

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    (empty_dir / "notes.txt").write_text("x")
    with pytest.raises(TrainingExportError, match="no .csv or .json"):
        read_training_export(empty_dir, settings=settings, collected_at=COLLECTED)

    with pytest.raises(TrainingExportError, match="does not exist"):
        read_training_export(tmp_path / "missing.csv", settings=settings, collected_at=COLLECTED)


def test_directory_exports_cannot_follow_symlinks_out_of_the_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_text(HEADER + "ada@example.com,101,SAT,,,,2026-05-01,completed,,\n")
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    (export_dir / "linked.csv").symlink_to(outside)
    with pytest.raises(TrainingExportError, match="outside the export directory"):
        read_training_export(export_dir, settings=TrainingExportSettings(), collected_at=COLLECTED)


@pytest.mark.parametrize(
    "options",
    [
        {"completion_window_days": 0},
        {"completion_window_days": 5000},
        {"completion_window_days": "365"},
        {"new_hire_grace_days": -1},
        {"column_map": {"nickname": "Name"}},
        {"column_map": {"person_email": ""}},
        {"column_map": {"person_email": "Email", "employee_id": "Email"}},
        {"system": "../etc"},
    ],
)
def test_invalid_settings_are_rejected(options: dict[str, Any]) -> None:
    with pytest.raises(TrainingExportError):
        TrainingExportSettings.from_options(options)


# --- evaluation against the HR population ---------------------------------------------


def test_population_join_states_n_of_m_and_keeps_gaps_explicit() -> None:
    derived = correlate_training_coverage(
        [*HR_POPULATION, *_assignments()], as_of=AS_OF, collected_at=COLLECTED, tenant_id="t"
    )
    assert validate_raw_events(derived) == []
    people = _by_email(derived)
    outcomes = {email: (row["status"], row["attributes"]["outcome"]) for email, row in people.items()}
    assert outcomes == {
        "ada@example.com": ("pass", "completed_within_window"),
        "alan@example.com": ("open", "overdue"),
        "linus@example.com": ("open", "completion_expired"),
        "katherine@example.com": ("open", "no_training_record"),
        "contractor@example.com": ("not_evaluated", "not_in_hr_population"),
    }
    # terminated staff, a new hire inside the onboarding grace, and an assignment
    # that is not yet due neither pass nor fail
    assert {"grace@example.com", "margaret@example.com", "barbara@example.com"}.isdisjoint(people)
    for row in people.values():
        assert row["safeguard_ids"] == [TRAINING_SAFEGUARD_ID]
        assert row["controls"] == TRAINING_CONTROLS
        assert row["entity"]["asset_type"] == TRAINING_PERSON_ASSET_TYPE
        assert "@" not in row["entity"]["asset_id"]
        assert row["attributes"]["data_sensitivity"] == "confidential"
    # the optional phishing course is overdue but does not fail ada
    assert people["ada@example.com"]["attributes"]["overdue_course_ids"] == []

    summary = _summary(derived)
    assert summary["status"] == "observed"
    assert not summary.get("safeguard_ids")
    attributes = summary["attributes"]
    assert attributes["population_source"] == "hris"
    assert attributes["population_completeness"] == "hr_population"
    assert {
        key: attributes[key]
        for key in (
            "active_population",
            "completed_within_window",
            "overdue",
            "completion_expired",
            "no_training_record",
            "not_yet_due",
            "within_onboarding_grace",
            "excluded_terminated",
            "not_in_hr_population",
            "identity_conflict",
        )
    } == {
        "active_population": 6,
        "completed_within_window": 1,
        "overdue": 1,
        "completion_expired": 1,
        "no_training_record": 1,
        "not_yet_due": 1,
        "within_onboarding_grace": 1,
        "excluded_terminated": 1,
        "not_in_hr_population": 1,
        "identity_conflict": 0,
    }
    assert attributes["statement"] == ("1 of 6 active personnel completed required training within the last 365 days.")


def test_without_an_hr_population_completions_are_not_evaluated_but_overdue_stays_open() -> None:
    derived = correlate_training_coverage(_assignments(), as_of=AS_OF, collected_at=COLLECTED, tenant_id="t")
    outcomes = {email: (row["status"], row["attributes"]["outcome"]) for email, row in _by_email(derived).items()}
    assert outcomes == {
        "ada@example.com": ("not_evaluated", "hr_population_missing"),
        "contractor@example.com": ("not_evaluated", "hr_population_missing"),
        "alan@example.com": ("open", "overdue"),
        "grace@example.com": ("open", "overdue"),
        "linus@example.com": ("open", "completion_expired"),
    }
    attributes = _summary(derived)["attributes"]
    assert attributes["population_source"] == "none"
    assert attributes["population_completeness"] == "not_established"
    assert attributes["active_population"] is None
    assert "not established" in attributes["statement"]


def test_conflicting_identifiers_are_not_evaluated(tmp_path: Path) -> None:
    export = tmp_path / "export.csv"
    # ada's email with alan's employee id cannot be attributed to either person
    export.write_text(HEADER + "ada@example.com,103,SAT,,,,2026-05-01,completed,,\n")
    derived = correlate_training_coverage(
        [*HR_POPULATION, *_assignments(export)], as_of=AS_OF, collected_at=COLLECTED, tenant_id="t"
    )
    conflict = _by_email(derived)["ada@example.com"]
    assert (conflict["status"], conflict["attributes"]["outcome"]) == ("not_evaluated", "identity_conflict")
    assert _summary(derived)["attributes"]["identity_conflict"] == 1


def test_employee_id_alone_joins_the_hr_record(tmp_path: Path) -> None:
    export = tmp_path / "export.csv"
    export.write_text(HEADER + ",E-103,SAT,,,,2026-05-01,completed,,\n")
    derived = correlate_training_coverage(
        [*HR_POPULATION, *_assignments(export)], as_of=AS_OF, collected_at=COLLECTED, tenant_id="t"
    )
    alan = _by_email(derived)["alan@example.com"]
    assert (alan["status"], alan["attributes"]["hr_employee_id"]) == ("pass", "103")


def test_completion_window_is_configurable() -> None:
    derived = correlate_training_coverage(
        [*HR_POPULATION, *_assignments(completion_window_days=730)],
        as_of=AS_OF,
        collected_at=COLLECTED,
        tenant_id="t",
    )
    assert _by_email(derived)["linus@example.com"]["status"] == "pass"


def test_hr_only_lakes_produce_no_training_rows() -> None:
    assert correlate_training_coverage(HR_POPULATION, as_of=AS_OF, collected_at=COLLECTED, tenant_id="t") == []


def test_bindings_stay_inside_the_reviewed_training_crosswalk() -> None:
    safeguards = {row["safeguard_id"]: row for row in load_safeguards()["safeguards"]}
    training = safeguards[TRAINING_SAFEGUARD_ID]
    reviewed = {m["control_id"] for m in training["satisfies"] if m.get("review_status") == "reviewed"}
    catalog = load_control_catalog()
    assert set(TRAINING_CONTROLS) <= reviewed
    assert all(control_id in catalog for control_id in TRAINING_CONTROLS)
    assert all(not catalog[control_id].get("required_evidence_types") for control_id in TRAINING_CONTROLS)
    assert TRAINING_PERSON_ASSET_TYPE in training["asset_types"]
    # Only SG-TRAINING-001 and SG-IDENTITY-001 accept "user"; assignment and
    # program rows count toward no safeguard's scope.
    for asset_type in ("training_assignment", "training_program"):
        assert not [sid for sid, row in safeguards.items() if asset_type in row.get("asset_types", [])]


# --- sync, pipeline and CCF assessment ------------------------------------------------


def _day(offset: int) -> str:
    return (datetime.now(UTC).date() + timedelta(days=offset)).isoformat()


def _write_hr_fixture(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    people = [
        ("201", "ada@example.com", _day(-900), None),
        ("202", "alan@example.com", _day(-900), None),
        ("203", "grace@example.com", _day(-900), _day(-20)),
    ]
    (directory / "employee_dataset.json").write_text(
        json.dumps(
            [
                {"fields": {"eeid": eeid, "email": email, "hireDate": hired, "terminationDate": terminated}}
                for eeid, email, hired, terminated in people
            ]
        )
    )
    return directory


def _write_training_fixture(directory: Path, *, alan_completed: bool) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    alan = (
        f"alan@example.com,202,SAT,Awareness,{_day(-60)},{_day(-30)},{_day(-40)},completed,90,true\n"
        if alan_completed
        else f"alan@example.com,202,SAT,Awareness,{_day(-60)},{_day(-30)},,not_started,,true\n"
    )
    (directory / "export.csv").write_text(
        HEADER
        + f"ada@example.com,201,SAT,Awareness,{_day(-60)},{_day(-30)},{_day(-45)},completed,95,true\n"
        + alan
        + f"grace@example.com,203,SAT,Awareness,{_day(-60)},{_day(-30)},,overdue,,true\n"
    )
    return directory


def _enable(lake: Path) -> None:
    append_config_event(
        lake,
        connector_id="bamboohr-personnel",
        state="enabled",
        actor="a",
        credentials={"company_domain": "acme", "credential_ref": "BAMBOOHR_API_KEY"},
    )
    append_config_event(
        lake, connector_id=CONNECTOR_ID, state="enabled", actor="a", credentials={"path": "/srv/exports/lms"}
    )


def _assessment(lake: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    result = read_json(lake / "gold/ccf_assessment.json")
    safeguard = next(row for row in result["safeguards"] if row["safeguard_id"] == TRAINING_SAFEGUARD_ID)
    requirements = {row["control_id"]: row for row in result["requirements"]}
    return safeguard, requirements


def test_sync_joins_hr_and_training_through_the_ccf_assessment(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _enable(lake)
    raw_path = lake / connector_runner.CONNECTOR_RAW_FILE

    # training first: no HR population yet, so nothing can pass
    connector_runner.run_connector_sync(
        lake,
        connector_id=CONNECTOR_ID,
        fixture_dir=_write_training_fixture(tmp_path / "t1", alan_completed=False),
    )
    safeguard, _ = _assessment(lake)
    assert safeguard["status"] == "fail"  # alan's training is overdue even without HR context
    derived = [r for r in read_jsonl(raw_path) if r.get("connector_id") == TRAINING_COVERAGE_CONNECTOR_ID]
    assert _summary(derived)["attributes"]["population_source"] == "none"

    # HR arrives: grace is terminated and drops out of the population
    connector_runner.run_connector_sync(
        lake, connector_id="bamboohr-personnel", fixture_dir=_write_hr_fixture(tmp_path / "hr")
    )
    derived = [r for r in read_jsonl(raw_path) if r.get("connector_id") == TRAINING_COVERAGE_CONNECTOR_ID]
    assert {e: r["status"] for e, r in _by_email(derived).items()} == {
        "ada@example.com": "pass",
        "alan@example.com": "open",
    }
    assert _summary(derived)["attributes"]["statement"].startswith("1 of 2 active personnel")
    safeguard, requirements = _assessment(lake)
    assert (safeguard["status"], safeguard["assessed_asset_count"], safeguard["unassessed_asset_count"]) == (
        "fail",
        2,
        0,
    )

    # alan completes; the next training sync clears the finding
    connector_runner.run_connector_sync(
        lake,
        connector_id=CONNECTOR_ID,
        fixture_dir=_write_training_fixture(tmp_path / "t2", alan_completed=True),
    )
    safeguard, requirements = _assessment(lake)
    assert safeguard["status"] == "pass"
    # reviewed crosswalk members follow the safeguard; proposed ones never attest
    assert requirements["CMMC-3.2.1"]["status"] == "pass"
    assert requirements["ISO27001-A.6.3"]["status"] != "pass"
    assert requirements["ISO27001-A.6.3"]["pending_mapping_count"] >= 1
    assert all(r.get("attributes", {}).get("synthetic") for r in read_jsonl(raw_path))


def test_failed_sync_keeps_prior_evidence_and_records_an_error(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    _enable(lake)
    connector_runner.run_connector_sync(
        lake,
        connector_id=CONNECTOR_ID,
        fixture_dir=_write_training_fixture(tmp_path / "good", alan_completed=True),
        materialize=False,
    )
    raw_path = lake / connector_runner.CONNECTOR_RAW_FILE
    before = raw_path.read_bytes()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "export.csv").write_text(HEADER)
    with pytest.raises(connector_runner.ConnectorSyncError, match="no training records"):
        connector_runner.run_connector_sync(lake, connector_id=CONNECTOR_ID, fixture_dir=broken, materialize=False)
    assert raw_path.read_bytes() == before
    run = latest_run(lake, CONNECTOR_ID, kind="sync")
    assert run["result"] == "error"
    assert "example.com" not in json.dumps(run)


# --- local export path boundary --------------------------------------------------------


def _write_export(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "export.csv").write_text(HEADER + "ada@example.com,101,SAT,,,,2026-05-01,completed,,\n")
    return directory


def test_live_path_is_confined_to_the_local_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    inside = _write_export(root / "lms")
    outside = _write_export(tmp_path / "elsewhere")
    build = connector_runner.REGISTRY[CONNECTOR_ID]

    def inputs(path: Path, env: dict[str, str]) -> connector_runner.SyncInputs:
        return connector_runner.SyncInputs(
            repo=None, fixture_dir=None, token_env="", env=env, credentials={"path": str(path)}
        )

    with pytest.raises(ValueError, match=local_paths.LOCAL_ROOT_ENV):
        build(inputs(inside, {}))
    env = {local_paths.LOCAL_ROOT_ENV: str(root)}
    assert len(build(inputs(inside, env))) == 1
    with pytest.raises(ValueError, match="outside"):
        build(inputs(outside, env))
    with pytest.raises(ValueError, match="outside"):
        build(inputs(root / "lms" / ".." / ".." / "elsewhere", env))
    with pytest.raises(ValueError, match="credentials.path"):
        build(connector_runner.SyncInputs(repo=None, fixture_dir=None, token_env="", env=env))


def test_hosted_tenants_read_only_their_own_export_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    own = _write_export(root / "tenant-a" / "lms")
    other = _write_export(root / "tenant-b" / "lms")
    build = connector_runner.REGISTRY[CONNECTOR_ID]
    env = {local_paths.LOCAL_ROOT_ENV: str(root)}

    def inputs(path: Path) -> connector_runner.SyncInputs:
        return connector_runner.SyncInputs(
            repo=None, fixture_dir=None, token_env="", env=env, credentials={"path": str(path)}
        )

    with server_execution("tenant-a"):
        assert len(build(inputs(own))) == 1
        with pytest.raises(ValueError, match="tenant"):
            build(inputs(other))
