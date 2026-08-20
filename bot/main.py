from cosmecito_bot.bot import CosmecitoBot
from cosmecito_bot.config import get_settings


def main() -> None:
    settings = get_settings()
    bot = CosmecitoBot(settings)
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
