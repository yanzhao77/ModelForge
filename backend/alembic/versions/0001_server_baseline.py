"""Create the ModelForge server baseline schema.

Revision ID: 0001_server_baseline
Revises:
Create Date: 2026-08-28
"""
from __future__ import annotations

from alembic import op

from core.database import Base
import models.records  # noqa: F401 -- register mappings

revision = "0001_server_baseline"
down_revision = None
branch_labels = None
depends_on = None


_POST_BASELINE_TABLES = {
    "organizations", "api_projects", "project_api_keys", "api_invocations",
    "project_quotas", "usage_ledger", "project_agent_bindings",
}


def upgrade() -> None:
    """Create the complete schema available at the server baseline revision."""
    tables = [table for name, table in Base.metadata.tables.items() if name not in _POST_BASELINE_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    """Drop the server baseline schema; use only for a disposable deployment."""
    Base.metadata.drop_all(bind=op.get_bind())
