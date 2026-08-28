"""Add project-scoped Agent API control-plane tables.

Revision ID: 0002_api_platform
Revises: 0001_server_baseline
Create Date: 2026-08-28
"""
from __future__ import annotations

from alembic import op

from core.database import Base
import models.records  # noqa: F401 -- register mappings

revision = "0002_api_platform"
down_revision = "0001_server_baseline"
branch_labels = None
depends_on = None

_TABLE_NAMES = (
    "organizations", "api_projects", "project_api_keys", "api_invocations",
    "project_quotas", "usage_ledger", "project_agent_bindings",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLE_NAMES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
