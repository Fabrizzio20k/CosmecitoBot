import asyncio

import discord
from discord.ext import commands

from cosmecito_bot.config import Settings
from cosmecito_bot.services.rag import RagService
from cosmecito_bot.services.runtime_metrics import RuntimeMetrics
from cosmecito_db import Database

COGS = (
    "cosmecito_bot.cogs.ping",
    "cosmecito_bot.cogs.meme",
    "cosmecito_bot.cogs.chat",
    "cosmecito_bot.cogs.announcements",
)


class CosmecitoBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        # Necesario para expandir destinatarios de recordatorios por rol.
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.metrics = RuntimeMetrics()
        self.rag = RagService(settings, self.metrics)
        self.database = Database(settings.database_url)

    async def setup_hook(self) -> None:
        print(await self.rag.collection_status())
        await self.database.ping()
        print("✅ PostgreSQL conectado")
        print(await asyncio.to_thread(self.metrics.report))

        for extension in COGS:
            await self.load_extension(extension)

        if self.settings.sync_commands:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced_commands = await self.tree.sync(guild=guild)
            print(f"✅ {len(synced_commands)} comandos sincronizados")
        else:
            print("Sincronizacion de comandos desactivada")

    async def on_ready(self) -> None:
        print("-----------------------------")
        print(f"✅ Bot conectado como: {self.user}")
        print(f"✅ ID del bot: {self.user.id if self.user else 'desconocido'}")
        print(f"✅ Servidor de prueba: {self.settings.guild_id}")
        print("-----------------------------")

    async def close(self) -> None:
        await self.rag.close()
        await self.database.close()
        await super().close()
