"""V4.0: OS core resource/process/event/skill tables.

Revision ID: 0008_os_core
Revises: 0007_learning_goals
Create Date: 2026-09-14
"""
from __future__ import annotations

import models.records  # noqa: F401 -- register mappings
from alembic import op
from core.database import Base

revision = "0008_os_core"
down_revision = "0007_learning_goals"
branch_labels = None
depends_on = None

_TABLE_NAMES = (
    "os_resources",
    "os_processes",
    "os_events",
    "event_rules",
    "agent_skills",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLE_NAMES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
