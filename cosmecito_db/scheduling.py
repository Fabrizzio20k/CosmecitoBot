"""Reglas deterministas para la programación en hora de Lima."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


LIMA_TIMEZONE = ZoneInfo("America/Lima")
RECURRENCES = frozenset({"once", "daily", "weekly", "monthly"})


def next_occurrence(
    value: datetime, recurrence: str, weekdays: tuple[int, ...] = ()
) -> datetime | None:
    """Devuelve la siguiente ocurrencia conservando la hora local de Lima."""
    if recurrence == "once":
        return None
    if recurrence not in RECURRENCES:
        raise ValueError("Recurrencia no válida")

    local = value.astimezone(LIMA_TIMEZONE)
    if recurrence == "daily":
        next_local = local + timedelta(days=1)
    elif recurrence == "weekly":
        enabled_days = weekdays or (local.weekday(),)
        next_local = next(
            local + timedelta(days=offset)
            for offset in range(1, 8)
            if (local + timedelta(days=offset)).weekday() in enabled_days
        )
    else:
        year = local.year + (local.month == 12)
        month = 1 if local.month == 12 else local.month + 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        next_local = local.replace(year=year, month=month, day=day)
    return next_local.astimezone(UTC)
