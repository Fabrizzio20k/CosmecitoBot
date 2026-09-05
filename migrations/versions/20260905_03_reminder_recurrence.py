"""Add recurrence metadata to reminder deliveries."""

from alembic import op
import sqlalchemy as sa


revision = "20260905_03"
down_revision = "20260904_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminders", sa.Column("recurrence", sa.String(length=16), server_default="once", nullable=False))
    op.add_column("reminders", sa.Column("recurrence_interval", sa.Integer(), server_default="1", nullable=False))
    op.add_column("reminders", sa.Column("recurrence_weekdays", sa.String(length=13), server_default="", nullable=False))
    op.add_column("reminders", sa.Column("recurrence_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reminders", sa.Column("recurrence_group_id", sa.Uuid(), nullable=True))
    op.create_index("idx_reminders_recurrence_group", "reminders", ["recurrence_group_id"])


def downgrade() -> None:
    op.drop_index("idx_reminders_recurrence_group", table_name="reminders")
    op.drop_column("reminders", "recurrence_group_id")
    op.drop_column("reminders", "recurrence_until")
    op.drop_column("reminders", "recurrence_weekdays")
    op.drop_column("reminders", "recurrence_interval")
    op.drop_column("reminders", "recurrence")
