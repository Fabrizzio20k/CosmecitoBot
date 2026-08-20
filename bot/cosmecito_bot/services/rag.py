import time
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from qdrant_client import AsyncQdrantClient

from cosmecito_bot.config import Settings
from cosmecito_bot.services.runtime_metrics import RuntimeMetrics


class RagError(RuntimeError):
    """Error que puede mostrarse al usuario sin exponer detalles internos."""


@dataclass(frozen=True)
class RetrievedChunk:
    source: str
    title: str
    section: str
    content: str


class RagService:
    """Recupera contexto desde una colección Qdrant ya indexada."""

    def __init__(self, settings: Settings, metrics: RuntimeMetrics | None = None) -> None:
        self.embedding_model = settings.rag_embedding_model
        self.embedding_base_url = settings.rag_embedding_base_url
        self.top_k = settings.rag_top_k
        self.min_score = settings.rag_min_score
        self.collection_name = settings.qdrant_collection
        self.vector_name = settings.qdrant_vector_name
        self.metrics = metrics or RuntimeMetrics()
        self.client = AsyncOpenAI(
            base_url=self.embedding_base_url,
            api_key="local-llama-cpp",
            timeout=settings.llama_cpp_timeout_seconds,
        )
        self.qdrant = AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=settings.llama_cpp_timeout_seconds,
        )

    async def collection_status(self) -> str:
        """Devuelve un estado informativo sin impedir que el bot arranque."""
        try:
            exists = await self.qdrant.collection_exists(self.collection_name)
        except Exception:
            return "⚠️ Qdrant no respondió durante el arranque; se reintentará al consultar."
        if exists:
            return f"📚 RAG conectado a Qdrant: colección '{self.collection_name}'."
        return (
            f"⚠️ La colección Qdrant '{self.collection_name}' aún no existe. "
            "El bot no tendrá contexto RAG hasta que el servicio de ingesta la cree."
        )

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        if not question.strip():
            return []

        started_at = time.perf_counter()
        embeddings = await self._embed([question], "query_embedding")
        query_started_at = time.perf_counter()
        try:
            response = await self.qdrant.query_points(
                collection_name=self.collection_name,
                query=embeddings[0],
                using=self.vector_name,
                limit=self.top_k,
                score_threshold=self.min_score,
                with_payload=True,
            )
        except Exception as error:
            raise RagError(
                "No se pudo consultar Qdrant. Revisa que la colección exista y que "
                "QDRANT_URL sea accesible."
            ) from error
        self.metrics.record("vector_search", time.perf_counter() - query_started_at)

        retrieved: list[RetrievedChunk] = []
        for point in response.points:
            payload = point.payload or {}
            content = payload.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            retrieved.append(
                RetrievedChunk(
                    source=self._payload_text(payload, "source", "documento"),
                    title=self._payload_text(payload, "title", "Documento sin título"),
                    section=self._payload_text(payload, "section", "Sin sección"),
                    content=content,
                )
            )

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

    async def close(self) -> None:
        await self.qdrant.close()

    async def _embed(self, texts: list[str], metric_name: str) -> list[list[float]]:
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

    def _payload_text(self, payload: dict[object, object], key: str, default: str) -> str:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default
