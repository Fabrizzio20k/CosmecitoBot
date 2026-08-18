import discord
from discord import app_commands
from discord.ext import commands


class PingCog(commands.Cog):
    """Comandos de diagnostico del bot."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Comprueba si el bot funciona")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🏓 Pong! El bot funciona.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingCog(bot))
