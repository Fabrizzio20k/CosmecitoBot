import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Header, HTTPException, status
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient, models


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
    )


load_dotenv()
settings = get_settings()
qdrant = AsyncQdrantClient(url=settings.qdrant_url, timeout=600)
embeddings_client = AsyncOpenAI(
    base_url=settings.embedding_base_url,
    api_key="local-llama-cpp",
    timeout=600,
)
app = FastAPI(title="Cosmecito knowledge API", version="1.0.0")


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


@app.get("/health")
async def health() -> dict[str, str]:
    try:
        await qdrant.get_collections()
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Qdrant no disponible") from error
    return {"status": "ok"}


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
