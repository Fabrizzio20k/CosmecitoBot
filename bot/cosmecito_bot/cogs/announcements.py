from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import selectinload

from cosmecito_db.models import (
    Announcement,
    AnnouncementChannel,
    MessageAttachment,
    Reminder,
    ReminderRecipient,
)
from cosmecito_db.reminder_recurrence import (
    LIMA_TIMEZONE,
    next_occurrence as next_reminder_occurrence,
    normalize_recurrence,
)
from cosmecito_db.scheduling import next_occurrence as next_announcement_occurrence


class AnnouncementCog(commands.Cog):
    """Publica anuncios de canal y recordatorios privados persistidos."""

    max_content_length = 2_000
    max_attachment_bytes = 8 * 1024 * 1024
    stale_claim_after = timedelta(minutes=5)
    lima_timezone = LIMA_TIMEZONE

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sessions = bot.database.sessions
        self.scheduler_client = AsyncOpenAI(
            base_url=bot.settings.llama_cpp_base_url,
            api_key="local-llama-cpp",
            timeout=bot.settings.llama_cpp_timeout_seconds,
        )
        self.delivery_loop.start()

    def cog_unload(self) -> None:
        self.delivery_loop.cancel()

    @tasks.loop(seconds=20)
    async def delivery_loop(self) -> None:
        await self._dispatch_announcements()
        await self._dispatch_reminders()

    @delivery_loop.before_loop
    async def wait_until_ready(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="anuncio", description="Interpreta y programa un anuncio")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal donde se publicará el anuncio",
        mensaje="Texto del anuncio",
        fecha="Opcional. Ej.: 'mañana 18:30' o 'cada lunes a las 09:00' (hora Lima)",
        archivo="Archivo opcional que se enviará con el anuncio",
    )
    async def create_announcement(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        mensaje: str,
        fecha: str | None = None,
        archivo: discord.Attachment | None = None,
    ) -> None:
        if not self._can_manage(interaction):
            await interaction.response.send_message(
                "Necesitas el permiso Gestionar servidor.", ephemeral=True
            )
            return
        if not mensaje.strip() or len(mensaje) > self.max_content_length:
            await interaction.response.send_message(
                "El mensaje debe tener entre 1 y 2000 caracteres.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            scheduled_for, recurrence = (
                await self._interpret_schedule(fecha)
                if fecha else (datetime.now(UTC), "once")
            )
        except ValueError as error:
            await interaction.edit_original_response(content=str(error))
            return

        async def persist() -> str:
            announcement = await self._create_announcement(
                content=mensaje.strip(),
                channel_ids=[canal.id],
                scheduled_for=scheduled_for,
                created_by=interaction.user.id,
                recurrence=recurrence,
                attachments=await self._attachments_from_discord(archivo),
            )
            return f"Anuncio `{announcement.id}` confirmado para {self._format_lima(scheduled_for)}."

        await self._request_confirmation(
            interaction,
            title=f"Anuncio en #{canal.name}",
            scheduled_for=scheduled_for,
            recurrence=recurrence,
            schedule_text=fecha,
            persist=persist,
        )

    @app_commands.command(name="recordatorio", description="Interpreta y programa un recordatorio privado")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        destinatarios="Menciona personas, un rol y/o escribe 'yo': @persona @rol yo",
        mensaje="Texto que se enviará por mensaje privado",
        fecha="Opcional. Ej.: 'mañana 18:30' o 'todos los días a las 09:00' (hora Lima)",
        archivo="Archivo opcional que se enviará por DM",
    )
    async def create_reminder(
        self,
        interaction: discord.Interaction,
        destinatarios: str,
        mensaje: str,
        fecha: str | None = None,
        archivo: discord.Attachment | None = None,
    ) -> None:
        if not self._can_manage(interaction):
            await interaction.response.send_message(
                "Necesitas el permiso Gestionar servidor.", ephemeral=True
            )
            return
        if not mensaje.strip() or len(mensaje) > self.max_content_length:
            await interaction.response.send_message(
                "El mensaje debe tener entre 1 y 2000 caracteres.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            user_ids, role_id, recipient_label = self._parse_combined_recipients(
                destinatarios, interaction.user.id, interaction.guild
            )
            scheduled_for, recurrence = (
                await self._interpret_schedule(fecha)
                if fecha else (datetime.now(UTC), "once")
            )
            recurrence, interval, weekdays, until = normalize_recurrence(
                recurrence, 1, (), scheduled_for, None
            )
        except ValueError as error:
            await interaction.edit_original_response(content=str(error))
            return

        async def persist() -> str:
            reminder = await self._create_reminder(
                announcement_id=None,
                content=mensaje.strip(),
                scheduled_for=scheduled_for,
                user_ids=user_ids,
                role_id=role_id,
                recurrence=recurrence,
                recurrence_interval=interval,
                recurrence_weekdays=weekdays,
                recurrence_until=until,
                attachments=await self._attachments_from_discord(archivo),
            )
            return f"Recordatorio `{reminder.id}` confirmado para {self._format_lima(scheduled_for)}."

        await self._request_confirmation(
            interaction,
            title=f"Recordatorio privado para {recipient_label}",
            scheduled_for=scheduled_for,
            recurrence=recurrence,
            schedule_text=fecha,
            persist=persist,
        )

    async def _create_announcement(
        self,
        *,
        content: str,
        channel_ids: list[int],
        scheduled_for: datetime,
        created_by: int | None,
        recurrence: str = "once",
        attachments: list[MessageAttachment] | None = None,
    ) -> Announcement:
        async with self.sessions() as session, session.begin():
            announcement = Announcement(
                content=content,
                created_by=created_by,
                status="scheduled",
                recurrence=recurrence,
                attachments=attachments or [],
            )
            announcement.channels = [
                AnnouncementChannel(
                    channel_id=channel_id, scheduled_for=scheduled_for, status="queued"
                )
                for channel_id in set(channel_ids)
            ]
            session.add(announcement)
        return announcement

    async def _create_reminder(
        self,
        *,
        announcement_id: uuid.UUID | None,
        content: str,
        scheduled_for: datetime,
        user_ids: list[int],
        role_id: int | None,
        recurrence: str,
        recurrence_interval: int,
        recurrence_weekdays: tuple[int, ...],
        recurrence_until: datetime | None,
        attachments: list[MessageAttachment] | None = None,
    ) -> Reminder | None:
        async with self.sessions() as session, session.begin():
            if announcement_id is not None:
                announcement = await session.get(Announcement, announcement_id)
                if announcement is None or announcement.status == "cancelled":
                    return None
            reminder_id = uuid.uuid4()
            reminder = Reminder(
                id=reminder_id,
                announcement_id=announcement_id,
                content=content,
                scheduled_for=scheduled_for,
                target_role_id=role_id,
                recurrence=recurrence,
                recurrence_interval=recurrence_interval,
                recurrence_weekdays=",".join(str(day) for day in recurrence_weekdays),
                recurrence_until=recurrence_until,
                recurrence_group_id=reminder_id if recurrence != "once" else None,
                status="scheduled",
            )
            reminder.recipients = [
                ReminderRecipient(user_id=user_id, source="direct", status="queued")
                for user_id in set(user_ids)
            ]
            reminder.attachments = attachments or []
            session.add(reminder)
        return reminder

    async def _interpret_schedule(self, instruction: str) -> tuple[datetime, str]:
        now = datetime.now(UTC)
        prompt = """Interpreta una instrucción de fecha en español para America/Lima.
Devuelve exclusivamente JSON: {"date":"YYYY-MM-DD","time":"HH:MM","recurrence":"once|daily|weekly|monthly"}.
Usa once si no hay repetición. No inventes una fecha u hora si la instrucción es ambigua."""
        try:
            completion = await self.scheduler_client.chat.completions.create(
                model=self.bot.settings.llama_cpp_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "now_lima": now.astimezone(self.lima_timezone).strftime("%Y-%m-%d %H:%M"),
                                "instruction": instruction.strip(),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=120,
            )
        except (APITimeoutError, APIConnectionError, APIStatusError) as error:
            raise ValueError("No se pudo consultar el modelo para interpretar la fecha.") from error
        match = re.search(r"\{.*\}", (completion.choices[0].message.content or "").strip(), re.DOTALL)
        if match is None:
            raise ValueError("No pude interpretar fecha, hora y repetición. Corrige el texto e inténtalo otra vez.")
        try:
            result = json.loads(match.group())
            if not (
                isinstance(result.get("date"), str)
                and isinstance(result.get("time"), str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["date"])
                and re.fullmatch(r"\d{2}:\d{2}", result["time"])
            ):
                raise ValueError
            scheduled_for = datetime.combine(
                date.fromisoformat(result["date"]),
                time.fromisoformat(result["time"]),
                tzinfo=self.lima_timezone,
            ).astimezone(UTC)
            recurrence = result["recurrence"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("La interpretación del modelo no es válida. Corrige el texto e inténtalo otra vez.") from error
        if recurrence not in {"once", "daily", "weekly", "monthly"} or scheduled_for <= now:
            raise ValueError("La fecha debe ser futura y la repetición debe ser una vez, diaria, semanal o mensual.")
        return scheduled_for, recurrence

    async def _attachments_from_discord(
        self, attachment: discord.Attachment | None
    ) -> list[MessageAttachment]:
        if attachment is None:
            return []
        if attachment.size > self.max_attachment_bytes:
            raise ValueError("El archivo supera el límite de 8 MiB.")
        data = await attachment.read()
        return [
            MessageAttachment(
                filename=attachment.filename[:255],
                content_type=attachment.content_type,
                byte_size=len(data),
                data=data,
            )
        ]

    @staticmethod
    def _parse_combined_recipients(
        value: str, caller_id: int, guild: discord.Guild | None
    ) -> tuple[list[int], int | None, str]:
        """Parsea menciones Discord, nombres simples y la palabra `yo`."""
        user_ids = {int(match) for match in re.findall(r"<@!?(\d+)>", value)}
        role_ids = {int(match) for match in re.findall(r"<@&(\d+)>", value)}
        unresolved: list[str] = []
        if guild is not None:
            for raw_name in re.findall(r"(?<!<)@([^\s,@]+)", value):
                name = raw_name.rstrip(".,;:").casefold()
                matching_roles = [role for role in guild.roles if role.name.casefold() == name]
                matching_members = [
                    member
                    for member in guild.members
                    if name
                    in {
                        member.name.casefold(),
                        member.display_name.casefold(),
                        (member.global_name or "").casefold(),
                    }
                ]
                if len(matching_roles) + len(matching_members) == 1:
                    if matching_roles:
                        role_ids.add(matching_roles[0].id)
                    else:
                        user_ids.add(matching_members[0].id)
                elif name:
                    unresolved.append(f"@{raw_name}")
        normalized = value.casefold()
        if re.search(r"(?:^|[\s,])(?:yo|mí|mi)(?:$|[\s,])", normalized):
            user_ids.add(caller_id)
        if unresolved:
            raise ValueError(
                "No pude identificar " + ", ".join(unresolved) + ". "
                "Usa una mención real o un nombre único del servidor."
            )
        if len(role_ids) > 1:
            raise ValueError("Usa como máximo un rol por recordatorio; puedes combinarlo con varias personas.")
        if not user_ids and not role_ids:
            raise ValueError("Menciona al menos una persona, un rol o escribe 'yo'.")
        labels: list[str] = []
        if user_ids:
            labels.append(f"{len(user_ids)} persona{'s' if len(user_ids) != 1 else ''}")
        if role_ids:
            labels.append("un rol")
        return sorted(user_ids), next(iter(role_ids), None), " y ".join(labels)

    async def _request_confirmation(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        scheduled_for: datetime,
        recurrence: str,
        schedule_text: str | None,
        persist,
    ) -> None:
        def preview() -> str:
            return (
                f"**{title}**\n"
                f"Interpreté: **{self._format_lima(scheduled_for)}** · "
                f"**{self._recurrence_label(recurrence)}**.\n"
                "Confirma para guardarlo o elige **Corregir texto** para cambiar "
                "la fecha o la repetición."
            )

        view = discord.ui.View(timeout=180)
        confirm = discord.ui.Button(label="Confirmar", style=discord.ButtonStyle.success)
        cancel = discord.ui.Button(label="Corregir texto", style=discord.ButtonStyle.secondary)

        async def confirm_callback(button_interaction: discord.Interaction) -> None:
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message("Sólo quien creó la solicitud puede confirmarla.", ephemeral=True)
                return
            try:
                result = await persist()
            except (ValueError, discord.DiscordException) as error:
                await button_interaction.response.edit_message(content=f"No se pudo guardar: {error}", view=None)
                return
            await button_interaction.response.edit_message(content=f"✅ {result}", view=None)

        async def cancel_callback(button_interaction: discord.Interaction) -> None:
            if button_interaction.user.id != interaction.user.id:
                await button_interaction.response.send_message("Sólo quien creó la solicitud puede corregirla.", ephemeral=True)
                return

            class CorrectScheduleModal(discord.ui.Modal, title="Corregir programación"):
                instruction = discord.ui.TextInput(
                    label="Fecha y repetición en lenguaje natural",
                    placeholder="Ej.: mañana 18:30 o cada lunes a las 09:00",
                    default=schedule_text or "",
                    required=True,
                    max_length=300,
                )

                async def on_submit(self, modal_interaction: discord.Interaction) -> None:
                    nonlocal scheduled_for, recurrence
                    try:
                        scheduled_for, recurrence = await self_cog._interpret_schedule(
                            str(self.instruction.value)
                        )
                    except ValueError as error:
                        await modal_interaction.response.send_message(str(error), ephemeral=True)
                        return
                    await modal_interaction.response.defer(ephemeral=True)
                    await interaction.edit_original_response(content=preview(), view=view)
                    await modal_interaction.followup.send(
                        "Interpretación actualizada. Revísala y confirma cuando esté correcta.",
                        ephemeral=True,
                    )

            self_cog = self
            await button_interaction.response.send_modal(CorrectScheduleModal())

        confirm.callback = confirm_callback
        cancel.callback = cancel_callback
        view.add_item(confirm)
        view.add_item(cancel)
        await interaction.edit_original_response(content=preview(), view=view)

    async def _dispatch_announcements(self) -> None:
        for record_id, channel_id, content, attachments in await self._claim_due_channels():
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(
                    channel_id
                )
                if not isinstance(channel, discord.abc.Messageable):
                    raise RuntimeError("El destino no acepta mensajes")
                message = await channel.send(content, files=self._discord_files(attachments))
            except (discord.DiscordException, RuntimeError) as error:
                await self._finish_channel(record_id, error=str(error))
            else:
                await self._finish_channel(record_id, message_id=message.id)

    async def _claim_due_channels(
        self,
    ) -> list[tuple[int, int, str, list[tuple[str, str | None, bytes]]]]:
        now = datetime.now(UTC)
        stale_before = now - self.stale_claim_after
        async with self.sessions() as session, session.begin():
            rows = await session.scalars(
                select(AnnouncementChannel)
                .join(Announcement)
                .options(
                    selectinload(AnnouncementChannel.announcement).selectinload(
                        Announcement.attachments
                    )
                )
                .where(
                    AnnouncementChannel.scheduled_for <= now,
                    Announcement.status != "cancelled",
                    or_(
                        AnnouncementChannel.status == "queued",
                        and_(
                            AnnouncementChannel.status == "processing",
                            AnnouncementChannel.claimed_at < stale_before,
                        ),
                    ),
                )
                .order_by(AnnouncementChannel.scheduled_for)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
            records = rows.all()
            for record in records:
                await session.execute(
                    update(AnnouncementChannel)
                    .where(AnnouncementChannel.id == record.id)
                    .values(
                        status="processing",
                        claimed_at=now,
                        attempts=AnnouncementChannel.attempts + 1,
                    )
                )
        return [
            (
                record.id,
                record.channel_id,
                record.announcement.content,
                [
                    (attachment.filename, attachment.content_type, attachment.data)
                    for attachment in record.announcement.attachments
                ],
            )
            for record in records
        ]

    async def _finish_channel(
        self, record_id: int, message_id: int | None = None, error: str | None = None
    ) -> None:
        async with self.sessions() as session, session.begin():
            record = await session.get(AnnouncementChannel, record_id, with_for_update=True)
            if record is None:
                return
            record.status = "sent" if message_id else "failed"
            record.discord_message_id = message_id
            record.sent_at = datetime.now(UTC) if message_id else None
            record.error = error[:1_000] if error else None
            announcement = await session.scalar(
                select(Announcement)
                .where(Announcement.id == record.announcement_id)
                .options(
                    selectinload(Announcement.channels), selectinload(Announcement.attachments)
                )
                .with_for_update()
            )
            if announcement is not None:
                # El bloqueo del padre serializa el cálculo y evita crear cero
                # o dos ocurrencias cuando varios canales terminan a la vez.
                channel_statuses = list(
                    await session.scalars(
                        select(AnnouncementChannel.status).where(
                            AnnouncementChannel.announcement_id == record.announcement_id
                        )
                    )
                )
                announcement.status = self._aggregate_status(channel_statuses)
                if (
                    announcement.status in {"completed", "failed", "partially_failed"}
                    and announcement.recurrence != "once"
                    and announcement.recurrence_scheduled_at is None
                ):
                    next_scheduled_for = next_announcement_occurrence(
                        record.scheduled_for, announcement.recurrence
                    )
                    if next_scheduled_for is not None:
                        announcement.recurrence_scheduled_at = next_scheduled_for
                        session.add(
                            Announcement(
                                content=announcement.content,
                                created_by=announcement.created_by,
                                status="scheduled",
                                recurrence=announcement.recurrence,
                                channels=[
                                    AnnouncementChannel(
                                        channel_id=channel.channel_id,
                                        scheduled_for=next_scheduled_for,
                                        status="queued",
                                    )
                                    for channel in announcement.channels
                                ],
                                attachments=[
                                    self._copy_attachment(attachment)
                                    for attachment in announcement.attachments
                                ],
                            )
                        )

    async def _dispatch_reminders(self) -> None:
        for reminder_id, content, role_id, attachments in await self._claim_due_reminders():
            if role_id is not None:
                recipients = await self._members_for_role(role_id)
                if recipients is None:
                    await self._finish_reminder_without_delivery(
                        reminder_id, "No se encontró el rol destinatario"
                    )
                    continue
                await self._add_role_recipients(reminder_id, recipients)
            for recipient_id, user_id in await self._claim_recipients(reminder_id):
                try:
                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                    await user.send(content, files=self._discord_files(attachments))
                except discord.DiscordException as error:
                    await self._finish_recipient(recipient_id, error=str(error))
                else:
                    await self._finish_recipient(recipient_id)
            await self._finish_reminder_if_ready(reminder_id)

    async def _claim_due_reminders(
        self,
    ) -> list[tuple[uuid.UUID, str, int | None, list[tuple[str, str | None, bytes]]]]:
        now = datetime.now(UTC)
        stale_before = now - self.stale_claim_after
        async with self.sessions() as session, session.begin():
            rows = await session.scalars(
                select(Reminder)
                .options(selectinload(Reminder.attachments))
                .where(
                    Reminder.scheduled_for <= now,
                    or_(
                        Reminder.status == "scheduled",
                        and_(Reminder.status == "processing", Reminder.claimed_at < stale_before),
                    ),
                )
                .order_by(Reminder.scheduled_for)
                .limit(10)
                .with_for_update(skip_locked=True)
            )
            reminders = rows.all()
            for reminder in reminders:
                await session.execute(
                    update(Reminder)
                    .where(Reminder.id == reminder.id)
                    .values(status="processing", claimed_at=now)
                )
        return [
            (
                reminder.id,
                reminder.content,
                reminder.target_role_id,
                [
                    (attachment.filename, attachment.content_type, attachment.data)
                    for attachment in reminder.attachments
                ],
            )
            for reminder in reminders
        ]

    async def _members_for_role(self, role_id: int) -> list[int] | None:
        guild = self.bot.get_guild(self.bot.settings.guild_id)
        if guild is None:
            return None
        role = guild.get_role(role_id)
        if role is None:
            return None
        members = role.members
        if not members:
            try:
                members = [
                    member
                    async for member in guild.fetch_members(limit=None)
                    if role in member.roles
                ]
            except discord.DiscordException:
                return None
        return [member.id for member in members if not member.bot]

    async def _add_role_recipients(self, reminder_id: uuid.UUID, user_ids: list[int]) -> None:
        async with self.sessions() as session, session.begin():
            existing = set(
                await session.scalars(
                    select(ReminderRecipient.user_id).where(
                        ReminderRecipient.reminder_id == reminder_id
                    )
                )
            )
            session.add_all(
                ReminderRecipient(
                    user_id=user_id, reminder_id=reminder_id, source="role", status="queued"
                )
                for user_id in set(user_ids) - existing
            )

    async def _claim_recipients(self, reminder_id: uuid.UUID) -> list[tuple[int, int]]:
        now = datetime.now(UTC)
        stale_before = now - self.stale_claim_after
        async with self.sessions() as session, session.begin():
            rows = await session.execute(
                select(ReminderRecipient.id, ReminderRecipient.user_id)
                .where(
                    ReminderRecipient.reminder_id == reminder_id,
                    or_(
                        ReminderRecipient.status == "queued",
                        and_(
                            ReminderRecipient.status == "processing",
                            ReminderRecipient.claimed_at < stale_before,
                        ),
                    ),
                )
                .limit(500)
                .with_for_update(skip_locked=True)
            )
            recipients = rows.all()
            for recipient_id, _ in recipients:
                await session.execute(
                    update(ReminderRecipient)
                    .where(ReminderRecipient.id == recipient_id)
                    .values(
                        status="processing", claimed_at=now, attempts=ReminderRecipient.attempts + 1
                    )
                )
        return recipients

    async def _finish_recipient(self, recipient_id: int, error: str | None = None) -> None:
        async with self.sessions() as session, session.begin():
            recipient = await session.get(ReminderRecipient, recipient_id, with_for_update=True)
            if recipient is None:
                return
            recipient.status = "failed" if error else "sent"
            recipient.error = error[:1_000] if error else None
            recipient.sent_at = None if error else datetime.now(UTC)

    async def _finish_reminder_without_delivery(self, reminder_id: uuid.UUID, error: str) -> None:
        async with self.sessions() as session, session.begin():
            reminder = await session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is not None and reminder.status == "processing":
                reminder.status = "failed"
                await self._schedule_next_reminder(session, reminder)

    async def _finish_reminder_if_ready(self, reminder_id: uuid.UUID) -> None:
        async with self.sessions() as session, session.begin():
            reminder = await session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None:
                return
            if reminder.status != "processing":
                return
            statuses = list(
                await session.scalars(
                    select(ReminderRecipient.status).where(
                        ReminderRecipient.reminder_id == reminder_id
                    )
                )
            )
            if any(status in {"queued", "processing"} for status in statuses):
                return
            reminder.status = (
                "failed"
                if statuses and all(status == "failed" for status in statuses)
                else "completed"
            )
            await self._schedule_next_reminder(session, reminder)

    async def _schedule_next_reminder(self, session, reminder: Reminder) -> None:
        if reminder.recurrence == "once":
            return
        weekdays = tuple(int(value) for value in reminder.recurrence_weekdays.split(",") if value)
        next_scheduled_for = next_reminder_occurrence(
            reminder.scheduled_for,
            reminder.recurrence,
            reminder.recurrence_interval,
            weekdays,
            reminder.recurrence_until,
        )
        if next_scheduled_for is None:
            return
        direct_user_ids = list(
            await session.scalars(
                select(ReminderRecipient.user_id).where(
                    ReminderRecipient.reminder_id == reminder.id,
                    ReminderRecipient.source == "direct",
                )
            )
        )
        attachments = list(
            await session.scalars(
                select(MessageAttachment).where(MessageAttachment.reminder_id == reminder.id)
            )
        )
        session.add(
            Reminder(
                id=uuid.uuid4(),
                announcement_id=reminder.announcement_id,
                content=reminder.content,
                scheduled_for=next_scheduled_for,
                target_role_id=reminder.target_role_id,
                status="scheduled",
                recurrence=reminder.recurrence,
                recurrence_interval=reminder.recurrence_interval,
                recurrence_weekdays=reminder.recurrence_weekdays,
                recurrence_until=reminder.recurrence_until,
                recurrence_group_id=reminder.recurrence_group_id,
                recipients=[
                    ReminderRecipient(user_id=user_id, source="direct", status="queued")
                    for user_id in direct_user_ids
                ],
                attachments=[self._copy_attachment(attachment) for attachment in attachments],
            )
        )

    @staticmethod
    def _copy_attachment(attachment: MessageAttachment) -> MessageAttachment:
        return MessageAttachment(
            filename=attachment.filename,
            content_type=attachment.content_type,
            byte_size=attachment.byte_size,
            data=attachment.data,
        )

    @staticmethod
    def _discord_files(attachments: list[tuple[str, str | None, bytes]]) -> list[discord.File]:
        return [
            discord.File(BytesIO(data), filename=filename, description=content_type)
            for filename, content_type, data in attachments
        ]

    @staticmethod
    def _aggregate_status(statuses: list[str]) -> str:
        if any(status in {"queued", "processing"} for status in statuses):
            return "scheduled"
        if statuses and all(status == "sent" for status in statuses):
            return "completed"
        if statuses and all(status == "failed" for status in statuses):
            return "failed"
        return "partially_failed"

    @staticmethod
    def _can_manage(interaction: discord.Interaction) -> bool:
        return (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.manage_guild
        )

    @staticmethod
    def _parse_weekdays(value: str | None) -> tuple[int, ...]:
        if not value:
            return ()
        names = {
            "lun": 0,
            "lunes": 0,
            "mar": 1,
            "martes": 1,
            "mie": 2,
            "miercoles": 2,
            "jue": 3,
            "jueves": 3,
            "vie": 4,
            "viernes": 4,
            "sab": 5,
            "sabado": 5,
            "dom": 6,
            "domingo": 6,
        }
        values = [
            part.strip().casefold().replace("é", "e").replace("á", "a") for part in value.split(",")
        ]
        try:
            return tuple(sorted({names[item] for item in values if item}))
        except KeyError as error:
            raise ValueError("Usa días separados por coma, por ejemplo: lun, mie, vie.") from error

    @staticmethod
    def _recurrence_label(recurrence: str) -> str:
        labels = {"once": "una vez", "daily": "diario", "weekly": "semanal", "monthly": "mensual"}
        return labels[recurrence]

    @staticmethod
    def _parse_lima_datetime(value: str | None, *, required: bool = False) -> datetime:
        if not value:
            if required:
                raise ValueError("Indica fecha y hora Lima, por ejemplo 'mañana 18:30'.")
            return datetime.now(UTC)
        normalized = " ".join(value.casefold().replace("mañana", "manana").split())
        now_lima = datetime.now(AnnouncementCog.lima_timezone)
        relative_dates = {"hoy": now_lima.date(), "manana": (now_lima + timedelta(days=1)).date()}
        try:
            day_word, time_text = normalized.split(maxsplit=1)
            if day_word in relative_dates:
                hour, minute = (int(part) for part in time_text.split(":"))
                return (
                    datetime.combine(
                        relative_dates[day_word],
                        datetime.min.time(),
                        tzinfo=AnnouncementCog.lima_timezone,
                    )
                    .replace(hour=hour, minute=minute)
                    .astimezone(UTC)
                )
        except ValueError as error:
            pass
        try:
            date_text, time_text = normalized.split(maxsplit=1)
            hour, minute = (int(part) for part in time_text.split(":"))
            date_parts = [int(part) for part in date_text.split("/")]
            if len(date_parts) == 2:
                day, month = date_parts
                year = now_lima.year
            elif len(date_parts) == 3:
                day, month, year = date_parts
            else:
                raise ValueError
            return datetime(
                year, month, day, hour, minute, tzinfo=AnnouncementCog.lima_timezone
            ).astimezone(UTC)
        except ValueError as error:
            raise ValueError(
                "Usa hora Lima: 'hoy 18:30', 'mañana 09:00' o '15/09 14:00'."
            ) from error

    @staticmethod
    def _format_lima(value: datetime) -> str:
        return value.astimezone(AnnouncementCog.lima_timezone).strftime("%d/%m/%Y %H:%M (Lima)")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnouncementCog(bot))
