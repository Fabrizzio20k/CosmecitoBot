from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import unittest


module_path = Path(__file__).resolve().parents[1] / "cosmecito_db" / "reminder_recurrence.py"
spec = importlib.util.spec_from_file_location("reminder_recurrence", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("No se pudo cargar la lógica de recurrencias")
recurrence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recurrence)
next_occurrence = recurrence.next_occurrence
normalize_recurrence = recurrence.normalize_recurrence


class ReminderRecurrenceTests(unittest.TestCase):
    def test_daily_preserves_the_lima_calendar_time(self) -> None:
        scheduled_for = datetime(2026, 9, 7, 14, 30, tzinfo=UTC)
        result = next_occurrence(scheduled_for, "daily", 2, (), None)
        self.assertEqual(result, datetime(2026, 9, 9, 14, 30, tzinfo=UTC))

    def test_weekly_uses_the_selected_weekdays(self) -> None:
        scheduled_for = datetime(2026, 9, 7, 14, 30, tzinfo=UTC)  # Monday, 09:30 Lima
        result = next_occurrence(scheduled_for, "weekly", 1, (0, 2, 4), None)
        self.assertEqual(result, datetime(2026, 9, 9, 14, 30, tzinfo=UTC))

    def test_monthly_clamps_to_the_last_calendar_day(self) -> None:
        scheduled_for = datetime(2026, 1, 31, 14, 30, tzinfo=UTC)
        result = next_occurrence(scheduled_for, "monthly", 1, (), None)
        self.assertEqual(result, datetime(2026, 2, 28, 14, 30, tzinfo=UTC))

    def test_end_date_stops_the_series(self) -> None:
        scheduled_for = datetime(2026, 9, 7, 14, 30, tzinfo=UTC)
        result = next_occurrence(scheduled_for, "daily", 1, (), datetime(2026, 9, 7, 20, 0, tzinfo=UTC))
        self.assertIsNone(result)

    def test_weekly_defaults_to_the_first_send_weekday(self) -> None:
        scheduled_for = datetime(2026, 9, 7, 14, 30, tzinfo=UTC)
        recurrence, interval, weekdays, until = normalize_recurrence("weekly", 1, [], scheduled_for, None)
        self.assertEqual((recurrence, interval, weekdays, until), ("weekly", 1, (0,), None))

    def test_rejects_weekdays_for_non_weekly_recurrence(self) -> None:
        with self.assertRaisesRegex(ValueError, "sólo se usan"):
            normalize_recurrence("daily", 1, [0], datetime(2026, 9, 7, 14, 30, tzinfo=UTC), None)
