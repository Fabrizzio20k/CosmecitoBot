import json
import os
import re
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, Field
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from cosmecito_db import Database
from cosmecito_db.models import Announcement, AnnouncementChannel, MessageAttachment, Reminder, ReminderRecipient
from cosmecito_db.scheduling import LIMA_TIMEZONE, RECURRENCES


@dataclass(frozen=True)
class Settings:
    admin_token: str
    qdrant_url: str
    qdrant_collection: str
    qdrant_vector_name: str
    embedding_base_url: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    max_document_bytes: int
    database_url: str
    llama_cpp_base_url: str
    llama_cpp_model: str
    scheduler_model_timeout_seconds: float
    attachment_max_bytes: int
    attachment_total_max_bytes: int


def get_settings() -> Settings:
    admin_token = os.getenv("API_ADMIN_TOKEN", "")
    if not admin_token:
        raise RuntimeError("Falta la variable de entorno requerida: API_ADMIN_TOKEN")

    chunk_size = int(os.getenv("RAG_CHUNK_SIZE", "1600"))
    chunk_overlap = int(os.getenv("RAG_CHUNK_OVERLAP", "200"))
    if chunk_size < 1 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise RuntimeError("RAG_CHUNK_SIZE y RAG_CHUNK_OVERLAP no son válidos")

    return Settings(
        admin_token=admin_token,
        qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "course_knowledge"),
        qdrant_vector_name=os.getenv("QDRANT_VECTOR_NAME", "embedding"),
        embedding_base_url=os.getenv("RAG_EMBEDDING_BASE_URL", "http://embeddings:8081/v1").rstrip("/"),
        embedding_model=os.getenv("RAG_EMBEDDING_MODEL", "qwen3-embedding-4b-q4_k_m.gguf"),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        max_document_bytes=int(os.getenv("API_DOCUMENT_MAX_BYTES", "5000000")),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://cosmecito:cosmecito@127.0.0.1:5432/cosmecito",
        ),
        llama_cpp_base_url=os.getenv("LLAMA_CPP_BASE_URL", "http://chat:8080/v1").rstrip("/"),
        llama_cpp_model=os.getenv("LLAMA_CPP_MODEL", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
        scheduler_model_timeout_seconds=float(os.getenv("SCHEDULER_MODEL_TIMEOUT_SECONDS", "45")),
        attachment_max_bytes=int(os.getenv("MESSAGE_ATTACHMENT_MAX_BYTES", str(8 * 1024 * 1024))),
        attachment_total_max_bytes=int(os.getenv("MESSAGE_ATTACHMENT_TOTAL_MAX_BYTES", str(20 * 1024 * 1024))),
    )


load_dotenv()
settings = get_settings()
qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=600)
embeddings_client = AsyncOpenAI(
    base_url=settings.embedding_base_url,
    api_key="local-llama-cpp",
    timeout=600,
)
scheduler_client = AsyncOpenAI(
    base_url=settings.llama_cpp_base_url,
    api_key="local-llama-cpp",
    timeout=settings.scheduler_model_timeout_seconds,
)
database = Database(settings.database_url)
app = FastAPI(title="Cosmecito knowledge API", version="1.0.0")

MAX_ATTACHMENTS = 10


@dataclass(frozen=True)
class Chunk:
    id: str
    position: int
    section: str
    content: str


async def require_admin(
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado")


@app.on_event("shutdown")
async def shutdown() -> None:
    await qdrant.close()
    await scheduler_client.close()
    await database.close()


@app.get("/health")
async def health() -> dict[str, str]:
    try:
        await qdrant.get_collections()
        await database.ping()
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Qdrant o PostgreSQL no disponible") from error
    return {"status": "ok"}


class AnnouncementInput(BaseModel):
    content: str = Field(min_length=1, max_length=2_000)
    channel_ids: list[int] = Field(min_length=1, max_length=25)
    scheduled_for: datetime | None = None
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|monthly)$")
    created_by: int | None = None


class ReminderInput(BaseModel):
    content: str = Field(min_length=1, max_length=2_000)
    scheduled_for: datetime
    recurrence: str = Field(default="none", pattern="^(none|daily|weekly|monthly)$")
    user_ids: list[int] = Field(default_factory=list, max_length=500)
    role_id: int | None = None
    announcement_id: uuid.UUID | None = None


