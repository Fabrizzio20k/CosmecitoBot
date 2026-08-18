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
        texto="Texto del meme. Usa | para separar arriba y abajo",
    )
    async def meme(
        self,
        interaction: discord.Interaction,
        imagen: discord.Attachment,
        texto: str,
    ) -> None:
        if not texto.strip():
            await interaction.response.send_message(
                "Escribe el texto que quieres poner en el meme.",
                ephemeral=True,
            )
            return

        if len(texto) > self.max_text_length:
            await interaction.response.send_message(
                "El texto no puede superar 500 caracteres.",
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
        texto_arriba, separador, texto_abajo = texto.partition("|")
        if not separador:
            texto_abajo = ""

        try:
            meme_bytes = self.generator.generate(
                await imagen.read(),
                texto_arriba,
                texto_abajo,
            )
        except MemeGenerationError as error:
            await interaction.edit_original_response(content=str(error))
            return

        file = discord.File(BytesIO(meme_bytes), filename="meme.jpg")
        await interaction.edit_original_response(attachments=[file])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemeCog(bot))
