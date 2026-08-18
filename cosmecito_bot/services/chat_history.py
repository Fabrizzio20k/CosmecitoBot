import sqlite3
from dataclasses import dataclass
from pathlib import Path


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
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    def get_conversation(self, user_id: int, channel_id: int) -> Conversation:
        with self._connect() as connection:
            summary_row = connection.execute(
                """
                SELECT summary
                FROM conversations
                WHERE user_id = ? AND channel_id = ?
                """,
                (user_id, channel_id),
            ).fetchone()
            message_rows = connection.execute(
                """
                SELECT id, role, content
                FROM messages
                WHERE user_id = ? AND channel_id = ?
                ORDER BY id
                """,
                (user_id, channel_id),
            ).fetchall()

        return Conversation(
            summary=summary_row["summary"] if summary_row else "",
            messages=[
                ChatMessage(
                    id=row["id"],
                    role=row["role"],
                    content=row["content"],
                )
                for row in message_rows
            ],
        )

    def add_message(self, user_id: int, channel_id: int, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (user_id, channel_id, role, content)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, channel_id, role, content),
            )

    def discard_messages(
        self,
        user_id: int,
        channel_id: int,
        message_ids: list[int],
    ) -> None:
        """Elimina mensajes concretos y cualquier resumen heredado del chat."""
        with self._connect() as connection:
            if message_ids:
                placeholders = ", ".join("?" for _ in message_ids)
                connection.execute(
                    f"""
                    DELETE FROM messages
                    WHERE user_id = ? AND channel_id = ? AND id IN ({placeholders})
                    """,
                    [user_id, channel_id, *message_ids],
                )
            connection.execute(
                """
                DELETE FROM conversations
                WHERE user_id = ? AND channel_id = ?
                """,
                (user_id, channel_id),
            )

    def clear_summary(self, user_id: int, channel_id: int) -> None:
        """Quita la memoria resumida usada por versiones anteriores del bot."""
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM conversations
                WHERE user_id = ? AND channel_id = ?
                """,
                (user_id, channel_id),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_tables(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (user_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages (user_id, channel_id, id);
                """,
            )
