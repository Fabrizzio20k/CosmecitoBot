"""Persist the selected weekdays for recurring announcements."""

from alembic import op
import sqlalchemy as sa


revision = "20260914_05"
down_revision = "20260914_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "announcements",
        sa.Column("recurrence_weekdays", sa.String(length=13), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("announcements", "recurrence_weekdays")
