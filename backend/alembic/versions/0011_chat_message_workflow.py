"""Add chat message pin workflow fields.

Revision ID: 0011_chat_message_workflow
Revises: 0010_merge_heads
Create Date: 2026-09-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0011_chat_message_workflow"
down_revision = "0010_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    if "is_pinned" not in message_columns:
        op.add_column("messages", sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "pinned_at" not in message_columns:
        op.add_column("messages", sa.Column("pinned_at", sa.DateTime(), nullable=True))
    op.create_index("ix_messages_is_pinned", "messages", ["is_pinned"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_messages_is_pinned", table_name="messages")
    op.drop_column("messages", "pinned_at")
    op.drop_column("messages", "is_pinned")