class ScheduleInstruction(BaseModel):
    instruction: str = Field(min_length=1, max_length=500)


def _format_lima(value: datetime) -> str:
    return value.astimezone(LIMA_TIMEZONE).strftime("%A %d/%m/%Y, %H:%M (Lima)")


def _schedule_payload(value: datetime, recurrence: str) -> dict[str, str]:
    labels = {
        "none": "una sola vez",
        "daily": "todos los días",
        "weekly": "cada semana",
        "monthly": "cada mes",
    }
    return {
        "scheduled_for": value.isoformat(),
        "recurrence": recurrence,
        "summary": f"{_format_lima(value)} · {labels[recurrence]}",
        "timezone": "America/Lima",
    }


def _schedule_from_model(content: str, now: datetime) -> tuple[datetime, str]:
    match = re.search(r"\{.*\}", content.strip(), flags=re.DOTALL)
    if match is None:
        raise ValueError("El modelo no devolvió una fecha válida.")
    try:
        result = json.loads(match.group())
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("date"), str)
            or not isinstance(result.get("time"), str)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["date"])
            or not re.fullmatch(r"\d{2}:\d{2}", result["time"])
        ):
            raise ValueError
        scheduled_date = date.fromisoformat(result["date"])
        scheduled_time = time.fromisoformat(result["time"])
        recurrence = result["recurrence"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("El modelo no devolvió una programación válida.") from error
    if recurrence not in RECURRENCES:
        raise ValueError("La repetición indicada no está permitida.")
    scheduled_for = datetime.combine(scheduled_date, scheduled_time, tzinfo=LIMA_TIMEZONE).astimezone(UTC)
    if scheduled_for <= now:
        raise ValueError("La fecha interpretada ya pasó. Indica una fecha y hora futuras.")
    return scheduled_for, recurrence


@app.post("/schedules/parse", dependencies=[Depends(require_admin)])
async def parse_schedule(payload: ScheduleInstruction) -> dict[str, str]:
    now = datetime.now(UTC)
    now_lima = now.astimezone(LIMA_TIMEZONE)
    system_prompt = """Eres un analizador de calendario, no un asistente conversacional.
Interpreta la instrucción en español para programar un mensaje en America/Lima.
Devuelve exclusivamente JSON válido con exactamente estas claves:
{"date":"YYYY-MM-DD","time":"HH:MM","recurrence":"none|daily|weekly|monthly"}.
Usa recurrence daily solo si se pide cada día/todos los días; weekly solo si se pide cada semana o un día de la semana; monthly solo si se pide cada mes. Si no se pide repetición, usa none.
Resuelve las referencias relativas contra la fecha/hora entregada. No inventes destinatarios ni cambies la hora. Si la instrucción es ambigua o no indica hora y fecha suficientes, devuelve {"error":"..."}."""
    try:
        completion = await scheduler_client.chat.completions.create(
            model=settings.llama_cpp_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "now_lima": now_lima.strftime("%Y-%m-%d %H:%M"),
                            "instruction": payload.instruction.strip(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0,
            max_tokens=120,
        )
    except (APITimeoutError, APIConnectionError, APIStatusError) as error:
        raise HTTPException(status_code=503, detail="No se pudo consultar el modelo de programación.") from error
    response = completion.choices[0].message.content or ""
    try:
        scheduled_for, recurrence = _schedule_from_model(response, now)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f"No pude interpretar la programación: {error}") from error
    return _schedule_payload(scheduled_for, recurrence)


def _utc_datetime(value: datetime | None, *, default_now: bool = False) -> datetime:
    if value is None:
        if default_now:
            return datetime.now(UTC)
        raise HTTPException(status_code=422, detail="La fecha programada es obligatoria")
    if value.tzinfo is None:
        raise HTTPException(status_code=422, detail="La fecha debe incluir zona horaria; usa UTC (Z)")
    return value.astimezone(UTC)


def _form_datetime(value: str | None, *, required: bool) -> datetime | None:
    if not value:
        if required:
            raise HTTPException(status_code=422, detail="La fecha programada es obligatoria")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail="La fecha programada no es válida") from error
    return _utc_datetime(parsed)


