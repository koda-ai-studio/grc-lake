"""Exercise real migrations and model parity on disposable databases."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from security_lakehouse.db.migrate import _config


@pytest.fixture(params=["sqlite", "postgresql"])
def migration_url(request, tmp_path: Path):
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'state.sqlite'}"
        return
    configured = os.environ.get("TEST_POSTGRES_URL")
    if not configured:
        pytest.skip("TEST_POSTGRES_URL is required for the PostgreSQL migration gate")
    name = "trustops_test_" + uuid.uuid4().hex
    admin = create_engine(configured, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(configured).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_upgrade_downgrade_upgrade_has_no_model_drift(migration_url):
    cfg = _config(migration_url)
    command.upgrade(cfg, "head")
    command.check(cfg)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    command.check(cfg)


def test_upgrade_preserves_existing_tenant_and_user(migration_url):
    cfg = _config(migration_url)
    command.upgrade(cfg, "0020_saml_assertion_replays")
    engine = create_engine(migration_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO tenants (id, slug, name) VALUES ('t', 'example', 'Example')"))
            conn.execute(text("INSERT INTO users (id, tenant_id, email) VALUES ('u', 't', 'u@example.test')"))
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT email FROM users WHERE id = 'u'")).scalar_one() == "u@example.test"
        command.check(cfg)
    finally:
        engine.dispose()


def test_governance_composite_references_reject_foreign_tenant(migration_url):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from security_lakehouse.db.models import GovernanceDecision, GovernanceReview, Tenant

    cfg = _config(migration_url)
    command.upgrade(cfg, "head")
    engine = create_engine(migration_url)
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(text("PRAGMA foreign_keys=ON"))
                conn.commit()
            with Session(conn) as session:
                session.add_all(
                    [Tenant(id="t-a", slug="tenant-a", name="A"), Tenant(id="t-b", slug="tenant-b", name="B")]
                )
                session.commit()
                session.add(
                    GovernanceDecision(
                        id="d",
                        tenant_id="t-a",
                        content_json="{}",
                        content_sha256="a" * 64,
                        created_by_id="u",
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                )
                session.commit()
                session.add(
                    GovernanceReview(
                        tenant_id="t-b",
                        decision_id="d",
                        slot="decision",
                        action="approve",
                        rationale="Invalid cross-tenant review",
                        content_sha256="a" * 64,
                        reviewer_id="r",
                        auth_method="session:oidc",
                    )
                )
                with pytest.raises(IntegrityError):
                    session.commit()
                session.rollback()
                assert session.get(GovernanceDecision, "d").tenant_id == "t-a"
    finally:
        engine.dispose()
