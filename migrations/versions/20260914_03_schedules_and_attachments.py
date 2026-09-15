"""Add recurrence metadata and persisted message attachments."""

from alembic import op
import sqlalchemy as sa


revision = "20260914_03"
down_revision = "20260905_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("announcements", sa.Column("recurrence", sa.String(length=16), server_default="once", nullable=False))
    op.add_column("announcements", sa.Column("recurrence_scheduled_at", sa.DateTime(timezone=True)))
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("announcement_id", sa.Uuid()),
        sa.Column("reminder_id", sa.Uuid()),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255)),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(announcement_id IS NOT NULL AND reminder_id IS NULL) OR "
            "(announcement_id IS NULL AND reminder_id IS NOT NULL)",
            name="ck_message_attachment_owner",
        ),
    )
    op.create_index("idx_message_attachments_announcement", "message_attachments", ["announcement_id"])
    op.create_index("idx_message_attachments_reminder", "message_attachments", ["reminder_id"])


def downgrade() -> None:
    op.drop_index("idx_message_attachments_reminder", table_name="message_attachments")
    op.drop_index("idx_message_attachments_announcement", table_name="message_attachments")
    op.drop_table("message_attachments")
    op.drop_column("announcements", "recurrence_scheduled_at")
    op.drop_column("announcements", "recurrence")
