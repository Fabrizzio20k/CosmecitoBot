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
        llama_cpp_model=os.getenv("LLAMA_CPP_MODEL", "Qwen3.5-9B-Q4_K_M.gguf"),
        llama_cpp_timeout_seconds=_get_positive_float_env(
            "LLAMA_CPP_TIMEOUT_SECONDS",
            default=600,
        ),
    )
