"""Collect public observations before publishing through the assessment boundary."""

from pathlib import Path
from urllib.parse import urlencode

from security_lakehouse import repo_audit
from security_lakehouse.connector_runner import CONNECTOR_RAW_FILE, _upsert_raw_events
from security_lakehouse.generations import active_generation, publication_lock, verify_generation
from security_lakehouse.investigation_graph import _id
from security_lakehouse.io import canonical_sha256, read_jsonl, write_jsonl
from security_lakehouse.services.assessments import AssessmentContext, EvaluationCommand, evaluate


def validate_request(payload: dict) -> str:
    if payload.keys() - {"repo", "actor", "idempotency_key"} or not isinstance(payload.get("repo"), str):
        raise ValueError("provide only a public GitHub repository URL; credentials and local paths are not accepted")
    if len(payload["repo"]) > 220:
        raise ValueError("repository URL exceeds 220 characters")
    return repo_audit.parse_repo_spec(payload["repo"]).slug


def collect(lake: Path, repo: str, *, actor: str) -> tuple[dict, dict, bool]:
    # No persisted evidence is touched until every bounded provider read succeeds.
    rows = repo_audit.audit_public_repo(repo)
    spec = repo_audit.parse_repo_spec(repo)
    account = f"github:{spec.owner}"
    owner = "github-public-repo-" + canonical_sha256(spec.slug)[:16]
    with publication_lock(lake):
        raw = lake / CONNECTOR_RAW_FILE
        if not raw.exists() and (generation := active_generation(lake)) is not None:
            # A first URL audit must not discard a lake originally imported via CLI.
            verify_generation(generation)
            write_jsonl(raw, [row["raw"] for row in read_jsonl(generation / "bronze/raw_events.jsonl")])
        _upsert_raw_events(raw, rows, connector_id=owner, write_mode="snapshot")
        assessment = evaluate(lake, EvaluationCommand(), AssessmentContext(actor=actor))
    attributes = rows[0]["attributes"]
    root = _id("asset", account, spec.asset_id)
    return (
        {
            "repo": spec.slug,
            "provider": "github",
            "source_account_id": account,
            "source_commit": attributes["source_commit"],
            "source_ref": attributes["source_ref"],
            "observation_id": attributes["observation_id"],
            "observed_at": rows[0]["event_time"],
            "synthetic": attributes["synthetic"],
            "evidence_count": len(rows),
            "graph_root": root,
            "investigate_href": "/graph/?" + urlencode({"root": root}),
        },
        assessment.outcome,
        assessment.succeeded,
    )
