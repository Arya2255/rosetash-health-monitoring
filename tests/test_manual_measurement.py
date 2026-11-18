"""Manual measurement HTTP routing tests using disposable SQLite and gateway fixtures."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_location_policy import IsolatedBridge, bridge, MAC, NOW, ACTOR


class ManualMeasurementTests(IsolatedBridge):
    def setUp(self):
        super().setUp()
        self.employee()
        self.gateway("gw-a", .2, .3)
        self.presence("gw-a", -43)
        self.status(NOW)

    def status(self, at, **fields):
        bridge.ingest("roztash/gw-a/status", json.dumps({
            "online": True, "scan_policy_ready": True,
            "manual_measurement": True, **fields}), at)

    def test_manual_request_routes_once_and_has_correlated_pending_state(self):
        with patch.object(bridge, "publish", return_value=(True, "sent")) as publish:
            ok, error, info = bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW)
            self.assertTrue(ok, error)
            payload = json.loads(publish.call_args.args[1])
            self.assertEqual((publish.call_args.args[0], payload["action"], payload["mac"]),
                             ("roztash/gw-a/cmd", "measure", MAC))
            self.assertTrue(payload["request_id"].startswith("measure-"))
            self.assertFalse(publish.call_args.kwargs["retained"])
            second = bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW+1)
            self.assertFalse(second[0])
            self.assertEqual(second[1], "measurement already pending")
            self.assertEqual(publish.call_count, 1)
        row = bridge.snapshot(NOW+1)["manual_measurements"][0]
        self.assertEqual((row["request_id"], row["status"]), (info["request_id"], "pending"))

    def test_manual_request_requires_role_schedule_gateway_capability_and_fresh_band(self):
        for role, extra, expected in (("", {}, "forbidden"),
                                      ("viewer", {"vitals": "yes"}, "invalid measurement")):
            with patch.object(bridge, "get_role", return_value=role), patch.object(bridge, "publish") as pub:
                ok, error, _ = bridge.request_measurement({"mac": MAC, "actor": ACTOR, **extra}, NOW)
                self.assertFalse(ok)
                self.assertEqual(error, expected)
                pub.assert_not_called()
        bridge.db().execute("UPDATE employees SET scan_paused=1 WHERE mac=?", (MAC,))
        bridge.db().commit()
        self.assertEqual(bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW)[1],
                         "employee monitoring is paused or outside scheduled hours")
        bridge.db().execute("UPDATE employees SET scan_paused=0 WHERE mac=?", (MAC,))
        bridge.db().commit()
        with patch.object(bridge, "publish") as pub:
            self.assertEqual(bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW+61)[1],
                             "band unavailable")
            pub.assert_not_called()
        self.status(NOW, manual_measurement=False)
        self.assertEqual(bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW)[1],
                         "gateway update required")

    def test_manual_request_skips_strongest_gateway_without_capability(self):
        self.gateway("gw-strong", .2, .3)
        self.gateway("gw-ready", .4, .5)
        self.presence("gw-strong", -35)
        self.presence("gw-ready", -60)
        bridge.ingest("roztash/gw-a/status", json.dumps({
            "online": True, "scan_policy_ready": True,
            "manual_measurement": False}), NOW)
        bridge.ingest("roztash/gw-strong/status", json.dumps({
            "online": True, "scan_policy_ready": True,
            "manual_measurement": False}), NOW)
        bridge.ingest("roztash/gw-ready/status", json.dumps({
            "online": True, "scan_policy_ready": True,
            "manual_measurement": True}), NOW)
        policy = bridge.employee_scan_policy(NOW)
        self.assertEqual(policy["health_by_gateway"]["gw-ready"], [MAC])
        self.assertEqual(policy["health_by_gateway"]["gw-strong"], [])
        with patch.object(bridge, "publish", return_value=(True, "sent")) as publish:
            ok, error, info = bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW)
        self.assertTrue(ok, error)
        self.assertEqual(info["gw"], "gw-ready")
        self.assertEqual(publish.call_args.args[0], "roztash/gw-ready/cmd")

    def test_only_matching_fresh_heart_samples_complete_request(self):
        with patch.object(bridge, "publish", return_value=(True, "sent")):
            ok, _, info = bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW)
        self.assertTrue(ok)
        doc = {"mac": MAC, "request_id": info["request_id"], "reason": "manual_measure", "type": "measure_done"}
        bridge.ingest("roztash/other/event", json.dumps(doc), NOW+1)
        bridge.ingest("roztash/gw-a/event", json.dumps({**doc, "replayed": True}), NOW+1)
        bridge.ingest("roztash/gw-a/event", json.dumps(doc), NOW+2)
        health = {"mac": MAC, "request_id": info["request_id"], "state": "done",
                  "n": 2, "bpm": [78, 82], "avg": 80}
        bridge.ingest("roztash/other/health", json.dumps(health), NOW+3)
        bridge.ingest("roztash/gw-a/health", json.dumps({**health, "bpm": []}), NOW+4)
        bridge.ingest("roztash/gw-a/health", json.dumps({**health, "replayed": True}), NOW+5)
        pending = bridge.snapshot(NOW+5)
        self.assertEqual(pending["manual_measurements"][0]["status"], "pending")
        self.assertIsNone(pending["employees"][0]["health"])
        bridge.ingest("roztash/gw-a/health", json.dumps(health), NOW+6)
        self.close_db()
        snapshot = bridge.snapshot(NOW+7)
        result = snapshot["employees"][0]["manual_measurement"]
        self.assertEqual((result["status"], result["bpm"]), ("done", 80))
        self.assertEqual(snapshot["employees"][0]["health"]["avg"], 80)
        self.assertNotIn("actor", result)

    def test_publish_does_not_use_observation_from_before_resume(self):
        bridge.db().execute("UPDATE employees SET scan_resume_at=? WHERE mac=?", (NOW+1, MAC))
        bridge.db().commit()
        with patch.object(bridge, "publish") as pub:
            result = bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW+2)
            self.assertEqual(result[:2], (False, "band unavailable"))
            pub.assert_not_called()

    def test_expired_pending_measurement_is_not_resurrected(self):
        with patch.object(bridge, "publish", return_value=(True, "sent")):
            ok, _, info = bridge.request_measurement({"mac": MAC, "actor": ACTOR}, NOW)
        self.assertTrue(ok)
        expired = bridge.snapshot(NOW+120)["employees"][0]["manual_measurement"]
        self.assertEqual(expired["status"], "timeout")
        bridge.ingest("roztash/gw-a/health", json.dumps({"mac": MAC,
            "request_id": info["request_id"], "state": "done", "n": 1, "bpm": [79], "avg": 79}), NOW+121)
        snapshot = bridge.snapshot(NOW+122)
        self.assertIsNone(snapshot["employees"][0]["health"])
        self.assertEqual(snapshot["employees"][0]["manual_measurement"]["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
