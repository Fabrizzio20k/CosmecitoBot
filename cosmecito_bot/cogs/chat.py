import discord
from discord import app_commands
from discord.ext import commands
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from cosmecito_bot.config import Settings


class ChatCog(commands.Cog):
    max_question_length = 2_000
    max_discord_message_length = 2_000

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings: Settings = bot.settings
        self.model = settings.llama_cpp_model
        self.client = AsyncOpenAI(
            base_url=settings.llama_cpp_base_url,
            api_key="local-llama-cpp",
            timeout=settings.llama_cpp_timeout_seconds,
        )

    @app_commands.command(name="chat", description="Habla con el modelo local")
    @app_commands.describe(mensaje="Tu mensaje para el modelo")
    async def chat(self, interaction: discord.Interaction, mensaje: str) -> None:
        if not mensaje.strip():
            await interaction.response.send_message(
                "Escribe un mensaje para el modelo.",
                ephemeral=True,
            )
            return

        if len(mensaje) > self.max_question_length:
            await interaction.response.send_message(
                "El mensaje no puede superar 2000 caracteres.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)

        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": mensaje}],
                max_tokens=512,
            )
        except APITimeoutError:
            await interaction.edit_original_response(
                content="El modelo tardó demasiado en responder.",
            )
            return
        except APIConnectionError:
            await interaction.edit_original_response(
                content="No se pudo conectar con llama.cpp local.",
            )
            return
        except APIStatusError as error:
            await interaction.edit_original_response(
                content=f"llama.cpp respondió con error {error.status_code}.",
            )
            return

        response = completion.choices[0].message.content or "El modelo no devolvió texto."
        chunks = list(self._split_response(response))
        await interaction.edit_original_response(content=chunks[0])

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    def _split_response(self, response: str):
        remaining = response.strip()
        while len(remaining) > self.max_discord_message_length:
            split_at = remaining.rfind("\n", 0, self.max_discord_message_length)
            if split_at <= 0:
                split_at = self.max_discord_message_length
            yield remaining[:split_at]
            remaining = remaining[split_at:].lstrip()
        yield remaining or "El modelo no devolvió texto."


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
