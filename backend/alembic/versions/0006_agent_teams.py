"""V3.1: multi-agent team tables.

Revision ID: 0006_agent_teams
Revises: 0005_platform_tables
Create Date: 2026-09-14
"""
from __future__ import annotations

import models.records  # noqa: F401 -- register mappings
from alembic import op
from core.database import Base

revision = "0006_agent_teams"
down_revision = "0005_platform_tables"
branch_labels = None
depends_on = None

_TABLE_NAMES = (
    "agent_teams",
    "agent_team_members",
    "agent_team_runs",
    "agent_team_tasks",
    "agent_delegations",
    "agent_team_messages",
    "agent_team_events",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLE_NAMES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
