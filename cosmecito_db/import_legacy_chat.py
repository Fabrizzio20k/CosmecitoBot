"""Importa una vez el historial SQLite anterior al nuevo PostgreSQL."""

import asyncio
import os
import sqlite3
from pathlib import Path

from sqlalchemy import select

from cosmecito_db.database import Database
from cosmecito_db.models import ChatMessage, Conversation, DataImport

IMPORT_SOURCE = "sqlite-chat-history-v1"


async def import_legacy_chat() -> None:
    source_path = Path(os.getenv("LEGACY_CHAT_DATABASE_PATH", "/legacy-state/chat_history.sqlite3"))
    if not source_path.is_file():
        print("No se encontró un historial SQLite anterior; se omite la importación.")
        return

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Falta DATABASE_URL para importar el historial SQLite")

    with sqlite3.connect(source_path) as legacy:
        legacy.row_factory = sqlite3.Row
        conversations = legacy.execute(
            "SELECT user_id, channel_id, summary FROM conversations"
        ).fetchall()
        messages = legacy.execute(
            "SELECT user_id, channel_id, role, content FROM messages ORDER BY id"
        ).fetchall()

    database = Database(database_url)
    try:
        async with database.session() as session, session.begin():
            already_imported = await session.scalar(
                select(DataImport.source).where(DataImport.source == IMPORT_SOURCE)
            )
            if already_imported:
                print("El historial SQLite ya fue importado anteriormente.")
                return
            session.add_all(
                Conversation(
                    user_id=row["user_id"], channel_id=row["channel_id"], summary=row["summary"]
                )
                for row in conversations
            )
            session.add_all(
                ChatMessage(
                    user_id=row["user_id"],
                    channel_id=row["channel_id"],
                    role=row["role"],
                    content=row["content"],
                )
                for row in messages
            )
            session.add(DataImport(source=IMPORT_SOURCE))
        print(f"Historial SQLite importado: {len(conversations)} conversaciones y {len(messages)} mensajes.")
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(import_legacy_chat())
