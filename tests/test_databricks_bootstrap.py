"""Execute bootstrap projections locally with documented SQL-function adapters.

DuckDB is a bounded SQL regression harness, not Databricks runtime qualification.
"""

from pathlib import Path

import pytest


def _bootstrap(response_field, codes):
    import duckdb

    db = duckdb.connect()
    db.execute("CREATE MACRO get_json_object(value, path) AS json_extract_string(value, path)")
    db.execute("CREATE MACRO date_sub(value, days) AS value - CAST(days AS INTEGER)")
    db.execute("CREATE MACRO sha2(value, bits) AS sha256(value)")
    db.execute(
        f"CREATE TABLE audit_source (event_id VARCHAR, user_identity STRUCT(email VARCHAR), "
        f"service_name VARCHAR, action_name VARCHAR, response STRUCT({response_field} INTEGER), "
        "request_id VARCHAR, event_time TIMESTAMP, event_date DATE, workspace_id VARCHAR)"
    )
    for index, code in enumerate(codes):
        db.execute(
            "INSERT INTO audit_source VALUES (?, {'email': 'reader@example.com'}, 'sql', 'execute', "
            f"{{'{response_field}': ?}}, 'request', CURRENT_TIMESTAMP, CURRENT_DATE, 'synthetic-workspace')",
            [f"event-{index}", code],
        )
    source = (Path(__file__).resolve().parents[1] / "deploy/databricks/bootstrap_poc.sql").read_text()
    source = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("--"))
    for statement in source.split(";"):
        if statement.strip().startswith("CREATE OR REPLACE VIEW"):
            db.execute(statement.replace("trustops.evidence.", "").replace("system.access.audit", "audit_source"))
    return db


@pytest.mark.parametrize("response_field", ["statusCode", "status_code"])
@pytest.mark.parametrize(
    "codes, expected",
    [
        ([], "not_evaluated"),
        ([200], "passed"),
        ([403], "open"),
        ([None], "not_evaluated"),
        ([200, None], "not_evaluated"),
        ([403, None], "open"),
    ],
)
def test_audit_schema_variants_and_missing_results_never_invent_a_verdict(response_field, codes, expected):
    with _bootstrap(response_field, codes) as db:
        rows = db.execute("SELECT control_id, status, risk_score FROM GRC_LAKE_CONTROL_POSTURE").fetchall()
        by_control = {row[0]: row[1:] for row in rows}
        denied = by_control["DATABRICKS-DENIED-ACCESS-REVIEW"]
        assert denied[0] == expected
        if expected == "not_evaluated":
            assert denied[1] is None
        assert by_control["DATABRICKS-AUDIT-LOGGING"][0] == ("passed" if codes else "not_evaluated")
        for name in ("AUDIT_EVENTS", "EVIDENCE_BUNDLES"):
            assert db.execute(f"SELECT count(*) FROM GRC_LAKE_{name}").fetchone()[0] == len(codes)


def test_unknown_response_schema_is_not_evaluated():
    with _bootstrap("unknown_field", [200]) as db:
        row = db.execute(
            "SELECT status FROM GRC_LAKE_CONTROL_POSTURE WHERE control_id = 'DATABRICKS-DENIED-ACCESS-REVIEW'"
        ).fetchone()
        assert row == ("not_evaluated",)
