"""Add an optional end date to recurring announcements."""

from alembic import op
import sqlalchemy as sa


revision = "20260914_04"
down_revision = "20260914_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("announcements", sa.Column("recurrence_until", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("announcements", "recurrence_until")
