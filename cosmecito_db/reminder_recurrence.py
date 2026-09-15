from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    LIMA_TIMEZONE = ZoneInfo("America/Lima")
except ZoneInfoNotFoundError:
    # Lima keeps UTC-5 year round. This also permits native Windows execution
    # when the OS/Python installation does not include the IANA timezone data.
    LIMA_TIMEZONE = timezone(timedelta(hours=-5), name="America/Lima")
RECURRENCE_TYPES = frozenset({"once", "daily", "weekly", "monthly"})


def normalize_recurrence(
    recurrence: str,
    interval: int,
    weekdays: list[int] | tuple[int, ...],
    scheduled_for: datetime,
    until: datetime | None,
) -> tuple[str, int, tuple[int, ...], datetime | None]:
    """Validate and normalize a recurrence rule stored in UTC."""
    if recurrence not in RECURRENCE_TYPES:
        raise ValueError("La recurrencia debe ser una de: once, diaria, semanal o mensual.")
    if interval < 1 or interval > 365:
        raise ValueError("El intervalo debe estar entre 1 y 365.")
    if recurrence in {"once", "weekly"} and interval != 1:
        raise ValueError("El intervalo sólo se puede personalizar en recurrencias diaria o mensual.")
    if scheduled_for.tzinfo is None:
        raise ValueError("La fecha programada debe incluir zona horaria.")
    if until is not None:
        if until.tzinfo is None:
            raise ValueError("La fecha de fin debe incluir zona horaria.")
        if until <= scheduled_for:
            raise ValueError("La fecha de fin debe ser posterior al primer envío.")

    normalized_weekdays = tuple(sorted(set(weekdays)))
    if any(day < 0 or day > 6 for day in normalized_weekdays):
        raise ValueError("Los días de semana deben estar entre 0 (lunes) y 6 (domingo).")
    if recurrence == "weekly" and not normalized_weekdays:
        normalized_weekdays = (scheduled_for.astimezone(LIMA_TIMEZONE).weekday(),)
    if recurrence != "weekly" and normalized_weekdays:
        raise ValueError("Los días de semana sólo se usan en la recurrencia semanal.")
    if recurrence == "once" and until is not None:
        raise ValueError("Un recordatorio de una sola vez no puede tener fecha de fin.")
    return recurrence, interval, normalized_weekdays, until


def next_occurrence(
    scheduled_for: datetime,
    recurrence: str,
    interval: int,
    weekdays: tuple[int, ...],
    until: datetime | None,
) -> datetime | None:
    """Return the following occurrence, preserving its calendar time in Lima."""
    if recurrence == "once":
        return None
    local = scheduled_for.astimezone(LIMA_TIMEZONE)
    if recurrence == "daily":
        candidate = local + timedelta(days=interval)
    elif recurrence == "weekly":
        enabled_days = weekdays or (local.weekday(),)
        candidate = next(
            local + timedelta(days=offset)
            for offset in range(1, 8)
            if (local + timedelta(days=offset)).weekday() in enabled_days
        )
    elif recurrence == "monthly":
        month_index = local.month - 1 + interval
        year, month = local.year + month_index // 12, month_index % 12 + 1
        candidate = local.replace(day=min(local.day, monthrange(year, month)[1]), year=year, month=month)
    else:
        raise ValueError(f"Recurrencia desconocida: {recurrence}")

    candidate_utc = candidate.astimezone(scheduled_for.tzinfo)
    return None if until is not None and candidate_utc > until else candidate_utc
