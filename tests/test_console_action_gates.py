"""Console actions must be offered only where the server will accept them."""

from __future__ import annotations

from pathlib import Path

from security_lakehouse.auth.rbac import ROLE_SCOPES

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web" / "src" / "app"


def test_workflow_run_stays_with_contributor_and_the_role_table_says_so() -> None:
    """Approving (workflow_manage) and triggering (workflow_run) stay in
    different roles so an approver cannot also start the run; admins are told."""
    runners = {role for role, scopes in ROLE_SCOPES.items() if "workflow_run" in scopes}
    approvers = {role for role, scopes in ROLE_SCOPES.items() if "workflow_manage" in scopes}
    assert runners == {"contributor"}
    assert runners.isdisjoint(approvers)
    table = (ROOT / "docs" / "SERVER_AUTH.md").read_text(encoding="utf-8")
    admin_row = next(line for line in table.splitlines() if line.startswith("| `admin`"))
    assert "workflow_run" in admin_row


def test_automation_page_gates_run_on_the_workflow_run_scope() -> None:
    page = (WEB / "automation" / "page.tsx").read_text(encoding="utf-8")
    assert 'scopes.includes("workflow_run")' in page
    assert page.count("canRun") >= 3, "Preview and Run buttons and the explanation must use the gate"


def test_mapping_review_page_requires_an_interactive_session_to_decide() -> None:
    page = (WEB / "mapping-review" / "page.tsx").read_text(encoding="utf-8")
    assert 'scopes.includes("mapping_review")' in page
    assert "auth_method" in page and '"session:oidc", "session:saml"' in page