def _form_ids(value: str, *, field_name: str, maximum: int) -> list[int]:
    try:
        values = json.loads(value)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail=f"{field_name} debe ser una lista JSON de IDs") from error
    if not isinstance(values, list) or not values or len(values) > maximum:
        raise HTTPException(status_code=422, detail=f"Indica entre 1 y {maximum} {field_name}")
    if any(not isinstance(item, int) or item <= 0 for item in values):
        raise HTTPException(status_code=422, detail=f"Los IDs de {field_name} deben ser positivos")
    return sorted(set(values))


def _message_content(value: str) -> str:
    content = value.strip()
    if not content:
        raise HTTPException(status_code=422, detail="El mensaje no puede estar vacío")
    return content


def _future_schedule(value: datetime | None, *, default_now: bool) -> datetime:
    scheduled_for = _utc_datetime(value, default_now=default_now)
    if value is not None and scheduled_for <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="La fecha programada debe ser futura")
    return scheduled_for


async def _read_attachments(files: list[UploadFile]) -> list[MessageAttachment]:
    if len(files) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=422, detail=f"Puedes adjuntar como máximo {MAX_ATTACHMENTS} archivos")
    attachments: list[MessageAttachment] = []
    total_size = 0
    for upload in files:
        try:
            filename = Path(upload.filename or "").name.strip()
            if filename in {"", ".", ".."}:
                raise HTTPException(status_code=422, detail="Cada archivo debe tener un nombre válido")
            data = await upload.read(settings.attachment_max_bytes + 1)
        finally:
            await upload.close()
        if len(data) > settings.attachment_max_bytes:
            raise HTTPException(status_code=422, detail=f"El archivo {filename} supera el límite permitido")
        total_size += len(data)
        if total_size > settings.attachment_total_max_bytes:
            raise HTTPException(status_code=422, detail="Los adjuntos superan el tamaño total permitido")
        attachments.append(
            MessageAttachment(
                filename=filename[:255],
                content_type=(upload.content_type or None),
                byte_size=len(data),
                data=data,
            )
        )
    return attachments


def _attachment_payload(attachment: MessageAttachment) -> dict[str, object]:
    return {
        "id": str(attachment.id),
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "byte_size": attachment.byte_size,
    }


def _reminder_payload(reminder: Reminder) -> dict[str, object]:
    return {
        "id": str(reminder.id),
        "announcement_id": str(reminder.announcement_id) if reminder.announcement_id else None,
        "content": reminder.content,
        "scheduled_for": reminder.scheduled_for.isoformat(),
        "target_role_id": reminder.target_role_id,
        "status": reminder.status,
        "recurrence": reminder.recurrence,
        "attachments": [_attachment_payload(attachment) for attachment in reminder.attachments],
        "recipients": [
            {
                "user_id": recipient.user_id,
                "source": recipient.source,
                "status": recipient.status,
                "sent_at": recipient.sent_at.isoformat() if recipient.sent_at else None,
                "error": recipient.error,
            }
            for recipient in reminder.recipients
        ],
    }


def _announcement_payload(announcement: Announcement) -> dict[str, object]:
    return {
        "id": str(announcement.id),
        "content": announcement.content,
        "created_by": announcement.created_by,
        "status": announcement.status,
        "recurrence": announcement.recurrence,
        "created_at": announcement.created_at.isoformat(),
        "channels": [
            {
                "id": channel.id,
                "channel_id": channel.channel_id,
                "scheduled_for": channel.scheduled_for.isoformat(),
                "status": channel.status,
                "discord_message_id": channel.discord_message_id,
                "sent_at": channel.sent_at.isoformat() if channel.sent_at else None,
                "error": channel.error,
            }
            for channel in announcement.channels
        ],
        "reminders": [
            _reminder_payload(reminder)
            for reminder in announcement.reminders
        ],
        "attachments": [_attachment_payload(attachment) for attachment in announcement.attachments],
    }


