"""Isolated bridge location and gateway-routing regression tests (stdlib only)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "src"))
import bridge

MAC = "aa:bb:cc:dd:ee:01"
ACTOR = "operator@example.test"
SCHEDULE = {"mon": [{"start": "08:00", "end": "16:00"}]}
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=bridge.TEHRAN).timestamp()


class IsolatedBridge(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="bridge-policy-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(temp.cleanup)
        self.addCleanup(self.close_db)
        bridge._db = None
        for field, value in (("DB_PATH", str(Path(temp.name) / "state.db")),
                             ("PHOTOS_DIR", str(Path(temp.name) / "photos"))):
            ctx = patch.object(bridge, field, value)
            ctx.start()
            self.addCleanup(ctx.stop)
        roles = patch.object(bridge, "get_role", side_effect=lambda a: "viewer" if a == ACTOR else "")
        roles.start()
        self.addCleanup(roles.stop)
        self.clock = patch.object(bridge.time, "time", return_value=NOW - 3600)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        if hasattr(bridge, "_scan_policy_cleared"):
            bridge._scan_policy_cleared.clear()
        if hasattr(bridge, "_scan_policy_last"):
            bridge._scan_policy_last.clear()
        if hasattr(bridge, "_scan_policy_wake"):
            bridge._scan_policy_wake.clear()

    @staticmethod
    def close_db():
        if bridge._db is not None:
            bridge._db.close()
            bridge._db = None

    def employee(self, mac=MAC, schedule=SCHEDULE):
        self.assertEqual(bridge.upsert_employee({"mac": mac, "name": "Synthetic Employee"}), (True, ""))
        # Direct fixture setup; no live roles, authentication keys or DB access.
        bridge.db().execute("UPDATE employees SET weekly_schedule=? WHERE mac=?", (json.dumps(schedule), mac))
        bridge.db().commit()

    def gateway(self, gw, x, y, zone=None, kind="installed"):
        self.assertEqual(bridge.upsert_gateway({"gw": gw, "kind": kind, "x": x, "y": y,
                                               "zone": zone or gw}), (True, ""))

    def presence(self, gw, rssi, at=NOW, mac=MAC):
        bridge.ingest(f"roztash/{gw}/presence", json.dumps({"bands": [{"mac": mac, "rssi": rssi}]}), at)


class LocationPolicyTests(IsolatedBridge):
    def test_strongest_fresh_gateway_uses_registered_map_location(self):
        self.employee()
        self.gateway("gw-a", 0.2, 0.3, "registered-a")
        self.gateway("gw-b", 0.7, 0.8, "registered-b")
        bridge.ingest("roztash/gw-a/status", json.dumps({"zone": "spoofed-zone"}), NOW)
        self.presence("gw-a", -42, NOW - 10)
        self.presence("gw-b", -81, NOW)
        snap = bridge.snapshot(NOW)
        emp = snap["employees"][0]
        self.assertEqual(emp["gw"], "gw-a")
        self.assertEqual(emp["zone"], "registered-a")
        self.assertEqual((emp["location"]["gw"], emp["location"]["x"], emp["location"]["y"]),
                         ("gw-a", 0.2, 0.3))
        self.assertEqual(snap["bands"][0]["gw"], "gw-a")
        self.assertEqual(snap["bands_known"][0]["gw"], "gw-a")

    def test_expiration_ties_and_older_or_invalid_observations(self):
        self.employee()
        self.gateway("gw-a", 0.2, 0.3)
        self.gateway("gw-b", 0.7, 0.8)
        self.presence("gw-b", -55, NOW - 15)
        self.presence("gw-a", -55, NOW - 10)
        self.assertEqual(bridge.snapshot(NOW)["employees"][0]["gw"], "gw-a")
        self.presence("gw-a", -80, NOW - 20)  # Older sample must not replace -55.
        for invalid in (None, True, "-20", 0, 10, -128, float("nan"), float("inf")):
            self.presence("gw-b", invalid, NOW)
        self.assertEqual(bridge.snapshot(NOW)["employees"][0]["gw"], "gw-a")
        self.presence("gw-b", -75, NOW + 20)
        self.assertEqual(bridge.snapshot(NOW + 51)["employees"][0]["gw"], "gw-b")
        stale = bridge.snapshot(NOW + 81)["employees"][0]
        self.assertFalse(stale["present"])
        self.assertIsNone(stale["location"])
        self.assertIsNone(stale["gw"])

    def test_unregistered_or_proposed_gateway_cannot_supply_map_location(self):
        self.employee()
        self.gateway("gw-real", 0.2, 0.3)
        self.gateway("gw-future", 0.7, 0.8, kind="proposed")
        self.presence("gw-real", -80)
        self.presence("gw-future", -20)
        self.presence("gw-unknown", -15)
        emp = bridge.snapshot(NOW)["employees"][0]
        self.assertEqual(emp["location"]["gw"], "gw-real")

    def test_cached_advertisement_age_does_not_extend_presence(self):
        self.employee()
        self.gateway("gw-a",0.2,0.3)
        self.presence("gw-a",-45,NOW)
        bridge.ingest("roztash/gw-a/presence", json.dumps({"bands":[
            {"mac":MAC,"rssi":-45,"age_ms":50000}]}),NOW+50)
        observed=bridge.db().execute("SELECT seen_at FROM band_observations WHERE mac=?",(MAC,)).fetchone()[0]
        self.assertEqual(observed,NOW)
        self.assertFalse(bridge.snapshot(NOW+61)["employees"][0]["present"])
        for age in (-1,True,"1000",float("nan")):
            bridge.ingest("roztash/gw-a/presence", json.dumps({"bands":[
                {"mac":MAC,"rssi":-20,"age_ms":age}]}),NOW+70)
        self.assertEqual(bridge.db().execute("SELECT seen_at FROM band_observations WHERE mac=?",(MAC,)).fetchone()[0],NOW)

    def test_cached_advertisement_cannot_restore_location_after_resume(self):
        self.employee()
        self.gateway("gw-a",0.2,0.3)
        for timestamp,paused in ((NOW,True),(NOW+5,False)):
            with patch.object(bridge.time,"time",return_value=timestamp):
                self.assertEqual(bridge.set_employee_monitoring({"mac":MAC,"actor":ACTOR,"scan_paused":paused}),(True,""))
        bridge.ingest("roztash/gw-a/presence",json.dumps({"bands":[
            {"mac":MAC,"rssi":-40,"age_ms":8000}]}),NOW+10)
        self.assertFalse(bridge.snapshot(NOW+10)["employees"][0]["present"])


if __name__ == "__main__":
    unittest.main()
