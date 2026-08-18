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
    )