async def _load_announcement(announcement_id: uuid.UUID) -> Announcement:
    async with database.session() as session:
        announcement = await session.scalar(
            select(Announcement)
            .where(Announcement.id == announcement_id)
            .options(
                selectinload(Announcement.channels),
                selectinload(Announcement.reminders).selectinload(Reminder.recipients),
                selectinload(Announcement.reminders).selectinload(Reminder.attachments),
                selectinload(Announcement.attachments),
            )
        )
        if announcement is None:
            raise HTTPException(status_code=404, detail="Anuncio no encontrado")
        return announcement


async def _load_reminder(reminder_id: uuid.UUID) -> Reminder:
    async with database.session() as session:
        reminder = await session.scalar(
            select(Reminder)
            .where(Reminder.id == reminder_id)
            .options(selectinload(Reminder.recipients), selectinload(Reminder.attachments))
        )
        if reminder is None:
            raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
        return reminder


async def _create_reminder_record(
    payload: ReminderInput,
    announcement_id: uuid.UUID | None,
    attachments: list[MessageAttachment] | None = None,
) -> uuid.UUID:
    user_ids = sorted(set(payload.user_ids))
    if not user_ids and payload.role_id is None:
        raise HTTPException(status_code=422, detail="Indica al menos un usuario o un rol destinatario")
    if any(user_id <= 0 for user_id in user_ids) or (payload.role_id is not None and payload.role_id <= 0):
        raise HTTPException(status_code=422, detail="Los IDs de usuario y rol deben ser positivos")
    scheduled_for = _future_schedule(payload.scheduled_for, default_now=False)
    async with database.session() as session, session.begin():
        if announcement_id is not None:
            announcement = await session.get(Announcement, announcement_id)
            if announcement is None:
                raise HTTPException(status_code=404, detail="Anuncio no encontrado")
            if announcement.status == "cancelled":
                raise HTTPException(status_code=409, detail="No se puede agregar un recordatorio a un anuncio cancelado")
        reminder = Reminder(
            announcement_id=announcement_id,
            content=_message_content(payload.content),
            scheduled_for=scheduled_for,
            target_role_id=payload.role_id,
            status="scheduled",
            recurrence=payload.recurrence,
            attachments=attachments or [],
            recipients=[
                ReminderRecipient(user_id=user_id, source="direct", status="queued")
                for user_id in user_ids
            ],
        )
        session.add(reminder)
        await session.flush()
        return reminder.id


async def _create_announcement_record(
    payload: AnnouncementInput,
    attachments: list[MessageAttachment] | None = None,
) -> uuid.UUID:
    channel_ids = sorted(set(payload.channel_ids))
    if any(channel_id <= 0 for channel_id in channel_ids):
        raise HTTPException(status_code=422, detail="Los IDs de canal deben ser positivos")
    scheduled_for = _future_schedule(payload.scheduled_for, default_now=True)
    async with database.session() as session, session.begin():
        announcement = Announcement(
            content=_message_content(payload.content),
            created_by=payload.created_by,
            status="scheduled",
            recurrence=payload.recurrence,
            attachments=attachments or [],
            channels=[
                AnnouncementChannel(channel_id=channel_id, scheduled_for=scheduled_for, status="queued")
                for channel_id in channel_ids
            ],
        )
        session.add(announcement)
        await session.flush()
        return announcement.id


@app.get("/announcements", dependencies=[Depends(require_admin)])
async def list_announcements() -> list[dict[str, object]]:
    async with database.session() as session:
        announcements = list(
            await session.scalars(
                select(Announcement)
                .options(
                    selectinload(Announcement.channels),
                    selectinload(Announcement.reminders).selectinload(Reminder.recipients),
                    selectinload(Announcement.reminders).selectinload(Reminder.attachments),
                    selectinload(Announcement.attachments),
                )
                .order_by(Announcement.created_at.desc())
                .limit(100)
            )
        )
        return [_announcement_payload(announcement) for announcement in announcements]


