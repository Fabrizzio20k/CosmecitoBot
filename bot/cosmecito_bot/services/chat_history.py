from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from cosmecito_db.models import ChatMessage as ChatMessageModel
from cosmecito_db.models import Conversation as ConversationModel


@dataclass(frozen=True)
class ChatMessage:
    id: int
    role: str
    content: str


@dataclass(frozen=True)
class Conversation:
    summary: str
    messages: list[ChatMessage]


class ChatHistory:
    """Historial de chat almacenado en PostgreSQL."""

    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def get_conversation(self, user_id: int, channel_id: int) -> Conversation:
        async with self.sessions() as session:
            summary = await session.scalar(
                select(ConversationModel.summary).where(
                    ConversationModel.user_id == user_id,
                    ConversationModel.channel_id == channel_id,
                )
            )
            rows = await session.scalars(
                select(ChatMessageModel)
                .where(
                    ChatMessageModel.user_id == user_id,
                    ChatMessageModel.channel_id == channel_id,
                )
                .order_by(ChatMessageModel.id)
            )
            messages = rows.all()

        return Conversation(
            summary=summary or "",
            messages=[ChatMessage(id=row.id, role=row.role, content=row.content) for row in messages],
        )

    async def add_message(self, user_id: int, channel_id: int, role: str, content: str) -> None:
        async with self.sessions() as session, session.begin():
            session.add(
                ChatMessageModel(
                    user_id=user_id,
                    channel_id=channel_id,
                    role=role,
                    content=content,
                )
            )

    async def discard_messages(
        self,
        user_id: int,
        channel_id: int,
        message_ids: list[int],
    ) -> None:
        """Elimina mensajes concretos y cualquier resumen heredado del chat."""
        async with self.sessions() as session, session.begin():
            if message_ids:
                await session.execute(
                    delete(ChatMessageModel).where(
                        ChatMessageModel.user_id == user_id,
                        ChatMessageModel.channel_id == channel_id,
                        ChatMessageModel.id.in_(message_ids),
                    )
                )
            await session.execute(
                delete(ConversationModel).where(
                    ConversationModel.user_id == user_id,
                    ConversationModel.channel_id == channel_id,
                )
            )

    async def clear_summary(self, user_id: int, channel_id: int) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                delete(ConversationModel).where(
                    ConversationModel.user_id == user_id,
                    ConversationModel.channel_id == channel_id,
                )
            )
