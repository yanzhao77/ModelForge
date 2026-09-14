"""V1.1/V1.2: agents reference models by model_id; multi-runtime columns.

Revision ID: 0004_agent_and_runtime
Revises: 0003_model_runtime
Create Date: 2026-09-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_agent_and_runtime"
down_revision = "0003_model_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    agent_columns = {column["name"] for column in inspector.get_columns("agents")}
    agent_additions = [
        ("model_id", sa.Column("model_id", sa.Integer(), nullable=True)),
        ("updated_at", sa.Column("updated_at", sa.DateTime(), nullable=True)),
    ]
    missing_agent_columns = [column for name, column in agent_additions if name not in agent_columns]
    if missing_agent_columns:
        with op.batch_alter_table("agents") as batch:
            for column in missing_agent_columns:
                batch.add_column(column)

    model_columns = {column["name"] for column in inspector.get_columns("models")}
    model_additions = [
        ("supported_runtimes", sa.Column("supported_runtimes", sa.Text(), nullable=True)),
        ("preferred_runtime", sa.Column("preferred_runtime", sa.String(length=64), nullable=True)),
    ]
    missing_model_columns = [column for name, column in model_additions if name not in model_columns]
    if missing_model_columns:
        with op.batch_alter_table("models") as batch:
            for column in missing_model_columns:
                batch.add_column(column)
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
