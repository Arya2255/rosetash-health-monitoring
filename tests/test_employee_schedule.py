"""Weekly shift-schedule and BLE allowlist tests; no clocks/network/hardware."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from employee_schedule import (
    DAY_KEYS,
    MAX_ACTIVE_MACS,
    active_employee_macs,
    eligible_employee,
    is_scheduled,
    next_scheduled_start,
    normalize_schedule,
)

import employee_schedule as schedules

TEHRAN = ZoneInfo("Asia/Tehran")


class WeeklyScheduleTests(unittest.TestCase):
    def test_unconfigured_employee_is_not_scanned_by_default(self):
        self.assertFalse(eligible_employee({"mac": "aa:bb:cc:dd:ee:ff"}))
        self.assertFalse(eligible_employee({
            "mac": "aa:bb:cc:dd:ee:ff",
            "weekly_schedule": {"mon": [{"start": "08:00", "end": "16:00"}]},
            "scan_paused": True,
        }, datetime(2026, 11, 16, 9, 0, tzinfo=TEHRAN)))

    def test_each_weekday_has_its_own_window(self):
        schedule = {
            "mon": [{"start": "08:00", "end": "16:00"}],
            "wed": [{"start": "10:00", "end": "18:00"}],
        }
        self.assertTrue(is_scheduled(schedule, datetime(2026, 11, 16, 8, 0, tzinfo=TEHRAN)))
        self.assertFalse(is_scheduled(schedule, datetime(2026, 11, 16, 16, 0, tzinfo=TEHRAN)))
        self.assertTrue(is_scheduled(schedule, datetime(2026, 11, 18, 17, 59, tzinfo=TEHRAN)))
        self.assertFalse(is_scheduled(schedule, datetime(2026, 11, 17, 12, 0, tzinfo=TEHRAN)))

    def test_overnight_window_continues_into_the_next_weekday(self):
        schedule = {"sat": [{"start": "22:00", "end": "06:00"}]}
        self.assertTrue(is_scheduled(schedule, datetime(2026, 11, 14, 23, 30, tzinfo=TEHRAN)))
        self.assertTrue(is_scheduled(schedule, datetime(2026, 11, 15, 2, 0, tzinfo=TEHRAN)))
        self.assertFalse(is_scheduled(schedule, datetime(2026, 11, 15, 6, 0, tzinfo=TEHRAN)))

    def test_next_start_respects_weekday_and_local_timezone(self):
        schedule = {"sun": [{"start": "07:30", "end": "15:30"}]}
        now = datetime(2026, 11, 14, 20, 0, tzinfo=TEHRAN)
        self.assertEqual(next_scheduled_start(schedule, now),
                         datetime(2026, 11, 15, 7, 30, tzinfo=TEHRAN))

    def test_schedule_rejects_invalid_or_ambiguous_intervals(self):
        for invalid in (
            {"funday": [{"start": "08:00", "end": "16:00"}]},
            {"mon": [{"start": "08:00", "end": "08:00"}]},
            {"mon": [{"start": "25:00", "end": "26:00"}]},
            {"mon": "08:00-16:00"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_schedule(invalid)

    def test_scan_allowlist_is_deduplicated_and_bounded(self):
        schedule = {day: [{"start": "00:00", "end": "23:59"}] for day in DAY_KEYS}
        now = datetime(2026, 11, 16, 12, 0, tzinfo=TEHRAN)
        employees = [
            {"mac": "AA-BB-CC-DD-EE-01", "weekly_schedule": schedule},
            {"mac": "aa:bb:cc:dd:ee:01", "weekly_schedule": schedule},
            {"mac": "invalid", "weekly_schedule": schedule},
        ]
        self.assertEqual(active_employee_macs(employees, now), ["aa:bb:cc:dd:ee:01"])
        self.assertEqual(MAX_ACTIVE_MACS, 256)
        too_many = [
            {"mac": f"aa:bb:cc:dd:{i // 256:02x}:{i % 256:02x}",
             "weekly_schedule": schedule}
            for i in range(257)
        ]
        with self.assertRaises(ValueError):
            active_employee_macs(too_many, now)

    def test_next_transition_handles_overnight_and_overlapping_ranges(self):
        schedule = {"sat": [{"start": "22:00", "end": "06:00"}],
                    "sun": [{"start": "05:00", "end": "08:00"}]}
        now = datetime(2026, 11, 15, 2, 0, tzinfo=TEHRAN)
        self.assertEqual(schedules.next_schedule_transition(schedule, now),
                         datetime(2026, 11, 15, 8, 0, tzinfo=TEHRAN))
        self.assertIsNone(schedules.next_schedule_transition({}, now))

    def test_rejects_seconds_timezone_and_bad_time_formats(self):
        for start in ("08:00:00", "08:00+03:30", "0800", "8:0"):
            with self.subTest(start=start), self.assertRaises(ValueError):
                normalize_schedule({"mon": [{"start": start, "end": "16:00"}]})
        self.assertEqual(normalize_schedule({"mon": [{"start": "۰۸:۰۰", "end": "۱۶:۰۰"}]}),
                         {"mon": [{"start": "08:00", "end": "16:00"}]})


if __name__ == "__main__":
    unittest.main()
