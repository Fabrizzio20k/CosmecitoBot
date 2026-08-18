import os

import discord
from discord import app_commands
from dotenv import load_dotenv

# Cargar .env
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))


class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()

        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # Nuestro servidor de pruebas
        guild = discord.Object(id=GUILD_ID)

        # Registrar los comandos solamente
        # en este servidor
        self.tree.copy_global_to(guild=guild)

        commands = await self.tree.sync(guild=guild)

        print(f"✅ {len(commands)} comandos sincronizados")


bot = MyBot()


# ----------------------------
# COMANDO /ping
# ----------------------------


@bot.tree.command(name="ping", description="Comprueba si el bot funciona")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong! El bot funciona.")


# ----------------------------
# BOT ONLINE
# ----------------------------


@bot.event
async def on_ready():
    print("-----------------------------")
    print(f"✅ Bot conectado como: {bot.user}")
    print(f"✅ ID del bot: {bot.user.id}")
    print(f"✅ Servidor de prueba: {GUILD_ID}")
    print("-----------------------------")


# Iniciar bot
bot.run(TOKEN)
