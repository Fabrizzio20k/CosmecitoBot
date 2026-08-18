import asyncio
import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import zvec
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from cosmecito_bot.config import Settings
from cosmecito_bot.services.runtime_metrics import RuntimeMetrics


class RagError(RuntimeError):
    """Error que puede mostrarse al usuario sin exponer detalles internos."""


@dataclass(frozen=True)
class RagChunk:
    id: str
    source: str
    title: str
    section: str
    course: str
    unit: str
    week: str
    topics: str
    content: str


@dataclass(frozen=True)
class RetrievedChunk:
    source: str
    title: str
    section: str
    content: str


@dataclass(frozen=True)
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0


class RagService:
    """Sincroniza Markdown con Zvec y recupera contexto para el chat."""

    collection_name = "course_knowledge"
    collection_folder_name = "zvec_collection"
    _zvec_initialized = False

    def __init__(self, settings: Settings, metrics: RuntimeMetrics | None = None) -> None:
        self.knowledge_path = settings.rag_knowledge_path
        self.database_path = settings.rag_database_path
        self.collection_path = self.database_path / self.collection_folder_name
        self.registry_path = self.database_path / "registry.sqlite3"
        self.embedding_model = settings.rag_embedding_model
        self.embedding_base_url = settings.rag_embedding_base_url
        self.top_k = settings.rag_top_k
        self.max_distance = settings.rag_max_distance
        self.chunk_size = settings.rag_chunk_size
        self.chunk_overlap = settings.rag_chunk_overlap
        self.metrics = metrics or RuntimeMetrics()
        self.client = AsyncOpenAI(
            base_url=self.embedding_base_url,
            api_key="local-llama-cpp",
            timeout=settings.llama_cpp_timeout_seconds,
        )
        self.collection: zvec.Collection | None = None
        self.lock = asyncio.Lock()
        self.database_path.mkdir(parents=True, exist_ok=True)
        self.knowledge_path.mkdir(parents=True, exist_ok=True)
        self._create_registry()

    async def sync(self) -> SyncResult:
        """Indexa solo archivos nuevos o modificados y elimina los ya ausentes."""
        started_at = time.perf_counter()
        async with self.lock:
            current_files = {
                path.relative_to(self.knowledge_path).as_posix(): path
                for path in self.knowledge_path.rglob("*.md")
                if path.is_file()
            }
            known_files = self._known_files()
            removed_sources = set(known_files) - set(current_files)
            changed_sources: list[tuple[str, Path, str, bool]] = []
            unchanged = 0

            for source, path in current_files.items():
                content_hash = self._file_hash(path)
                previous_hash = known_files.get(source)
                if previous_hash == content_hash:
                    unchanged += 1
                else:
                    changed_sources.append((source, path, content_hash, previous_hash is not None))

            for source in removed_sources:
                self._delete_source(source)

            added = 0
            updated = 0
            for source, path, content_hash, existed in changed_sources:
                chunks = self._chunks_from_markdown(source, path.read_text(encoding="utf-8"))
                embeddings = (
                    await self._embed([chunk.content for chunk in chunks], "index_embedding")
                    if chunks
                    else []
                )
                if embeddings:
                    collection = self._get_collection(len(embeddings[0]))
                    old_ids = self._chunk_ids_for_source(source)
                    if old_ids:
                        collection.delete(old_ids)
                    collection.upsert(
                        [
                            zvec.Doc(
                                id=chunk.id,
                                vectors={"embedding": embedding},
                                fields={
                                    "source": chunk.source,
                                    "title": chunk.title,
                                    "section": chunk.section,
                                    "course": chunk.course,
                                    "unit": chunk.unit,
                                    "week": chunk.week,
                                    "topics": chunk.topics,
                                    "content": chunk.content,
                                },
                            )
                            for chunk, embedding in zip(chunks, embeddings, strict=True)
                        ]
                    )
                elif self._chunk_ids_for_source(source):
                    self._delete_vectors(self._chunk_ids_for_source(source))

                self._replace_source(source, content_hash, chunks)
                if existed:
                    updated += 1
                else:
                    added += 1

            if self.collection is not None and (removed_sources or changed_sources):
                self.collection.flush()

            result = SyncResult(
                added=added,
                updated=updated,
                removed=len(removed_sources),
                unchanged=unchanged,
            )
        self.metrics.record("indexing", time.perf_counter() - started_at)
        return result

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        if not self._has_chunks():
            return []

        started_at = time.perf_counter()
        async with self.lock:
            embeddings = await self._embed([question], "query_embedding")
            collection = self._get_collection(len(embeddings[0]))
            query_started_at = time.perf_counter()
            results = collection.query(
                zvec.Query("embedding", vector=embeddings[0]),
                topk=self.top_k,
                output_fields=["source", "title", "section", "content"],
            )
            self.metrics.record("vector_search", time.perf_counter() - query_started_at)

        retrieved = [
            RetrievedChunk(
                source=document.fields["source"],
                title=document.fields["title"],
                section=document.fields["section"],
                content=document.fields["content"],
            )
            for document in results
            if document.score is None or document.score <= self.max_distance
        ]
        self.metrics.record("retrieval", time.perf_counter() - started_at)
        return retrieved

    def format_context(self, chunks: list[RetrievedChunk]) -> str:
        return "\n\n".join(
            (
                f"[Fuente: {chunk.title} — {chunk.section} ({chunk.source})]\n"
                f"{chunk.content}"
            )
            for chunk in chunks
        )

    def trim_to_context(
        self,
        chunks: list[RetrievedChunk],
        max_characters: int,
    ) -> list[RetrievedChunk]:
        selected: list[RetrievedChunk] = []
        used_characters = 0
        for chunk in chunks:
            chunk_characters = len(chunk.title) + len(chunk.section) + len(chunk.content) + 40
            if not selected and chunk_characters > max_characters:
                available_content = max(1, max_characters - len(chunk.title) - len(chunk.section) - 43)
                selected.append(
                    RetrievedChunk(
                        source=chunk.source,
                        title=chunk.title,
                        section=chunk.section,
                        content=f"{chunk.content[:available_content].rstrip()}…",
                    )
                )
                break
            if selected and used_characters + chunk_characters > max_characters:
                break
            selected.append(chunk)
            used_characters += chunk_characters
        return selected

    async def _embed(self, texts: list[str], metric_name: str) -> list[list[float]]:
        if not texts:
            return []

        started_at = time.perf_counter()
        try:
            response = await self.client.embeddings.create(
                model=self.embedding_model,
                input=texts,
            )
        except APITimeoutError as error:
            raise RagError("El servidor de embeddings tardó demasiado en responder.") from error
        except APIConnectionError as error:
            raise RagError(
                "No se pudo conectar al servidor de embeddings del RAG. "
                "Revisa RAG_EMBEDDING_BASE_URL."
            ) from error
        except APIStatusError as error:
            raise RagError(
                "El servidor de embeddings rechazó la solicitud del RAG. "
                "Revisa RAG_EMBEDDING_MODEL y el endpoint /v1/embeddings."
            ) from error

        embeddings = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if len(embeddings) != len(texts) or not embeddings:
            raise RagError("El servidor de embeddings devolvió una respuesta incompleta.")
        if len({len(embedding) for embedding in embeddings}) != 1:
            raise RagError("El servidor de embeddings devolvió vectores con dimensiones distintas.")
        self.metrics.record(metric_name, time.perf_counter() - started_at)
        return embeddings

    def _get_collection(self, dimension: int) -> zvec.Collection:
        self._initialize_zvec()
        stored_dimension = self._get_metadata("embedding_dimension")
        stored_signature = self._get_metadata("index_signature")
        signature = self._index_signature()
        if stored_dimension is not None and int(stored_dimension) != dimension:
            raise RagError(
                "La dimensión del modelo de embeddings cambió. Borra data/rag "
                "una vez para reconstruir el índice con el modelo nuevo."
            )
        if stored_signature is not None and stored_signature != signature:
            raise RagError(
                "Cambió la configuración del RAG. Borra data/rag una vez para "
                "reconstruir el índice con la nueva configuración."
            )

        if self.collection is None:
            if self.collection_path.exists():
                self.collection = zvec.open(str(self.collection_path))
            else:
                schema = zvec.CollectionSchema(
                    name=self.collection_name,
                    fields=[
                        zvec.FieldSchema("source", zvec.DataType.STRING),
                        zvec.FieldSchema("title", zvec.DataType.STRING),
                        zvec.FieldSchema("section", zvec.DataType.STRING),
                        zvec.FieldSchema("course", zvec.DataType.STRING),
                        zvec.FieldSchema("unit", zvec.DataType.STRING),
                        zvec.FieldSchema("week", zvec.DataType.STRING),
                        zvec.FieldSchema("topics", zvec.DataType.STRING),
                        zvec.FieldSchema("content", zvec.DataType.STRING),
                    ],
                    vectors=zvec.VectorSchema(
                        "embedding",
                        zvec.DataType.VECTOR_FP32,
                        dimension,
                        index_param=zvec.HnswIndexParam(
                            metric_type=zvec.MetricType.COSINE,
                            m=16,
                            ef_construction=200,
                        ),
                    ),
                )
                self.collection = zvec.create_and_open(str(self.collection_path), schema)
                self._set_metadata("embedding_dimension", str(dimension))
                self._set_metadata("index_signature", signature)

        return self.collection

    def _delete_source(self, source: str) -> int:
        ids = self._chunk_ids_for_source(source)
        self._delete_vectors(ids)
        with self._connect() as connection:
            connection.execute("DELETE FROM source_files WHERE source = ?", (source,))
        return len(ids)

    def _delete_vectors(self, ids: list[str]) -> None:
        if not ids or not self.collection_path.exists():
            return
        self._get_collection_from_disk().delete(ids)

    def _get_collection_from_disk(self) -> zvec.Collection:
        self._initialize_zvec()
        if self.collection is None:
            self.collection = zvec.open(str(self.collection_path))
        return self.collection

    def _chunks_from_markdown(self, source: str, markdown: str) -> list[RagChunk]:
        metadata, body = self._parse_front_matter(markdown)
        title = metadata.get("title") or self._first_heading(body) or Path(source).stem.replace("-", " ")
        course = metadata.get("curso", metadata.get("course", ""))
        unit = metadata.get("unidad", metadata.get("unit", ""))
        week = metadata.get("semana", metadata.get("week", ""))
        topics = metadata.get("temas", metadata.get("topics", ""))
        chunks: list[RagChunk] = []

        for section, section_text in self._sections(body, title):
            for position, text in enumerate(self._split_text(section_text)):
                content = f"{title}\n{section}\n\n{text}".strip()
                chunk_id = hashlib.sha256(
                    f"{source}:{section}:{position}".encode("utf-8")
                ).hexdigest()
                chunks.append(
                    RagChunk(
                        id=chunk_id,
                        source=source,
                        title=title,
                        section=section,
                        course=course,
                        unit=unit,
                        week=week,
                        topics=topics,
                        content=content,
                    )
                )

        return chunks

    def _sections(self, body: str, fallback_title: str) -> list[tuple[str, str]]:
        sections: list[tuple[str, str]] = []
        current_title = fallback_title
        current_lines: list[str] = []
        for line in body.splitlines():
            match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if match:
                text = "\n".join(current_lines).strip()
                if text:
                    sections.append((current_title, text))
                current_title = match.group(1)
                current_lines = []
            else:
                current_lines.append(line)
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((current_title, text))
        return sections

    def _split_text(self, text: str) -> list[str]:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > self.chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_long_paragraph(paragraph))
                continue
            candidate = f"{current}\n\n{paragraph}".strip()
            if current and len(candidate) > self.chunk_size:
                chunks.append(current)
                overlap = current[-self.chunk_overlap :] if self.chunk_overlap else ""
                current = f"{overlap}\n\n{paragraph}".strip()
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        pieces: list[str] = []
        remaining = paragraph
        while len(remaining) > self.chunk_size:
            split_at = remaining.rfind(" ", 0, self.chunk_size)
            if split_at <= 0:
                split_at = self.chunk_size
            pieces.append(remaining[:split_at].strip())
            overlap = remaining[max(0, split_at - self.chunk_overlap) : split_at]
            remaining = f"{overlap}{remaining[split_at:]}".strip()
        if remaining:
            pieces.append(remaining)
        return pieces

    def _parse_front_matter(self, markdown: str) -> tuple[dict[str, str], str]:
        if not markdown.startswith("---\n"):
            return {}, markdown
        closing = re.search(r"^---\s*$", markdown[4:], flags=re.MULTILINE)
        if closing is None:
            return {}, markdown
        end = 4 + closing.end()
        metadata: dict[str, str] = {}
        current_key = ""
        for line in markdown[4 : 4 + closing.start()].splitlines():
            if match := re.match(r"^([\w-]+):\s*(.*?)\s*$", line):
                current_key = match.group(1).lower()
                metadata[current_key] = match.group(2).strip('"\'')
            elif current_key and (match := re.match(r"^\s*-\s*(.+?)\s*$", line)):
                metadata[current_key] = ", ".join(
                    value for value in (metadata[current_key], match.group(1)) if value
                )
        return metadata, markdown[end:].lstrip("\n")

    def _first_heading(self, text: str) -> str:
        match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
        return match.group(1) if match else ""

    def _known_files(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT source, content_hash FROM source_files").fetchall()
        return {row["source"]: row["content_hash"] for row in rows}

    def _chunk_ids_for_source(self, source: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chunk_id FROM chunks WHERE source = ? ORDER BY chunk_id", (source,)
            ).fetchall()
        return [row["chunk_id"] for row in rows]

    def _replace_source(self, source: str, content_hash: str, chunks: list[RagChunk]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE source = ?", (source,))
            connection.execute(
                """
                INSERT INTO source_files (source, content_hash)
                VALUES (?, ?)
                ON CONFLICT(source) DO UPDATE SET content_hash = excluded.content_hash
                """,
                (source, content_hash),
            )
            connection.executemany(
                "INSERT INTO chunks (chunk_id, source) VALUES (?, ?)",
                [(chunk.id, source) for chunk in chunks],
            )

    def _has_chunks(self) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT EXISTS(SELECT 1 FROM chunks)").fetchone()
        return bool(row[0])

    def _file_hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _index_signature(self) -> str:
        raw = f"{self.embedding_base_url}|{self.embedding_model}|{self.chunk_size}|{self.chunk_overlap}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_metadata(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_metadata(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO metadata (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _initialize_zvec(self) -> None:
        if not self.__class__._zvec_initialized:
            zvec.init()
            self.__class__._zvec_initialized = True

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.registry_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_registry(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS source_files (
                    source TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL REFERENCES source_files(source) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source);

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
