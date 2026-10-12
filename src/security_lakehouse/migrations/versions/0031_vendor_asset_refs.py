"""Explicit source-account asset references for vendor assessments."""

import sqlalchemy as sa
from alembic import op

revision = "0031_vendor_asset_refs"
down_revision = "0030_governance_records"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("vendor_assessments", sa.Column("asset_refs_json", sa.Text(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("vendor_assessments", "asset_refs_json")
