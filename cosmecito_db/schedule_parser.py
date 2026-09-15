"""Programación determinista de mensajes en español, siempre en hora Lima."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from cosmecito_db.scheduling import LIMA_TIMEZONE, RECURRENCES


MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "sabados": 5, "domingo": 6, "domingos": 6,
}
DATE_WORDS = "|".join(MONTHS)
DATE_PATTERN = re.compile(
    rf"(?P<day>\d{{1,2}})\s+de\s+(?P<month>{DATE_WORDS})(?:\s+(?:de\s+)?(?P<year>\d{{4}}))?"
)
NUMERIC_DATE_PATTERN = re.compile(r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})(?:[/-](?P<year>\d{4}))?")
TIME_PATTERN = re.compile(
    r"(?:a\s+las\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<meridian>a\.?m\.?|p\.?m\.?)?"
)


@dataclass(frozen=True)
class Schedule:
    scheduled_for: datetime
    recurrence: str
    recurrence_until: datetime | None = None
    recurrence_weekdays: tuple[int, ...] = ()


def schedule_help() -> str:
    return (
        "Usa una de estas fórmulas (hora Lima): `18/09/2026 a las 18:00`, "
        "`mañana a las 18:00`, `todos los viernes desde el 18 de setiembre "
        "a las 6pm`, o `todos los viernes desde el 18 de setiembre a las 6pm "
        "hasta el 30 de noviembre`. Puedes combinar días: `todos los lunes, "
        "miércoles y viernes desde el 18/09/2026 a las 18:00`."
    )


def parse_schedule(instruction: str, *, now: datetime | None = None) -> Schedule:
    """Parse a documented, unambiguous Spanish scheduling expression."""
    text = _normalize(instruction)
    if not text:
        raise ValueError(schedule_help())
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        raise ValueError("La hora actual debe incluir zona horaria.")
    now_local = now_utc.astimezone(LIMA_TIMEZONE)
    recurrence, weekdays = _recurrence(text)
    start_text, separator, until_text = text.partition(" hasta ")
    start_date, explicit_start_date = _parse_start_date(start_text, now_local, weekdays)
    start_time = _parse_time(start_text)
    scheduled_for = datetime.combine(start_date, start_time, tzinfo=LIMA_TIMEZONE).astimezone(UTC)

    if weekdays and explicit_start_date and start_date.weekday() not in weekdays:
        raise ValueError("El día de la fecha no coincide con los días semanales indicados. " + schedule_help())
    if scheduled_for <= now_utc:
        if weekdays and not explicit_start_date:
            scheduled_for = _next_weekday(now_local, weekdays, start_time).astimezone(UTC)
        else:
            raise ValueError("La fecha y hora deben ser futuras. " + schedule_help())

    recurrence_until = None
    if separator:
        if recurrence == "once":
            raise ValueError("`hasta` sólo se usa en una programación repetitiva. " + schedule_help())
        until_date = _parse_date(until_text, now_local.date(), fallback_year=scheduled_for.astimezone(LIMA_TIMEZONE).year)
        recurrence_until = datetime.combine(until_date, start_time, tzinfo=LIMA_TIMEZONE).astimezone(UTC)
        if recurrence_until <= scheduled_for:
            raise ValueError("La fecha límite debe ser posterior al primer envío. " + schedule_help())

    return Schedule(scheduled_for, recurrence, recurrence_until, weekdays if recurrence == "weekly" else ())


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.casefold())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", normalized).strip(" .,;")


def _recurrence(text: str) -> tuple[str, tuple[int, ...]]:
    weekdays = tuple(value for name, value in WEEKDAYS.items() if re.search(rf"\b{name}\b", text))
    repeated_weekday = bool(weekdays) and bool(re.search(r"\b(todos?\s+los?|cada)\s+", text))
    if repeated_weekday or re.search(r"\b(cada\s+semana|semanalmente)\b", text):
        return "weekly", weekdays
    if re.search(r"\b(todos?\s+los?\s+dias?|cada\s+dia|diariamente)\b", text):
        return "daily", ()
    if re.search(r"\b(cada\s+mes|mensualmente)\b", text):
        return "monthly", ()
    return "once", ()


def _parse_start_date(text: str, now: datetime, weekdays: tuple[int, ...]) -> tuple[date, bool]:
    if re.search(r"\bmanana\b", text):
        return now.date() + timedelta(days=1), False
    if re.search(r"\bhoy\b", text):
        return now.date(), False
    try:
        return _parse_date(text, now.date(), fallback_year=now.year), True
    except ValueError:
        if weekdays:
            return _next_weekday(now, weekdays, _parse_time(text)).date(), False
        raise ValueError("No pude encontrar una fecha válida. " + schedule_help()) from None


def _parse_date(text: str, reference: date, *, fallback_year: int) -> date:
    match = DATE_PATTERN.search(text)
    if match:
        month = MONTHS[match["month"]]
    else:
        match = NUMERIC_DATE_PATTERN.search(text)
        if not match:
            raise ValueError("No pude encontrar una fecha válida. " + schedule_help())
        month = int(match["month"])
    day = int(match["day"])
    year = int(match["year"]) if match["year"] else fallback_year
    try:
        candidate = date(year, month, day)
    except ValueError as error:
        raise ValueError("La fecha indicada no existe. " + schedule_help()) from error
    if match["year"] is None and candidate < reference:
        candidate = date(year + 1, month, day)
    return candidate


def _parse_time(text: str) -> time:
    match = re.search(r"\ba\s+las\s+" + TIME_PATTERN.pattern, text)
    if match is None:
        raise ValueError("Indica la hora con `a las`, por ejemplo `a las 18:00`. " + schedule_help())
    hour = int(match["hour"])
    minute = int(match["minute"] or 0)
    meridian = (match["meridian"] or "").replace(".", "")
    if minute > 59:
        raise ValueError("Los minutos deben estar entre 00 y 59.")
    if meridian:
        if not 1 <= hour <= 12:
            raise ValueError("Con am/pm la hora debe estar entre 1 y 12.")
        hour = hour % 12 + (12 if meridian == "pm" else 0)
    elif hour > 23:
        raise ValueError("La hora debe estar entre 00 y 23.")
    return time(hour, minute)


def _next_weekday(now: datetime, weekdays: tuple[int, ...], at: time) -> datetime:
    candidate = datetime.combine(now.date(), at, tzinfo=LIMA_TIMEZONE)
    return next(
        candidate + timedelta(days=offset)
        for offset in range(8)
        if candidate + timedelta(days=offset) > now
        and (candidate + timedelta(days=offset)).weekday() in weekdays
    )


assert RECURRENCES == frozenset({"once", "daily", "weekly", "monthly"})
