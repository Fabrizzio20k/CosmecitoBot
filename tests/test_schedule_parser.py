from datetime import UTC, datetime
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from zoneinfo import ZoneInfo


package = types.ModuleType("cosmecito_db")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "cosmecito_db")]
scheduling = types.ModuleType("cosmecito_db.scheduling")
scheduling.LIMA_TIMEZONE = ZoneInfo("America/Lima")
scheduling.RECURRENCES = frozenset({"once", "daily", "weekly", "monthly"})
sys.modules.setdefault("cosmecito_db", package)
sys.modules.setdefault("cosmecito_db.scheduling", scheduling)

module_path = Path(__file__).resolve().parents[1] / "cosmecito_db" / "schedule_parser.py"
spec = importlib.util.spec_from_file_location("cosmecito_db.schedule_parser", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError("No se pudo cargar el parser de programación")
schedule_parser = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = schedule_parser
spec.loader.exec_module(schedule_parser)
parse_schedule = schedule_parser.parse_schedule


class ScheduleParserTests(unittest.TestCase):
    def test_accepts_plural_saturday_with_an_end_date(self) -> None:
        schedule = parse_schedule(
            "todos los sábados desde el 19 de setiembre a las 16:55 hasta el 30 de noviembre",
            now=datetime(2026, 9, 14, 12, tzinfo=UTC),
        )

        self.assertEqual(schedule.recurrence, "weekly")
        self.assertEqual(schedule.recurrence_weekdays, (5,))
        self.assertEqual(schedule.scheduled_for, datetime(2026, 9, 19, 21, 55, tzinfo=UTC))
        self.assertEqual(schedule.recurrence_until, datetime(2026, 11, 30, 21, 55, tzinfo=UTC))
