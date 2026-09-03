import sys
from pathlib import Path

# Permite ejecutar `python main.py` desde bot/ y compartir el paquete de datos raíz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cosmecito_bot.bot import CosmecitoBot
from cosmecito_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    bot = CosmecitoBot(settings)
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
