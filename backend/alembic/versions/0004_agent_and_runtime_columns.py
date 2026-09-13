"""V1.1/V1.2: agents reference models by model_id; multi-runtime columns.

Revision ID: 0004_agent_and_runtime
Revises: 0003_model_runtime
Create Date: 2026-09-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_agent_and_runtime"
down_revision = "0003_model_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("model_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("models") as batch:
        batch.add_column(sa.Column("supported_runtimes", sa.Text(), nullable=True))
        batch.add_column(sa.Column("preferred_runtime", sa.String(length=64), nullable=True))
    op.create_index("ix_agents_model_id", "agents", ["model_id"], if_not_exists=True)
    op.create_index("ix_models_preferred_runtime", "models", ["preferred_runtime"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_models_preferred_runtime", table_name="models", if_exists=True)
    op.drop_index("ix_agents_model_id", table_name="agents", if_exists=True)
    with op.batch_alter_table("models") as batch:
        batch.drop_column("preferred_runtime")
        batch.drop_column("supported_runtimes")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("model_id")
