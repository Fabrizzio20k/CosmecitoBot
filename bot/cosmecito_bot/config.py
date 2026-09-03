import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Configuracion necesaria para ejecutar el bot."""

    discord_token: str
    guild_id: int
    sync_commands: bool
    llama_cpp_base_url: str
    llama_cpp_model: str
    llama_cpp_timeout_seconds: float
    llama_cpp_context_tokens: int
    llama_cpp_max_response_tokens: int
    database_url: str
    chat_rate_limit_seconds: float
    chat_max_recent_messages: int
    rag_embedding_base_url: str
    rag_embedding_model: str
    rag_top_k: int
    rag_min_score: float
    qdrant_url: str
    qdrant_collection: str
    qdrant_vector_name: str


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno requerida: {name}")
    return value


def _get_bool_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_positive_float_env(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed_value = float(value)
    except ValueError as error:
        raise RuntimeError(f"{name} debe ser un numero") from error

    if parsed_value <= 0:
        raise RuntimeError(f"{name} debe ser mayor que cero")
    return parsed_value


def _get_positive_int_env(name: str, *, default: int, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        parsed_value = int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} debe ser un numero entero") from error

    if parsed_value < minimum:
        if minimum == 1:
            raise RuntimeError(f"{name} debe ser mayor que cero")
        raise RuntimeError(f"{name} debe ser mayor o igual que {minimum}")
    return parsed_value


@lru_cache
def get_settings() -> Settings:
    """Carga una vez la configuracion desde el archivo .env y el entorno."""
    load_dotenv()

    guild_id = _get_required_env("DISCORD_GUILD_ID")
    try:
        parsed_guild_id = int(guild_id)
    except ValueError as error:
        raise RuntimeError("DISCORD_GUILD_ID debe ser un numero entero") from error

    return Settings(
        discord_token=_get_required_env("DISCORD_TOKEN"),
        guild_id=parsed_guild_id,
        # Se puede desactivar mientras se usa watchfiles para no sincronizar en
        # cada reinicio. Activalo cuando agregues o modifiques slash commands.
        sync_commands=_get_bool_env("DISCORD_SYNC_COMMANDS", default=True),
        llama_cpp_base_url=os.getenv(
            "LLAMA_CPP_BASE_URL",
            "http://127.0.0.1:8080/v1",
        ).rstrip("/"),
        llama_cpp_model=os.getenv("LLAMA_CPP_MODEL", "qwen2.5-1.5b-instruct-q4_k_m.gguf"),
        llama_cpp_timeout_seconds=_get_positive_float_env(
            "LLAMA_CPP_TIMEOUT_SECONDS",
            default=600,
        ),
        llama_cpp_context_tokens=_get_positive_int_env(
            "LLAMA_CPP_CONTEXT_TOKENS",
            default=8192,
        ),
        llama_cpp_max_response_tokens=_get_positive_int_env(
            "LLAMA_CPP_MAX_RESPONSE_TOKENS",
            default=256,
        ),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://cosmecito:cosmecito@127.0.0.1:5432/cosmecito",
        ),
        chat_rate_limit_seconds=_get_positive_float_env(
            "CHAT_RATE_LIMIT_SECONDS",
            default=10,
        ),
        chat_max_recent_messages=_get_positive_int_env(
            "CHAT_MAX_RECENT_MESSAGES",
            default=10,
            minimum=2,
        ),
        rag_embedding_base_url=os.getenv(
            "RAG_EMBEDDING_BASE_URL",
            "http://127.0.0.1:8081/v1",
        ).rstrip("/"),
        rag_embedding_model=os.getenv(
            "RAG_EMBEDDING_MODEL",
            "qwen3-embedding-4b-q4_k_m.gguf",
        ),
        rag_top_k=_get_positive_int_env("RAG_TOP_K", default=4),
        rag_min_score=_get_positive_float_env("RAG_MIN_SCORE", default=0.45),
        qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "course_knowledge"),
        qdrant_vector_name=os.getenv("QDRANT_VECTOR_NAME", "embedding"),
    )
