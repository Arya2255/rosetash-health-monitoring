"""Monitoring runtime/API regressions: disposable SQLite and loopback only."""
import json
import http.client
import os
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_location_policy import ACTOR, MAC, NOW, SCHEDULE, IsolatedBridge, bridge
from bridge_auth import sign_request


def local_ts(day=16, hour=9, minute=0, second=0):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=bridge.TEHRAN).timestamp()


class MonitoringRuntimeTests(IsolatedBridge):
    def health(self, at, mac=MAC, state="done", fail="none"):
        bridge.ingest("roztash/gw-a/health", json.dumps({"mac": mac, "state": state,
                      "fail": fail, "avg": 78, "n": 2, "bpm": [77, 79], "wearing": True}), at)

    def test_paused_state_preserves_schedule_and_hides_all_live_data(self):
        self.employee()
        self.gateway("gw-a", 0.2, 0.3)
        self.presence("gw-a", -40, NOW)
        self.health(NOW)
        with patch.object(bridge.time, "time", return_value=NOW + 1):
            self.assertEqual(bridge.set_employee_monitoring({"mac": MAC, "actor": ACTOR,
                                                             "scan_paused": True}), (True, ""))
        snap = bridge.snapshot(NOW + 2)
        emp = snap["employees"][0]
        self.assertTrue(emp["scheduled_now"])
        self.assertFalse(emp["scan_allowed"])
        self.assertEqual(emp["monitoring_reason"], "paused")
        self.assertFalse(emp["present"])
        self.assertIsNone(emp["health"])
        self.assertIsNone(emp["location"])
        self.assertEqual(snap["bands"], [])
        self.assertEqual(snap["health"], [])
        self.assertEqual(bridge.db().execute("SELECT COUNT(*) FROM health").fetchone()[0], 1)
        self.health(NOW + 3)
        bridge.ingest("roztash/gw-a/event", json.dumps({"mac": MAC,
                      "type": "measure_unavailable"}), NOW + 3)
        self.assertEqual(bridge.db().execute("SELECT COUNT(*) FROM health").fetchone()[0], 1)
        self.assertEqual(bridge.snapshot(NOW + 3)["employees"][0]["issues"], [])

    def test_resume_requires_new_presence_and_health(self):
        self.employee()
        self.gateway("gw-a", 0.2, 0.3)
        self.presence("gw-a", -40)
        self.health(NOW)
        for at, paused in ((NOW + 1, True), (NOW + 2, False)):
            with patch.object(bridge.time, "time", return_value=at):
                self.assertEqual(bridge.set_employee_monitoring({"mac": MAC, "actor": ACTOR,
                                                                 "scan_paused": paused}), (True, ""))
        emp = bridge.snapshot(NOW + 3)["employees"][0]
        self.assertFalse(emp["present"])
        self.assertIsNone(emp["health"])
        self.presence("gw-a", -45, NOW + 4)
        self.health(NOW + 4)
        emp = bridge.snapshot(NOW + 5)["employees"][0]
        self.assertTrue(emp["present"])
        self.assertIsNotNone(emp["health"])

    def test_shift_gap_cannot_reuse_prior_data_within_ttl(self):
        self.employee(schedule={"mon": [{"start": "08:00", "end": "09:00"},
                                         {"start": "09:01", "end": "10:00"}]})
        self.gateway("gw-a", 0.2, 0.3)
        self.presence("gw-a", -40, NOW - 1)
        self.health(NOW - 1)
        bridge.ingest("roztash/gw-a/vitals", json.dumps({"mac": MAC, "battery": 95,
                      "spo2_raw": ["0AB2:61"], "spo2_ack": True}), NOW - 1)
        snap = bridge.snapshot(NOW + 60)
        self.assertTrue(snap["employees"][0]["scheduled_now"])
        self.assertIsNone(snap["employees"][0]["health"])
        self.assertEqual(snap["health"], [])
        self.assertEqual(snap["vitals"], [])
        bridge.ingest("roztash/gw-a/vitals", json.dumps({"mac": MAC, "battery": 94}), NOW + 61)
        snap = bridge.snapshot(NOW + 62)
        self.assertIsNone(snap["employees"][0]["vitals"]["spo2"])
        self.assertEqual(snap["vitals"][0]["spo2_raw"], [])

    def test_overnight_boundary_and_measurement_absence_warning(self):
        self.employee(schedule={"mon": [{"start": "22:00", "end": "06:00"}]})
        self.gateway("gw-a", 0.2, 0.3)
        during, end = local_ts(17, 5, 59), local_ts(17, 6)
        bridge.ingest("roztash/gw-a/event", json.dumps({"mac": MAC,
                      "type": "measure_unavailable"}), during)
        emp = bridge.snapshot(during)["employees"][0]
        self.assertTrue(emp["scan_allowed"])
        self.assertEqual(emp["status"], "warn")
        self.assertIn("measure_unavailable", emp["issues"])
        off = bridge.snapshot(end)["employees"][0]
        self.assertFalse(off["scan_allowed"])
        self.assertEqual(off["monitoring_reason"], "outside_shift")
        self.assertEqual(off["issues"], [])
        self.assertEqual(off["status"], "off")

    def test_offline_replay_is_archived_without_becoming_fresh_telemetry(self):
        self.employee()
        for leaf, payload in (
            ("health", {"mac": MAC, "bpm": [80], "avg": 80, "n": 1}),
            ("vitals", {"mac": MAC, "battery": 90}),
            ("event", {"mac": MAC, "type": "measure_unavailable"}),
        ):
            bridge.ingest("roztash/gw-a/" + leaf,
                          json.dumps({**payload, "replayed": True}), NOW)
        snap = bridge.snapshot(NOW)
        self.assertEqual(snap["health"], [])
        self.assertEqual(snap["vitals"], [])
        self.assertEqual(snap["employees"][0]["issues"], [])
        self.assertEqual(bridge.db().execute(
            "SELECT COUNT(*) FROM events WHERE kind='offline_replay'").fetchone()[0], 3)

    def test_employee_save_cannot_change_protected_fields(self):
        self.employee()
        self.assertEqual(bridge.set_employee_monitoring({"mac": MAC, "actor": ACTOR,
                                                         "scan_paused": True}), (True, ""))
        old = bridge.employees_list()[0]
        self.assertEqual(bridge.upsert_employee({"mac": MAC, "name": "Updated",
                "actor": ACTOR, "scan_paused": False, "weekly_schedule": {},
                "scan_pause_at": None, "scan_pause_by": "forged"}), (True, ""))
        new = bridge.employees_list()[0]
        for field in ("weekly_schedule", "scan_paused", "scan_pause_at", "scan_pause_by"):
            self.assertEqual(new[field], old[field])
        self.assertEqual(new["name"], "Updated")
        self.assertEqual(bridge.upsert_employee({"mac": MAC, "dept": "Updated dept"}), (True, ""))
        self.assertEqual(bridge.employees_list()[0]["name"], "Updated")


