"""add google accounts and calendars

Revision ID: c2b9a4f1c8d7
Revises: 856f2c078717
Create Date: 2026-03-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c2b9a4f1c8d7"
down_revision: Union[str, None] = "856f2c078717"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "google_accounts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("google_account_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expiry", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "google_account_id", name="uq_google_account_user_sub"),
    )
    op.create_index(op.f("ix_google_accounts_user_id"), "google_accounts", ["user_id"], unique=False)

    op.create_table(
        "google_calendars",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("google_calendar_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("access_role", sa.String(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["google_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "google_calendar_id", name="uq_google_calendar_account_id"),
    )
    op.create_index(op.f("ix_google_calendars_account_id"), "google_calendars", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_google_calendars_account_id"), table_name="google_calendars")
    op.drop_table("google_calendars")
    op.drop_index(op.f("ix_google_accounts_user_id"), table_name="google_accounts")
    op.drop_table("google_accounts")
