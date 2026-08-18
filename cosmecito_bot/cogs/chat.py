import asyncio
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from cosmecito_bot.config import Settings
from cosmecito_bot.services.chat_history import ChatHistory, ChatMessage, Conversation


class ChatCog(commands.Cog):
    max_question_length = 2_000
    max_discord_message_length = 2_000
    minimum_recent_messages = 6
    system_prompt = (
        "Responde en español, de forma directa y breve. "
        "Usa como máximo cuatro oraciones salvo que el usuario pida detalle."
    )
    summary_prompt = (
        "Actualiza esta memoria de conversación en español. Conserva únicamente "
        "hechos, decisiones, datos, tareas, preferencias y preguntas pendientes "
        "necesarios para continuar. No inventes información. Sé conciso."
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings: Settings = bot.settings
        self.model = settings.llama_cpp_model
        self.max_response_tokens = settings.llama_cpp_max_response_tokens
        self.context_budget = max(
            1_024,
            settings.llama_cpp_context_tokens - self.max_response_tokens - 512,
        )
        self.history = ChatHistory(settings.chat_database_path)
        self.locks: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
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
        user_id = interaction.user.id
        channel_id = interaction.channel_id or 0
        lock = self.locks[(user_id, channel_id)]

        try:
            async with lock:
                conversation = self.history.get_conversation(user_id, channel_id)
                conversation = await self._compact_history(
                    user_id,
                    channel_id,
                    conversation,
                    mensaje,
                )
                completion = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self._build_messages(conversation, mensaje),
                    max_tokens=self.max_response_tokens,
                )
                response = completion.choices[0].message.content or "El modelo no devolvió texto."
                self.history.add_message(user_id, channel_id, "user", mensaje)
                self.history.add_message(user_id, channel_id, "assistant", response)
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

        chunks = list(self._split_response(response))
        await interaction.edit_original_response(content=chunks[0])

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)

    async def _compact_history(
        self,
        user_id: int,
        channel_id: int,
        conversation: Conversation,
        next_message: str,
    ) -> Conversation:
        while self._estimate_tokens(self._build_messages(conversation, next_message)) > self.context_budget:
            eligible_count = max(1, len(conversation.messages) - self.minimum_recent_messages)
            messages_to_summarize = self._select_messages_to_summarize(
                conversation.messages[:eligible_count],
            )
            summary = await self._summarize(conversation.summary, messages_to_summarize)
            self.history.replace_summary(
                user_id,
                channel_id,
                summary,
                [message.id for message in messages_to_summarize],
            )
            conversation = self.history.get_conversation(user_id, channel_id)

        return conversation

    def _select_messages_to_summarize(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        selected: list[ChatMessage] = []
        token_limit = 1_500
        tokens = 0

        for message in messages:
            message_tokens = self._estimate_tokens([self._message_to_dict(message)])
            if selected and tokens + message_tokens > token_limit:
                break
            selected.append(message)
            tokens += message_tokens

        return selected or messages[:1]

    async def _summarize(self, current_summary: str, messages: list[ChatMessage]) -> str:
        serialized_messages = "\n".join(
            f"{message.role}: {message.content}" for message in messages
        )
        summary_input = (
            f"Memoria anterior:\n{current_summary or 'Sin memoria anterior.'}\n\n"
            f"Fragmento a integrar:\n{serialized_messages}"
        )
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.summary_prompt},
                {"role": "user", "content": summary_input},
            ],
            max_tokens=384,
        )
        return completion.choices[0].message.content or current_summary

    def _build_messages(self, conversation: Conversation, next_message: str) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if conversation.summary:
            messages.append(
                {
                    "role": "system",
                    "content": f"Memoria de la conversación:\n{conversation.summary}",
                },
            )
        messages.extend(self._message_to_dict(message) for message in conversation.messages)
        messages.append({"role": "user", "content": next_message})
        return messages

    def _message_to_dict(self, message: ChatMessage) -> dict[str, str]:
        return {"role": message.role, "content": message.content}

    def _estimate_tokens(self, messages: list[dict[str, str]]) -> int:
        return sum(len(message["content"]) // 4 + 4 for message in messages)

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