class MonitoringHTTPTests(IsolatedBridge):
    def setUp(self):
        super().setUp()
        auth = patch.dict(os.environ, {"ROZTASH_BRIDGE_AUTH_FILE": str(Path(bridge.DB_PATH).with_suffix(".key"))})
        auth.start()
        self.addCleanup(auth.stop)
        self.server = bridge.Server(("127.0.0.1", 0), bridge.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, doc=None, actor=None):
        method = "GET" if doc is None else "POST"
        body = b"" if doc is None else json.dumps(doc).encode()
        headers = {"Content-Type": "application/json"}
        if actor:
            headers.update(sign_request(method, path, body, actor))
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            conn.request(method, path, body, headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_signed_monitoring_rejects_unsigned_actor_mismatch_and_unknown_role(self):
        self.employee()
        doc = {"mac": MAC, "actor": ACTOR, "scan_paused": True}
        self.assertEqual(self.request("/api/monitoring", doc)[0], 401)
        self.assertEqual(self.request("/api/monitoring", doc, "other@example.test")[0], 401)
        unknown = {**doc, "actor": "other@example.test"}
        self.assertEqual(self.request("/api/monitoring", unknown, unknown["actor"])[0], 403)
        self.assertEqual(self.request("/api/monitoring", doc, ACTOR)[0], 200)
        self.assertTrue(self.request("/api/employees")[1]["employees"][0]["scan_paused"])
        self.assertEqual(self.request("/api/employees", {"mac": MAC, "name": "Edited",
                         "scan_paused": False, "weekly_schedule": {}, "actor": ACTOR})[0], 200)
        self.assertTrue(self.request("/api/employees")[1]["employees"][0]["scan_paused"])

    def test_health_interval_default_permissions_validation_and_persistence(self):
        path = "/api/monitoring/settings"
        self.assertEqual(self.request(path)[1]["health_interval_s"], 600)
        self.assertEqual(self.request(path, {"actor": ACTOR, "health_interval_s": 900})[0], 401)
        for value in (True, "900", 900.0, 59, 86401, None):
            with self.subTest(value=value):
                self.assertEqual(self.request(path, {"actor": ACTOR, "health_interval_s": value}, ACTOR)[0], 400)
        for role in ("owner", "viewer"):
            with patch.object(bridge, "get_role", return_value=role):
                self.assertEqual(self.request(path, {"actor": ACTOR, "health_interval_s": 900}, ACTOR)[0], 200)
        self.assertEqual(self.request(path)[1]["health_interval_s"], 900)
        self.close_db()
        self.assertEqual(self.request(path)[1]["health_interval_s"], 900)
        self.assertEqual(self.request(path)[1]["updated_by"], ACTOR)


class PolicyPublishingTests(IsolatedBridge):
    def test_active_lists_without_address_types_and_unique_health_routing(self):
        self.employee()
        bridge.db().execute("UPDATE employees SET staff_group='hse' WHERE mac=?", (MAC,))
        bridge.db().execute("UPDATE employees SET weekly_schedule='{}' WHERE mac=?", (MAC,))
        bridge.db().commit()
        second, absent = "aa:bb:cc:dd:ee:02", "aa:bb:cc:dd:ee:03"
        self.employee(second)
        self.employee(absent)
        self.gateway("gw-a", 0.2, 0.3)
        self.gateway("gw-b", 0.7, 0.8)
        self.presence("gw-a", -40)
        self.presence("gw-b", -80)
        self.presence("gw-b", -50, NOW - 100, second)
        sent = []
        def publisher(topic, payload, retained=False):
            sent.append((topic, payload, retained))
            return True, "sent"
        with patch.object(bridge.time, "time", return_value=NOW), patch.object(bridge, "publish", side_effect=publisher):
            result = bridge.publish_scan_policies()
            self.assertEqual(result, {"gw-a": "sent", "gw-b": "sent"})
            bridge.publish_scan_policies()
        policies = {topic.split("/")[1]: json.loads(payload) for topic, payload, retained in sent if payload}
        self.assertEqual(policies["gw-a"]["active_macs"], [second, absent])
        self.assertEqual(policies["gw-b"]["active_macs"], [second, absent])
        self.assertEqual(policies["gw-a"]["health_macs"], [absent])
        self.assertEqual(policies["gw-b"]["health_macs"], [second])
        self.assertEqual(policies["gw-a"]["health_interval_s"], 600)
        self.assertIn(MAC, policies["gw-a"]["emergency_macs"])
        self.assertTrue(all(not retained for _, payload, retained in sent if payload))
        self.assertEqual(len([1 for _, payload, retained in sent if not payload and retained]), 2)

    def test_capacity_fail_closed_and_lease_bounded_at_transition(self):
        self.employee()
        self.gateway("gw-a", 0.2, 0.3)
        before_end = local_ts(hour=15, minute=59, second=57)
        self.assertLessEqual(bridge.employee_scan_policy(before_end)["lease_s"], 3)
        with patch.object(bridge, "MAX_ACTIVE_MACS", 0), patch.object(bridge.time, "time", return_value=NOW):
            sent = []
            with patch.object(bridge, "publish", side_effect=lambda t, p, retained=False: (sent.append(p) or (True, "sent"))):
                bridge.publish_scan_policies()
            policy = json.loads(next(p for p in sent if p))
            self.assertEqual(policy["active_macs"], [])
            self.assertEqual(policy["health_macs"], [])
            self.assertTrue(bridge.employee_scan_policy(NOW)["error"])

    def test_publish_failure_diagnostics_and_status_wakeup(self):
        self.gateway("gw-a", 0.2, 0.3)
        bridge._scan_policy_wake.clear()
        bridge.ingest("roztash/gw-new/status", json.dumps({"online": True}), NOW)
        self.assertTrue(bridge._scan_policy_wake.is_set())
        with patch.object(bridge, "publish", return_value=(False, "broker unavailable")):
            result = bridge.publish_scan_policies()
        self.assertIn("broker unavailable", result["gw-a"])
        settings = bridge.monitoring_settings()
        self.assertIn("broker unavailable", settings["policy_delivery"]["gw-a"]["error"])
        count = bridge.db().execute("SELECT COUNT(*) FROM events").fetchone()[0]
        for leaf in ("scan-policy", "cmd"):
            bridge.ingest(f"roztash/gw-a/{leaf}", "{}", NOW)
        self.assertEqual(bridge.db().execute("SELECT COUNT(*) FROM events").fetchone()[0], count)


if __name__ == "__main__":
    unittest.main()
