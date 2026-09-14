"""Add video generation job persistence.

Revision ID: 0003_video_jobs
Revises: 0002_api_platform
Create Date: 2026-09-11
"""
from __future__ import annotations

import models.records  # noqa: F401 -- register mappings
from alembic import op
from core.database import Base

revision = "0003_video_jobs"
down_revision = "0002_api_platform"
branch_labels = None
depends_on = None

_TABLE_NAMES = ("video_jobs",)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in _TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    bind = op.get_bind()
    for name in reversed(_TABLE_NAMES):
        Base.metadata.tables[name].drop(bind=bind, checkfirst=True)
