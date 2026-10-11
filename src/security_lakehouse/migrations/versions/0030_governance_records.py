"""Add scoped implementation revisions and independently reviewed risk decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0030_governance_records"
down_revision = "0029_distributed_scaling"
branch_labels = None
depends_on = None


def _markers():
    return revision, down_revision, branch_labels, depends_on


def _identity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _content():
    return [
        sa.Column("supersedes_id", sa.String(36)),
        sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_by_id", sa.String(36), nullable=False),
    ]


def upgrade():
    _markers()
    op.create_table(
        "safeguard_implementations",
        *_identity(),
        *_content(),
        sa.Column("safeguard_id", sa.String(128), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_safeguard_impl_tenant_id"),
        sa.UniqueConstraint("tenant_id", "supersedes_id", name="uq_safeguard_impl_successor"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supersedes_id"],
            ["safeguard_implementations.tenant_id", "safeguard_implementations.id"],
            name="fk_impl_successor_tenant",
        ),
    )
    op.create_table(
        "governance_decisions",
        *_identity(),
        *_content(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_governance_decision_tenant_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supersedes_id"],
            ["governance_decisions.tenant_id", "governance_decisions.id"],
            name="fk_decision_successor_tenant",
        ),
    )
    op.create_table(
        "governance_reviews",
        *_identity(),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("replaces_id", sa.String(36)),
        sa.Column("slot", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("auth_method", sa.String(32), nullable=False),
        sa.UniqueConstraint("tenant_id", "decision_id", "slot", name="uq_governance_review_slot"),
        sa.UniqueConstraint("tenant_id", "replaces_id", name="uq_governance_approved_successor"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "decision_id"],
            ["governance_decisions.tenant_id", "governance_decisions.id"],
            name="fk_review_decision_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "replaces_id"],
            ["governance_decisions.tenant_id", "governance_decisions.id"],
            name="fk_review_replaces_tenant",
        ),
    )
    for table in ("safeguard_implementations", "governance_decisions", "governance_reviews"):
        op.create_index("ix_" + table + "_tenant_id", table, ["tenant_id"])
    op.create_index("ix_governance_reviews_decision_id", "governance_reviews", ["decision_id"])


def downgrade():
    _markers()
    # Explicit rollback retains a clear boundary: export records before downgrade.
    for table in ("governance_reviews", "governance_decisions", "safeguard_implementations"):
        op.drop_table(table)