@app.post("/announcements", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_announcement(payload: AnnouncementInput) -> dict[str, object]:
    announcement_id = await _create_announcement_record(payload)
    return _announcement_payload(await _load_announcement(announcement_id))


@app.post("/announcements/upload", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_announcement_with_attachments(
    content: str = Form(...),
    channel_ids: str = Form(...),
    scheduled_for: str | None = Form(default=None),
    recurrence: str = Form(default="none"),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, object]:
    if recurrence not in RECURRENCES:
        raise HTTPException(status_code=422, detail="La repetición no es válida")
    payload = AnnouncementInput(
        content=content,
        channel_ids=_form_ids(channel_ids, field_name="canales", maximum=25),
        scheduled_for=_form_datetime(scheduled_for, required=False),
        recurrence=recurrence,
    )
    announcement_id = await _create_announcement_record(payload, await _read_attachments(files))
    return _announcement_payload(await _load_announcement(announcement_id))


@app.get("/announcements/{announcement_id}", dependencies=[Depends(require_admin)])
async def get_announcement(announcement_id: uuid.UUID) -> dict[str, object]:
    return _announcement_payload(await _load_announcement(announcement_id))


@app.get("/reminders", dependencies=[Depends(require_admin)])
async def list_standalone_reminders() -> list[dict[str, object]]:
    async with database.session() as session:
        reminders = list(
            await session.scalars(
                select(Reminder)
                .where(Reminder.announcement_id.is_(None))
                .options(selectinload(Reminder.recipients), selectinload(Reminder.attachments))
                .order_by(Reminder.scheduled_for.desc())
                .limit(100)
            )
        )
        return [_reminder_payload(reminder) for reminder in reminders]


@app.post("/reminders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_standalone_reminder(payload: ReminderInput) -> dict[str, object]:
    reminder_id = await _create_reminder_record(payload, payload.announcement_id)
    return _reminder_payload(await _load_reminder(reminder_id))


@app.post("/reminders/upload", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_reminder_with_attachments(
    content: str = Form(...),
    scheduled_for: str = Form(...),
    user_ids: str = Form(default="[]"),
    role_id: int | None = Form(default=None),
    announcement_id: uuid.UUID | None = Form(default=None),
    recurrence: str = Form(default="none"),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, object]:
    if recurrence not in RECURRENCES:
        raise HTTPException(status_code=422, detail="La repetición no es válida")
    try:
        raw_user_ids = json.loads(user_ids)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="Los usuarios deben ser una lista JSON de IDs") from error
    if not isinstance(raw_user_ids, list) or len(raw_user_ids) > 500:
        raise HTTPException(status_code=422, detail="Indica como máximo 500 usuarios")
    payload = ReminderInput(
        content=content,
        scheduled_for=_form_datetime(scheduled_for, required=True),
        user_ids=raw_user_ids,
        role_id=role_id,
        announcement_id=announcement_id,
        recurrence=recurrence,
    )
    reminder_id = await _create_reminder_record(
        payload,
        announcement_id,
        await _read_attachments(files),
    )
    return _reminder_payload(await _load_reminder(reminder_id))


@app.post("/announcements/{announcement_id}/reminders", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_reminder(announcement_id: uuid.UUID, payload: ReminderInput) -> dict[str, object]:
    await _create_reminder_record(payload, announcement_id)
    return _announcement_payload(await _load_announcement(announcement_id))


@app.delete("/reminders/{reminder_id}", dependencies=[Depends(require_admin)])
async def cancel_reminder(reminder_id: uuid.UUID) -> dict[str, str]:
    async with database.session() as session, session.begin():
        reminder = await session.get(Reminder, reminder_id, with_for_update=True)
        if reminder is None:
            raise HTTPException(status_code=404, detail="Recordatorio no encontrado")
        if reminder.status in {"scheduled", "processing"}:
            reminder.status = "cancelled"
            await session.execute(
                update(ReminderRecipient)
                .where(
                    ReminderRecipient.reminder_id == reminder_id,
                    ReminderRecipient.status.in_(["queued", "processing"]),
                )
                .values(status="cancelled")
            )
    return {"id": str(reminder_id), "status": "cancelled"}


@app.delete("/announcements/{announcement_id}", dependencies=[Depends(require_admin)])
async def cancel_announcement(announcement_id: uuid.UUID) -> dict[str, str]:
    async with database.session() as session, session.begin():
        announcement = await session.get(Announcement, announcement_id, with_for_update=True)
        if announcement is None:
            raise HTTPException(status_code=404, detail="Anuncio no encontrado")
        announcement.status = "cancelled"
        await session.execute(
            update(AnnouncementChannel)
            .where(
                AnnouncementChannel.announcement_id == announcement_id,
                AnnouncementChannel.status.in_(["queued", "processing"]),
            )
            .values(status="cancelled")
        )
        await session.execute(
            update(Reminder)
            .where(Reminder.announcement_id == announcement_id, Reminder.status.in_(["scheduled", "processing"]))
            .values(status="cancelled")
        )
        await session.execute(
            update(ReminderRecipient)
            .where(
                ReminderRecipient.reminder_id.in_(
                    select(Reminder.id).where(Reminder.announcement_id == announcement_id)
                ),
                ReminderRecipient.status.in_(["queued", "processing"]),
            )
            .values(status="cancelled")
        )
    return {"id": str(announcement_id), "status": "cancelled"}


@app.get("/documents", dependencies=[Depends(require_admin)])
async def list_documents() -> list[dict[str, object]]:
    if not await qdrant.collection_exists(settings.qdrant_collection):
        return []

    documents: dict[str, dict[str, object]] = {}
    offset: str | int | None = None
    while True:
        points, offset = await qdrant.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=None,
            limit=128,
            offset=offset,
            with_payload=["document_id", "source", "title", "updated_at"],
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            document_id = payload.get("document_id")
            if not isinstance(document_id, str) or document_id in documents:
                continue
            documents[document_id] = {
                "id": document_id,
                "source": _payload_text(payload, "source", document_id),
                "title": _payload_text(payload, "title", document_id),
                "updated_at": _payload_text(payload, "updated_at", ""),
            }
        if offset is None:
            break
    return sorted(documents.values(), key=lambda document: str(document["title"]).lower())


@app.post("/documents", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_document(
    content: str = Form(...),
    document_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    source: str | None = Form(default=None),
) -> dict[str, object]:
    return await _ingest(content, document_id, title, source)


@app.put("/documents/{document_id}", dependencies=[Depends(require_admin)])
async def update_document(
    document_id: str,
    content: str = Form(...),
    title: str | None = Form(default=None),
    source: str | None = Form(default=None),
) -> dict[str, object]:
    return await _ingest(content, document_id, title, source)


@app.get("/documents/{document_id}", dependencies=[Depends(require_admin)])
async def get_document(document_id: str) -> dict[str, object]:
    normalized_id = _normalize_document_id(document_id)
    if not await qdrant.collection_exists(settings.qdrant_collection):
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    offset: str | int | None = None
    fallback_payload: dict[object, object] | None = None
    legacy_payloads: list[dict[object, object]] = []
    while True:
        points, offset = await qdrant.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=_document_filter(normalized_id),
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = point.payload or {}
            fallback_payload = payload
            content = payload.get("document_content")
            if isinstance(content, str):
                return {
                    "id": normalized_id,
                    "source": _payload_text(payload, "source", normalized_id),
                    "title": _payload_text(payload, "title", normalized_id),
                    "content": content,
                    "reconstructed": False,
                }
            legacy_payloads.append(payload)
        if offset is None:
            break
    if fallback_payload is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return {
        "id": normalized_id,
        "source": _payload_text(fallback_payload, "source", normalized_id),
        "title": _payload_text(fallback_payload, "title", normalized_id),
        "content": _reconstruct_legacy_document(legacy_payloads, fallback_payload),
        "reconstructed": True,
    }


@app.delete("/documents/{document_id}", dependencies=[Depends(require_admin)])
async def delete_document(document_id: str) -> dict[str, str]:
    normalized_id = _normalize_document_id(document_id)
    if await qdrant.collection_exists(settings.qdrant_collection):
        await qdrant.delete(
            collection_name=settings.qdrant_collection,
            points_selector=models.FilterSelector(filter=_document_filter(normalized_id)),
            wait=True,
        )
    return {"id": normalized_id, "status": "deleted"}


async def _ingest(
    text: str,
    document_id: str | None,
    title: str | None,
    source: str | None,
) -> dict[str, object]:
    if not text.strip():
        raise HTTPException(status_code=422, detail="El documento está vacío")
    if len(text.encode("utf-8")) > settings.max_document_bytes:
        raise HTTPException(status_code=413, detail="El documento supera el tamaño máximo permitido")

    document_source = (source or document_id or title or "documento").strip()
    normalized_id = _normalize_document_id(document_id or document_source)
    document_title = (title or _first_heading(text) or document_source).strip()
    chunks = _chunks_from_text(normalized_id, document_title, text)
    if not chunks:
        raise HTTPException(status_code=422, detail="No se encontró texto indexable en el documento")

    vectors = await _embed([chunk.content for chunk in chunks])
    await _ensure_collection(len(vectors[0]))
    await qdrant.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(filter=_document_filter(normalized_id)),
        wait=True,
    )

    updated_at = datetime.now(UTC).isoformat()
    await qdrant.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            models.PointStruct(
                id=chunk.id,
                vector={settings.qdrant_vector_name: vector},
                payload={
                    "document_id": normalized_id,
                    "source": document_source,
                    "title": document_title,
                    "section": chunk.section,
                    "content": chunk.content,
                    "document_content": text if chunk.position == 0 else None,
                    "updated_at": updated_at,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ],
        wait=True,
    )
    return {"id": normalized_id, "title": document_title, "chunks": len(chunks)}


async def _ensure_collection(vector_size: int) -> None:
    if await qdrant.collection_exists(settings.qdrant_collection):
        return
    await qdrant.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config={
            settings.qdrant_vector_name: models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            )
        },
    )


async def _embed(texts: list[str]) -> list[list[float]]:
    try:
        response = await embeddings_client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="No se pudieron generar embeddings") from error
    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    if len(vectors) != len(texts) or not vectors:
        raise HTTPException(status_code=502, detail="El servidor de embeddings devolvió una respuesta incompleta")
    return vectors


def _document_filter(document_id: str) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(value=document_id),
            )
        ]
    )


