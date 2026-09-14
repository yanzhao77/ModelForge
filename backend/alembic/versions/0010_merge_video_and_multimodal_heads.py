"""Merge video job and multimodal chat migration heads.

Revision ID: 0010_merge_heads
Revises: 0009_multimodal_chat_foundation, 0003_video_jobs
Create Date: 2026-09-14
"""
from __future__ import annotations

revision = "0010_merge_heads"
down_revision = ("0009_multimodal_chat_foundation", "0003_video_jobs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
