"""V3.3/V3.4: agent learning and autonomous goal tables.

Revision ID: 0007_learning_goals
Revises: 0006_agent_teams
Create Date: 2026-09-14
"""
from __future__ import annotations

import models.records  # noqa: F401 -- register mappings
from alembic import op
from core.database import Base

revision = "0007_learning_goals"
down_revision = "0006_agent_teams"
branch_labels = None
depends_on = None

_TABLE_NAMES = (
    "agent_experiences",
    "experience_episodes",
    "experience_steps",
    "experience_outcomes",
    "experience_evaluations",
    "goals",
    "sub_goals",
    "approval_policies",
    "approval_requests",
    "approval_decisions",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLE_NAMES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
