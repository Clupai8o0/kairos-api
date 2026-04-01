"""add recurrence fields to tasks

Revision ID: b4d7e2f9c031
Revises: f3c2a1d9e847
Create Date: 2026-04-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4d7e2f9c031"
down_revision: Union[str, None] = "f3c2a1d9e847"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "recurrence_rule",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "parent_task_id",
            sa.String(),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("recurrence_index", sa.Integer(), nullable=True),
    )
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    op.drop_column("tasks", "recurrence_index")
    op.drop_column("tasks", "parent_task_id")
    op.drop_column("tasks", "recurrence_rule")