def _chunks_from_text(document_id: str, title: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, section_text in _sections(text, title):
        for position, piece in enumerate(_split_text(section_text)):
            content = f"{title}\n{section}\n\n{piece}".strip()
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{section}:{position}"))
            chunks.append(
                Chunk(
                    id=chunk_id,
                    position=len(chunks),
                    section=section,
                    content=content,
                )
            )
    return chunks


def _sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = fallback_title
    current_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if match:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_title, body))
            current_title = match.group(1)
            current_lines = []
        else:
            current_lines.append(line)
    body = "\n".join(current_lines).strip()
    if body:
        sections.append((current_title, body))
    return sections


def _split_text(text: str) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > settings.chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_paragraph(paragraph))
            continue
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > settings.chunk_size:
            chunks.append(current)
            overlap = current[-settings.chunk_overlap :] if settings.chunk_overlap else ""
            current = f"{overlap}\n\n{paragraph}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _split_long_paragraph(paragraph: str) -> list[str]:
    pieces: list[str] = []
    remaining = paragraph
    while len(remaining) > settings.chunk_size:
        split_at = remaining.rfind(" ", 0, settings.chunk_size)
        split_at = split_at if split_at > 0 else settings.chunk_size
        pieces.append(remaining[:split_at].strip())
        overlap = remaining[max(0, split_at - settings.chunk_overlap) : split_at]
        remaining = f"{overlap}{remaining[split_at:]}".strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def _normalize_document_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip(".-")
    if not normalized:
        raise HTTPException(status_code=422, detail="El identificador del documento no es válido")
    return normalized[:120]


def _first_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _payload_text(payload: dict[object, object], key: str, default: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _reconstruct_legacy_document(
    payloads: list[dict[object, object]],
    fallback_payload: dict[object, object],
) -> str:
    """Construye un borrador editable para documentos indexados antes del editor."""
    title = _payload_text(fallback_payload, "title", "Documento sin título")
    sections: list[str] = [f"# {title}"]
    seen: set[tuple[str, str]] = set()
    for payload in payloads:
        content = payload.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        section = _payload_text(payload, "section", title)
        prefix = f"{title}\n{section}\n\n"
        body = content.removeprefix(prefix).strip()
        key = (section, body)
        if not body or key in seen:
            continue
        seen.add(key)
        sections.extend((f"## {section}", body))
    return "\n\n".join(sections)
