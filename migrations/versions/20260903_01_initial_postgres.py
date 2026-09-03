"""Initial PostgreSQL schema for chats, announcements and reminders."""

from alembic import op
import sqlalchemy as sa


revision = "20260903_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("user_id", "channel_id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )
    op.create_index("idx_messages_conversation", "messages", ["user_id", "channel_id", "id"])

    op.create_table(
        "announcements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "announcement_channels",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("announcement_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("discord_message_id", sa.BigInteger()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("announcement_id", "channel_id", name="uq_announcement_channel"),
    )
    op.create_index("idx_announcement_channels_pending", "announcement_channels", ["status", "scheduled_for"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("announcement_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_role_id", sa.BigInteger()),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_reminders_pending", "reminders", ["status", "scheduled_for"])
    op.create_table(
        "reminder_recipients",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("reminder_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.ForeignKeyConstraint(["reminder_id"], ["reminders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reminder_id", "user_id", name="uq_reminder_recipient"),
    )
    op.create_index("idx_reminder_recipients_pending", "reminder_recipients", ["reminder_id", "status"])
    op.create_table(
        "data_imports",
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("source"),
    )


def downgrade() -> None:
    op.drop_table("data_imports")
    op.drop_index("idx_reminder_recipients_pending", table_name="reminder_recipients")
    op.drop_table("reminder_recipients")
    op.drop_index("idx_reminders_pending", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index("idx_announcement_channels_pending", table_name="announcement_channels")
    op.drop_table("announcement_channels")
    op.drop_table("announcements")
    op.drop_index("idx_messages_conversation", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
