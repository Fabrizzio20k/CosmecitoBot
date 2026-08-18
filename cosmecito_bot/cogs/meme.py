from io import BytesIO

import discord
from discord import app_commands
from discord.ext import commands

from cosmecito_bot.services.meme_generator import MemeGenerationError, MemeGenerator


class MemeCog(commands.Cog):
    max_image_size = 10 * 1024 * 1024
    max_text_length = 500

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.generator = MemeGenerator()

    @app_commands.command(name="meme", description="Crea un meme a partir de una imagen")
    @app_commands.describe(
        imagen="La imagen que se usará como base",
        texto_arriba="Texto de la parte superior",
        texto_abajo="Texto de la parte inferior",
    )
    async def meme(
        self,
        interaction: discord.Interaction,
        imagen: discord.Attachment,
        texto_arriba: str | None = None,
        texto_abajo: str | None = None,
    ) -> None:
        if not texto_arriba and not texto_abajo:
            await interaction.response.send_message(
                "Escribe texto arriba, abajo o en ambos campos.",
                ephemeral=True,
            )
            return

        if len(texto_arriba or "") + len(texto_abajo or "") > self.max_text_length:
            await interaction.response.send_message(
                "El texto combinado no puede superar 500 caracteres.",
                ephemeral=True,
            )
            return

        if imagen.size > self.max_image_size:
            await interaction.response.send_message(
                "La imagen no puede superar 10 MB.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            meme_bytes = self.generator.generate(
                await imagen.read(),
                texto_arriba or "",
                texto_abajo or "",
            )
        except MemeGenerationError as error:
            await interaction.edit_original_response(content=str(error))
            return

        file = discord.File(BytesIO(meme_bytes), filename="meme.jpg")
        await interaction.edit_original_response(attachments=[file])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemeCog(bot))
