from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")


class ChatMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_conversation", "user_id", "channel_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="scheduled", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    channels: Mapped[list[AnnouncementChannel]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan"
    )
    reminders: Mapped[list[Reminder]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan"
    )


class AnnouncementChannel(Base):
    __tablename__ = "announcement_channels"
    __table_args__ = (
        UniqueConstraint("announcement_id", "channel_id", name="uq_announcement_channel"),
        Index("idx_announcement_channels_pending", "status", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    announcement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    announcement: Mapped[Announcement] = relationship(back_populates="channels")


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index("idx_reminders_pending", "status", "scheduled_for"),
        Index("idx_reminders_recurrence_group", "recurrence_group_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("announcements.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_role_id: Mapped[int | None] = mapped_column(BigInteger)
    recurrence: Mapped[str] = mapped_column(String(16), default="once", nullable=False)
    recurrence_interval: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    recurrence_weekdays: Mapped[str] = mapped_column(String(13), default="", nullable=False)
    recurrence_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recurrence_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(24), default="scheduled", nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    announcement: Mapped[Announcement | None] = relationship(back_populates="reminders")
    recipients: Mapped[list[ReminderRecipient]] = relationship(
        back_populates="reminder", cascade="all, delete-orphan"
    )


class ReminderRecipient(Base):
    __tablename__ = "reminder_recipients"
    __table_args__ = (
        UniqueConstraint("reminder_id", "user_id", name="uq_reminder_recipient"),
        Index("idx_reminder_recipients_pending", "reminder_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    reminder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="direct", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    reminder: Mapped[Reminder] = relationship(back_populates="recipients")


class DataImport(Base):
    __tablename__ = "data_imports"

    source: Mapped[str] = mapped_column(String(120), primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
