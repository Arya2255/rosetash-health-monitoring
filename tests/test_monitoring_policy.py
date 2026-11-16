"""Bridge-side employee monitoring policy tests; uses an isolated SQLite file."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "src"))

import admin_roles
import bridge


class MonitoringPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scan-policy-")
        self.addCleanup(self.temp.cleanup)
        bridge.DB_PATH = str(Path(self.temp.name) / "live.db")
        bridge.PHOTOS_DIR = str(Path(self.temp.name) / "photos")
        bridge._db = None
        admin_roles.ROLES_FILE = str(Path(self.temp.name) / "roles.json")
        admin_roles._write_roles({"roles": {"viewer@example.test": "viewer"}})
        self.owner = admin_roles.DEFAULT_OWNER
        self.viewer = "viewer@example.test"
        self.mac = "aa:bb:cc:dd:ee:01"
        ok, error = bridge.upsert_employee({"mac": self.mac, "name": "Test Employee"})
        self.assertTrue(ok, error)

    def tearDown(self):
        if bridge._db is not None:
            bridge._db.close()
            bridge._db = None

    def _schedule(self, day="mon", start="08:00", end="16:00"):
        return {day: [{"start": start, "end": end}]}

    def test_owner_can_set_weekly_schedule(self):
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.owner,
             "weekly_schedule": self._schedule()})
        self.assertTrue(ok, error)
        row = next(r for r in bridge.employees_list() if r["mac"] == self.mac)
        self.assertEqual(json.loads(row["weekly_schedule"]), self._schedule())
        self.assertFalse(row["scan_paused"])

    def test_viewer_can_pause_resume_and_edit_schedule(self):
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.owner,
             "weekly_schedule": self._schedule()})
        self.assertTrue(ok, error)
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.viewer, "scan_paused": True})
        self.assertTrue(ok, error)
        row = next(r for r in bridge.employees_list() if r["mac"] == self.mac)
        self.assertTrue(row["scan_paused"])
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.viewer,
             "weekly_schedule": self._schedule("tue")})
        self.assertTrue(ok, error)
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.viewer, "scan_paused": False})
        self.assertTrue(ok, error)
        row = next(r for r in bridge.employees_list() if r["mac"] == self.mac)
        self.assertFalse(row["scan_paused"])
        self.assertEqual(row["name"], "Test Employee")
        self.assertEqual(json.loads(row["weekly_schedule"]), self._schedule("tue"))

    def test_unknown_admin_and_invalid_schedule_are_rejected(self):
        for request in (
            {"mac": self.mac, "actor": "not-admin@example.test", "scan_paused": True},
            {"mac": self.mac, "actor": self.owner,
             "weekly_schedule": {"monday": [{"start": "08:00", "end": "16:00"}]}},
        ):
            with self.subTest(request=request):
                ok, error = bridge.set_employee_monitoring(request)
                self.assertFalse(ok)
                self.assertIn(error, ("forbidden", "invalid schedule"))

    def test_mac_is_eligible_only_inside_schedule_and_not_while_paused(self):
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.owner,
             "weekly_schedule": self._schedule()})
        self.assertTrue(ok, error)
        tehran = ZoneInfo("Asia/Tehran")
        inside = datetime(2026, 11, 16, 9, 0, tzinfo=tehran).timestamp()
        outside = datetime(2026, 11, 16, 16, 0, tzinfo=tehran).timestamp()
        self.assertEqual(bridge.employee_scan_policy(inside)["active_macs"], [self.mac])
        self.assertEqual(bridge.employee_scan_policy(outside)["active_macs"], [])
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.viewer, "scan_paused": True})
        self.assertTrue(ok, error)
        self.assertEqual(bridge.employee_scan_policy(inside)["active_macs"], [])

    def test_absent_schedule_fails_closed(self):
        self.assertEqual(bridge.employee_scan_policy()["active_macs"], [])

    def test_out_of_shift_presence_is_not_saved(self):
        ok, error = bridge.set_employee_monitoring(
            {"mac": self.mac, "actor": self.owner,
             "weekly_schedule": self._schedule()})
        self.assertTrue(ok, error)
        tehran = ZoneInfo("Asia/Tehran")
        outside = datetime(2026, 11, 16, 18, 0, tzinfo=tehran).timestamp()
        bridge.ingest("roztash/gw-test-1/presence",
                      json.dumps({"bands": [{"mac": self.mac, "rssi": -55}]}),
                      recv_ts=outside)
        self.assertIsNone(bridge.db().execute(
            "SELECT mac FROM bands WHERE mac=?", (self.mac,)).fetchone())


if __name__ == "__main__":
    unittest.main()
