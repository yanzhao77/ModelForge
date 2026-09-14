"""Multimodal chat attachment, turn, event, and artifact tables.

Revision ID: 0009_multimodal_chat_foundation
Revises: 0008_os_core
Create Date: 2026-09-14
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0009_multimodal_chat_foundation"
down_revision = "0008_os_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    message_columns = {column["name"] for column in inspector.get_columns("messages")}
    for name, column in (
        ("schema_version", sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1")),
        ("parts_json", sa.Column("parts_json", sa.Text(), nullable=True)),
        ("status", sa.Column("status", sa.String(length=32), nullable=False, server_default="completed")),
        ("turn_id", sa.Column("turn_id", sa.String(length=64), nullable=True)),
        ("parent_message_id", sa.Column("parent_message_id", sa.Integer(), nullable=True)),
    ):
        if name not in message_columns:
            op.add_column("messages", column)
    op.create_index("ix_messages_status", "messages", ["status"], if_not_exists=True)
    op.create_index("ix_messages_turn_id", "messages", ["turn_id"], if_not_exists=True)
    op.create_index("ix_messages_parent_message_id", "messages", ["parent_message_id"], if_not_exists=True)

    if not inspector.has_table("attachments"):
        op.create_table(
            "attachments",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("display_name", sa.String(length=512), nullable=False),
            sa.Column("storage_key", sa.String(length=1024), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False, index=True),
            sa.Column("mime_type", sa.String(length=128), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("state", sa.String(length=32), nullable=False, server_default="READY", index=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
    op.create_index("ix_attachments_user_state", "attachments", ["user_id", "state"], if_not_exists=True)
    op.create_index("ix_attachments_user_created", "attachments", ["user_id", "created_at"], if_not_exists=True)

    if not inspector.has_table("attachment_derivatives"):
        op.create_table(
            "attachment_derivatives",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("source_attachment_id", sa.String(length=64), sa.ForeignKey("attachments.id"), nullable=False, index=True),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("processor_version", sa.String(length=64), nullable=False, server_default="builtin-v1"),
            sa.Column("selection_json", sa.Text(), nullable=True),
            sa.Column("storage_key", sa.String(length=1024), nullable=True),
            sa.Column("state", sa.String(length=32), nullable=False, server_default="SUCCEEDED", index=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(length=96), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    op.create_index("ix_attachment_derivatives_source_kind", "attachment_derivatives", ["source_attachment_id", "kind"], if_not_exists=True)

    if not inspector.has_table("message_attachments"):
        op.create_table(
            "message_attachments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False, index=True),
            sa.Column("attachment_id", sa.String(length=64), sa.ForeignKey("attachments.id"), nullable=False, index=True),
            sa.Column("scope", sa.String(length=32), nullable=False, server_default="message"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("message_id", "attachment_id", name="uq_message_attachment"),
        )

    if not inspector.has_table("chat_turns"):
        op.create_table(
            "chat_turns",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True, index=True),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="QUEUED", index=True),
            sa.Column("mode", sa.String(length=32), nullable=False, server_default="chat"),
            sa.Column("user_message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
            sa.Column("context_manifest_json", sa.Text(), nullable=True),
            sa.Column("capability_snapshot_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "idempotency_key", name="uq_chat_turn_user_idempotency"),
        )
    op.create_index("ix_chat_turns_session_status", "chat_turns", ["session_id", "status"], if_not_exists=True)

    if not inspector.has_table("chat_attempts"):
        op.create_table(
            "chat_attempts",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("turn_id", sa.String(length=64), sa.ForeignKey("chat_turns.id"), nullable=False, index=True),
            sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("output_message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
            sa.Column("run_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("job_id", sa.String(length=64), nullable=True, index=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="QUEUED", index=True),
            sa.Column("usage_json", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(length=96), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("turn_id", "attempt_no", name="uq_chat_attempt_turn_no"),
        )

    if not inspector.has_table("chat_events"):
        op.create_table(
            "chat_events",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("turn_id", sa.String(length=64), sa.ForeignKey("chat_turns.id"), nullable=False, index=True),
            sa.Column("attempt_id", sa.String(length=64), sa.ForeignKey("chat_attempts.id"), nullable=True, index=True),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_key", sa.String(length=160), nullable=False),
            sa.Column("type", sa.String(length=96), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("correlation_id", sa.String(length=96), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("turn_id", "sequence", name="uq_chat_event_turn_sequence"),
            sa.UniqueConstraint("turn_id", "event_key", name="uq_chat_event_turn_key"),
        )

    if not inspector.has_table("artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True, index=True),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True, index=True),
            sa.Column("name", sa.String(length=512), nullable=False),
            sa.Column("artifact_type", sa.String(length=64), nullable=False, server_default="file"),
            sa.Column("producer_ref", sa.String(length=128), nullable=True),
            sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    op.create_index("ix_artifacts_session_created", "artifacts", ["session_id", "created_at"], if_not_exists=True)

    if not inspector.has_table("artifact_versions"):
        op.create_table(
            "artifact_versions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("artifact_id", sa.String(length=64), sa.ForeignKey("artifacts.id"), nullable=False, index=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("attachment_id", sa.String(length=64), sa.ForeignKey("attachments.id"), nullable=False, index=True),
            sa.Column("parent_version", sa.Integer(), nullable=True),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),
        )


def downgrade() -> None:
    for table_name in (
        "artifact_versions",
        "artifacts",
        "chat_events",
        "chat_attempts",
        "chat_turns",
        "message_attachments",
        "attachment_derivatives",
        "attachments",
    ):
        op.drop_table(table_name)
    op.drop_index("ix_messages_parent_message_id", table_name="messages")
    op.drop_index("ix_messages_turn_id", table_name="messages")
    op.drop_index("ix_messages_status", table_name="messages")
    for column in ("parent_message_id", "turn_id", "status", "parts_json", "schema_version"):
        op.drop_column("messages", column)
