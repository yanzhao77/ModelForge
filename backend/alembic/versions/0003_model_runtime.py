"""Add unified model-registry columns (capabilities, metadata, lineage).

Revision ID: 0003_model_runtime
Revises: 0002_api_platform
Create Date: 2026-09-13

The model registry stores capabilities and metadata as JSON text so the same
migration works on PostgreSQL and SQLite. Existing rows are backfilled from
their ``format`` column; rows whose format is unknown are marked
``["INFERENCE"]`` rather than guessed as trainable.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_model_runtime"
down_revision = "0002_api_platform"
branch_labels = None
depends_on = None

_CAPABILITY_BACKFILL = """
UPDATE models
   SET capabilities = CASE
       WHEN lower(coalesce(format, '')) IN ('gguf', 'ggml') THEN '["CHAT","INFERENCE"]'
       WHEN lower(coalesce(format, '')) IN ('peft-adapter', 'lora', 'adapter') THEN '["LORA"]'
       WHEN lower(coalesce(format, '')) IN ('safetensors', 'transformers', 'pytorch', 'bin', 'pt', 'pth')
            THEN '["CHAT","INFERENCE","TRAINING","LORA"]'
       ELSE '["INFERENCE"]'
   END
 WHERE capabilities IS NULL
"""


def upgrade() -> None:
    with op.batch_alter_table("models") as batch:
        batch.add_column(sa.Column("display_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("capabilities", sa.Text(), nullable=True))
        batch.add_column(sa.Column("model_metadata", sa.Text(), nullable=True))
        batch.add_column(sa.Column("base_model_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("parent_model_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("updated_time", sa.DateTime(), nullable=True))
    op.create_index("ix_models_status", "models", ["status"], if_not_exists=True)
    op.create_index("ix_models_base_model_id", "models", ["base_model_id"], if_not_exists=True)
    op.execute(_CAPABILITY_BACKFILL)


def downgrade() -> None:
    op.drop_index("ix_models_base_model_id", table_name="models", if_exists=True)
    op.drop_index("ix_models_status", table_name="models", if_exists=True)
    with op.batch_alter_table("models") as batch:
        batch.drop_column("updated_time")
        batch.drop_column("parent_model_id")
        batch.drop_column("base_model_id")
        batch.drop_column("model_metadata")
        batch.drop_column("capabilities")
        batch.drop_column("size_bytes")
        batch.drop_column("display_name")
