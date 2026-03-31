"""add is_free to google calendars

Revision ID: e8a1f93d4b21
Revises: c2b9a4f1c8d7
Create Date: 2026-03-31 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8a1f93d4b21"
down_revision: Union[str, None] = "c2b9a4f1c8d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "google_calendars",
        sa.Column("is_free", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.alter_column("google_calendars", "is_free", server_default=None)


def downgrade() -> None:
    op.drop_column("google_calendars", "is_free")
