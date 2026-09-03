import asyncio
import math
import time
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from cosmecito_bot.config import Settings
from cosmecito_bot.services.chat_history import ChatHistory, ChatMessage, Conversation
from cosmecito_bot.services.rag import RagError, RagService


class ChatCog(commands.Cog):
    max_question_length = 2_000
    max_discord_message_length = 2_000
    system_prompt = (
        "Responde en español, de forma directa y breve. "
        "Usa como máximo cuatro oraciones salvo que el usuario pida detalle."
    )
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings: Settings = bot.settings
        self.model = settings.llama_cpp_model
        self.max_response_tokens = settings.llama_cpp_max_response_tokens
        self.rate_limit_seconds = settings.chat_rate_limit_seconds
        self.max_recent_messages = settings.chat_max_recent_messages
        self.context_budget = max(
            1_024,
            settings.llama_cpp_context_tokens - self.max_response_tokens - 512,
        )
        # Reserva contexto para la pregunta, la memoria y la respuesta del modelo.
        self.rag_context_char_budget = max(250, self.context_budget // 3)
        self.history = ChatHistory(bot.database.sessions)
        self.rag: RagService = bot.rag
        self.metrics = bot.metrics
        self.locks: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        self.rate_limit_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last_question_at: dict[int, float] = {}
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

        user_id = interaction.user.id
        wait_seconds = await self._remaining_cooldown(user_id)
        if wait_seconds:
            await interaction.response.send_message(
                f"Espera {wait_seconds} s antes de hacer otra pregunta.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        channel_id = interaction.channel_id or 0
        lock = self.locks[(user_id, channel_id)]

        try:
            async with lock:
                sources = await self.rag.retrieve(mensaje)
                sources = self.rag.trim_to_context(
                    sources,
                    self.rag_context_char_budget,
                )
                rag_context = self.rag.format_context(sources)
                conversation = await self.history.get_conversation(user_id, channel_id)
                trimming_started_at = time.perf_counter()
                conversation = await self._compact_history(
                    user_id,
                    channel_id,
                    conversation,
                    mensaje,
                    rag_context,
                )
                self.metrics.record(
                    "history_trim",
                    time.perf_counter() - trimming_started_at,
                )
                generation_started_at = time.perf_counter()
                completion = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self._build_messages(
                        conversation,
                        mensaje,
                        rag_context,
                    ),
                    max_tokens=self.max_response_tokens,
                )
                self.metrics.record(
                    "chat_generation",
                    time.perf_counter() - generation_started_at,
                )
                response = completion.choices[0].message.content or "El modelo no devolvió texto."
                await self.history.add_message(user_id, channel_id, "user", mensaje)
                await self.history.add_message(user_id, channel_id, "assistant", response)
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
        except RagError as error:
            await interaction.edit_original_response(content=str(error))
            return

        chunks = list(self._split_response(response))
        await interaction.edit_original_response(content=chunks[0])

        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)
        print(await asyncio.to_thread(self.metrics.report))

    async def _compact_history(
        self,
        user_id: int,
        channel_id: int,
        conversation: Conversation,
        next_message: str,
        rag_context: str = "",
    ) -> Conversation:
        # Se reservan dos espacios para la pregunta actual y la respuesta antes
        # de persistirlas; asi la base nunca supera el limite configurado.
        # No se genera resumen: los mensajes mas antiguos se descartan.
        if conversation.summary:
            await self.history.clear_summary(user_id, channel_id)
            conversation = await self.history.get_conversation(user_id, channel_id)

        target_message_count = max(0, self.max_recent_messages - 2)
        while (
            len(conversation.messages) > target_message_count
            or self._estimate_tokens(
                self._build_messages(conversation, next_message, rag_context)
            )
            > self.context_budget
        ):
            if not conversation.messages:
                # La pregunta actual o el contexto RAG por si solos exceden el
                # presupuesto; borrar mas historial ya no puede ayudar.
                break

            excess_messages = max(1, len(conversation.messages) - target_message_count)
            messages_to_discard = conversation.messages[:excess_messages]
            await self.history.discard_messages(
                user_id,
                channel_id,
                [message.id for message in messages_to_discard],
            )
            conversation = await self.history.get_conversation(user_id, channel_id)

        return conversation

    async def _remaining_cooldown(self, user_id: int) -> int:
        """Registra una pregunta aceptada y devuelve la espera restante, si existe."""
        async with self.rate_limit_locks[user_id]:
            now = time.monotonic()
            previous_question_at = self.last_question_at.get(user_id)
            if previous_question_at is not None:
                remaining = self.rate_limit_seconds - (now - previous_question_at)
                if remaining > 0:
                    return math.ceil(remaining)

            self.last_question_at[user_id] = now
            return 0

    def _build_messages(
        self,
        conversation: Conversation,
        next_message: str,
        rag_context: str = "",
    ) -> list[dict[str, str]]:
        system_sections = [self.system_prompt]
        if rag_context:
            system_sections.append(
                "Contexto recuperado del curso. Si la pregunta depende de este "
                "material, responde solo con la información sustentada aquí. "
                "Si no alcanza, dilo claramente.\n\n"
                f"{rag_context}"
            )
        if conversation.summary:
            system_sections.append(f"Memoria de la conversación:\n{conversation.summary}")

        # Algunas plantillas Jinja de llama.cpp (incluida Qwen) solo aceptan
        # un mensaje system y exigen que sea el primero.
        messages = [{"role": "system", "content": "\n\n".join(system_sections)}]
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
