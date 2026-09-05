from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import and_, func, or_, select, update

from cosmecito_db.models import Announcement, AnnouncementChannel, Reminder, ReminderRecipient
from cosmecito_db.reminder_recurrence import LIMA_TIMEZONE, next_occurrence, normalize_recurrence


class AnnouncementCog(commands.Cog):
    """Publica anuncios de canal y recordatorios privados persistidos."""

    max_content_length = 2_000
    stale_claim_after = timedelta(minutes=5)
    lima_timezone = LIMA_TIMEZONE

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sessions = bot.database.sessions
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

    @app_commands.command(name="anuncio", description="Programa un anuncio para un canal")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal donde se publicará el anuncio",
        mensaje="Texto del anuncio",
        fecha="Opcional en hora Lima: 'hoy 18:30', 'mañana 09:00' o '15/09 14:00'",
    )
    async def create_announcement(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        mensaje: str,
        fecha: str | None = None,
    ) -> None:
        if not self._can_manage(interaction):
            await interaction.response.send_message("Necesitas el permiso Gestionar servidor.", ephemeral=True)
            return
        if not mensaje.strip() or len(mensaje) > self.max_content_length:
            await interaction.response.send_message("El mensaje debe tener entre 1 y 2000 caracteres.", ephemeral=True)
            return
        try:
            scheduled_for = self._parse_lima_datetime(fecha)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        announcement = await self._create_announcement(
            content=mensaje.strip(),
            channel_ids=[canal.id],
            scheduled_for=scheduled_for,
            created_by=interaction.user.id,
        )
        await interaction.response.send_message(
            f"Anuncio `{announcement.id}` programado para {self._format_lima(scheduled_for)}.",
            ephemeral=True,
        )
        if scheduled_for <= datetime.now(UTC):
            await self._dispatch_announcements()

    @app_commands.command(name="recordatorio", description="Programa un recordatorio privado")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.choices(
        repetir=[
            app_commands.Choice(name="Una vez", value="once"),
            app_commands.Choice(name="Cada día", value="daily"),
            app_commands.Choice(name="Semanal", value="weekly"),
            app_commands.Choice(name="Mensual", value="monthly"),
        ]
    )
    @app_commands.describe(
        mensaje="Texto que se enviará por mensaje privado",
        fecha="Hora Lima: 'hoy 18:30', 'mañana 09:00' o '15/09 14:00'",
        usuario="Destinatario individual (alternativa al rol)",
        rol="Destinatarios pertenecientes a este rol (alternativa al usuario)",
        anuncio_id="Opcional: ID del anuncio relacionado",
        repetir="Frecuencia del recordatorio",
        cada="Cada cuántos días o meses (sólo diaria o mensual)",
        dias_semana="Sólo semanal: lun, mie, vie",
        hasta="Fin opcional, en hora Lima; por ejemplo '30/09 18:30'",
    )
    async def create_reminder(
        self,
        interaction: discord.Interaction,
        mensaje: str,
        fecha: str,
        usuario: discord.Member | None = None,
        rol: discord.Role | None = None,
        anuncio_id: str | None = None,
        repetir: app_commands.Choice[str] | None = None,
        cada: app_commands.Range[int, 1, 365] = 1,
        dias_semana: str | None = None,
        hasta: str | None = None,
    ) -> None:
        if not self._can_manage(interaction):
            await interaction.response.send_message("Necesitas el permiso Gestionar servidor.", ephemeral=True)
            return
        if bool(usuario) == bool(rol):
            await interaction.response.send_message("Indica exactamente un usuario o un rol.", ephemeral=True)
            return
        if not mensaje.strip() or len(mensaje) > self.max_content_length:
            await interaction.response.send_message("El mensaje debe tener entre 1 y 2000 caracteres.", ephemeral=True)
            return
        try:
            announcement_id = uuid.UUID(anuncio_id) if anuncio_id else None
            scheduled_for = self._parse_lima_datetime(fecha, required=True)
            recurrence, recurrence_interval, recurrence_weekdays, recurrence_until = normalize_recurrence(
                repetir.value if repetir else "once",
                cada,
                self._parse_weekdays(dias_semana),
                scheduled_for,
                self._parse_lima_datetime(hasta, required=True) if hasta else None,
            )
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        reminder = await self._create_reminder(
            announcement_id=announcement_id,
            content=mensaje.strip(),
            scheduled_for=scheduled_for,
            user_ids=[usuario.id] if usuario else [],
            role_id=rol.id if rol else None,
            recurrence=recurrence,
            recurrence_interval=recurrence_interval,
            recurrence_weekdays=recurrence_weekdays,
            recurrence_until=recurrence_until,
        )
        if reminder is None:
            await interaction.response.send_message("No existe ese anuncio.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Recordatorio `{reminder.id}` programado para {self._format_lima(scheduled_for)} ({self._recurrence_label(recurrence)}).",
            ephemeral=True,
        )

    async def _create_announcement(
        self,
        *,
        content: str,
        channel_ids: list[int],
        scheduled_for: datetime,
        created_by: int | None,
    ) -> Announcement:
        async with self.sessions() as session, session.begin():
            announcement = Announcement(content=content, created_by=created_by, status="scheduled")
            announcement.channels = [
                AnnouncementChannel(channel_id=channel_id, scheduled_for=scheduled_for, status="queued")
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
            session.add(reminder)
        return reminder

    async def _dispatch_announcements(self) -> None:
        for record_id, channel_id, content in await self._claim_due_channels():
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if not isinstance(channel, discord.abc.Messageable):
                    raise RuntimeError("El destino no acepta mensajes")
                message = await channel.send(content)
            except (discord.DiscordException, RuntimeError) as error:
                await self._finish_channel(record_id, error=str(error))
            else:
                await self._finish_channel(record_id, message_id=message.id)

    async def _claim_due_channels(self) -> list[tuple[int, int, str]]:
        now = datetime.now(UTC)
        stale_before = now - self.stale_claim_after
        async with self.sessions() as session, session.begin():
            rows = await session.execute(
                select(AnnouncementChannel.id, AnnouncementChannel.channel_id, Announcement.content)
                .join(Announcement)
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
            for record_id, _, _ in records:
                await session.execute(
                    update(AnnouncementChannel)
                    .where(AnnouncementChannel.id == record_id)
                    .values(status="processing", claimed_at=now, attempts=AnnouncementChannel.attempts + 1)
                )
        return [(record_id, channel_id, content) for record_id, channel_id, content in records]

    async def _finish_channel(self, record_id: int, message_id: int | None = None, error: str | None = None) -> None:
        async with self.sessions() as session, session.begin():
            record = await session.get(AnnouncementChannel, record_id, with_for_update=True)
            if record is None:
                return
            record.status = "sent" if message_id else "failed"
            record.discord_message_id = message_id
            record.sent_at = datetime.now(UTC) if message_id else None
            record.error = error[:1_000] if error else None
            channel_statuses = list(
                await session.scalars(
                    select(AnnouncementChannel.status).where(
                        AnnouncementChannel.announcement_id == record.announcement_id
                    )
                )
            )
            announcement = await session.get(Announcement, record.announcement_id, with_for_update=True)
            if announcement is not None:
                announcement.status = self._aggregate_status(channel_statuses)

    async def _dispatch_reminders(self) -> None:
        for reminder_id, content, role_id in await self._claim_due_reminders():
            if role_id is not None:
                recipients = await self._members_for_role(role_id)
                if recipients is None:
                    await self._finish_reminder_without_delivery(reminder_id, "No se encontró el rol destinatario")
                    continue
                await self._add_role_recipients(reminder_id, recipients)
            for recipient_id, user_id in await self._claim_recipients(reminder_id):
                try:
                    user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                    await user.send(content)
                except discord.DiscordException as error:
                    await self._finish_recipient(recipient_id, error=str(error))
                else:
                    await self._finish_recipient(recipient_id)
            await self._finish_reminder_if_ready(reminder_id)

    async def _claim_due_reminders(self) -> list[tuple[uuid.UUID, str, int | None]]:
        now = datetime.now(UTC)
        stale_before = now - self.stale_claim_after
        async with self.sessions() as session, session.begin():
            rows = await session.execute(
                select(Reminder.id, Reminder.content, Reminder.target_role_id)
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
            for reminder_id, _, _ in reminders:
                await session.execute(
                    update(Reminder)
                    .where(Reminder.id == reminder_id)
                    .values(status="processing", claimed_at=now)
                )
        return reminders

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
                members = [member async for member in guild.fetch_members(limit=None) if role in member.roles]
            except discord.DiscordException:
                return None
        return [member.id for member in members if not member.bot]

    async def _add_role_recipients(self, reminder_id: uuid.UUID, user_ids: list[int]) -> None:
        async with self.sessions() as session, session.begin():
            existing = set(
                await session.scalars(
                    select(ReminderRecipient.user_id).where(ReminderRecipient.reminder_id == reminder_id)
                )
            )
            session.add_all(
                ReminderRecipient(user_id=user_id, reminder_id=reminder_id, source="role", status="queued")
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
                    .values(status="processing", claimed_at=now, attempts=ReminderRecipient.attempts + 1)
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
            statuses = list(
                await session.scalars(
                    select(ReminderRecipient.status).where(ReminderRecipient.reminder_id == reminder_id)
                )
            )
            if any(status in {"queued", "processing"} for status in statuses):
                return
            reminder = await session.get(Reminder, reminder_id, with_for_update=True)
            if reminder is None or reminder.status != "processing":
                return
            reminder.status = "failed" if statuses and all(status == "failed" for status in statuses) else "completed"
            await self._schedule_next_reminder(session, reminder)

    async def _schedule_next_reminder(self, session, reminder: Reminder) -> None:
        weekdays = tuple(int(day) for day in reminder.recurrence_weekdays.split(",") if day)
        scheduled_for = next_occurrence(
            reminder.scheduled_for,
            reminder.recurrence,
            reminder.recurrence_interval,
            weekdays,
            reminder.recurrence_until,
        )
        if scheduled_for is None:
            return
        direct_user_ids = list(
            await session.scalars(
                select(ReminderRecipient.user_id).where(
                    ReminderRecipient.reminder_id == reminder.id,
                    ReminderRecipient.source == "direct",
                )
            )
        )
        next_reminder = Reminder(
            announcement_id=reminder.announcement_id,
            content=reminder.content,
            scheduled_for=scheduled_for,
            target_role_id=reminder.target_role_id,
            recurrence=reminder.recurrence,
            recurrence_interval=reminder.recurrence_interval,
            recurrence_weekdays=reminder.recurrence_weekdays,
            recurrence_until=reminder.recurrence_until,
            recurrence_group_id=reminder.recurrence_group_id or reminder.id,
            status="scheduled",
            recipients=[
                ReminderRecipient(user_id=user_id, source="direct", status="queued")
                for user_id in direct_user_ids
            ],
        )
        session.add(next_reminder)

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
        return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild

    @staticmethod
    def _parse_weekdays(value: str | None) -> tuple[int, ...]:
        if not value:
            return ()
        names = {
            "lun": 0, "lunes": 0, "mar": 1, "martes": 1, "mie": 2, "miercoles": 2,
            "jue": 3, "jueves": 3, "vie": 4, "viernes": 4, "sab": 5, "sabado": 5,
            "dom": 6, "domingo": 6,
        }
        values = [part.strip().casefold().replace("é", "e").replace("á", "a") for part in value.split(",")]
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
                return datetime.combine(
                    relative_dates[day_word],
                    datetime.min.time(),
                    tzinfo=AnnouncementCog.lima_timezone,
                ).replace(hour=hour, minute=minute).astimezone(UTC)
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
            return datetime(year, month, day, hour, minute, tzinfo=AnnouncementCog.lima_timezone).astimezone(UTC)
        except ValueError as error:
            raise ValueError(
                "Usa hora Lima: 'hoy 18:30', 'mañana 09:00' o '15/09 14:00'."
            ) from error

    @staticmethod
    def _format_lima(value: datetime) -> str:
        return value.astimezone(AnnouncementCog.lima_timezone).strftime("%d/%m/%Y %H:%M (Lima)")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnnouncementCog(bot))
