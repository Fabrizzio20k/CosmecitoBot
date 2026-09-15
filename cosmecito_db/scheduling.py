"""Reglas deterministas para la programación en hora de Lima."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


LIMA_TIMEZONE = ZoneInfo("America/Lima")
RECURRENCES = frozenset({"none", "daily", "weekly", "monthly"})


def next_occurrence(value: datetime, recurrence: str) -> datetime | None:
    """Devuelve la siguiente ocurrencia conservando la hora local de Lima."""
    if recurrence == "none":
        return None
    if recurrence not in RECURRENCES:
        raise ValueError("Recurrencia no válida")

    local = value.astimezone(LIMA_TIMEZONE)
    if recurrence == "daily":
        next_local = local + timedelta(days=1)
    elif recurrence == "weekly":
        next_local = local + timedelta(weeks=1)
    else:
        year = local.year + (local.month == 12)
        month = 1 if local.month == 12 else local.month + 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        next_local = local.replace(year=year, month=month, day=day)
    return next_local.astimezone(UTC)
