"""V1.5/V1.7/V1.8: workflows, packages and evaluation tables.

Revision ID: 0005_platform_tables
Revises: 0004_agent_and_runtime
Create Date: 2026-09-13
"""
from __future__ import annotations

import models.records  # noqa: F401 -- register mappings
from alembic import op
from core.database import Base

revision = "0005_platform_tables"
down_revision = "0004_agent_and_runtime"
branch_labels = None
depends_on = None

_TABLE_NAMES = (
    "workflows",
    "workflow_runs",
    "workflow_run_events",
    "platform_packages",
    "evaluation_datasets",
    "evaluation_runs",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLE_NAMES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
