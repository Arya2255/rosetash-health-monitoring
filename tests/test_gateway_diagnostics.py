"""Owner-only gateway BLE diagnostics stay separate from employee monitoring."""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_location_policy import ACTOR, MAC, NOW, IsolatedBridge, bridge


class GatewayDiagnosticTests(IsolatedBridge):
    def owner(self):
        return patch.object(bridge, "get_role", return_value="owner")

    def start(self, action="scan", mac=None, at=NOW):
        doc = {"actor": ACTOR, "action": action, "gw": "gw-a"}
        if mac is not None:
            doc["mac"] = mac
        with self.owner(), patch.object(bridge, "publish", return_value=(True, "sent")) as publish:
            result = bridge.gateway_diagnostic(doc, now=at)
        return result, publish

    def test_scan_requires_owner_and_publishes_bounded_non_retained_request(self):
        with patch.object(bridge, "publish") as publish:
            ok, error, doc = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "scan", "gw": "gw-a"}, now=NOW)
        self.assertEqual((ok, error, doc), (False, "forbidden", {}))
        publish.assert_not_called()

        (ok, error, doc), publish = self.start()
        self.assertTrue(ok, error)
        self.assertEqual(doc["status"], "pending")
        self.assertEqual(doc["action"], "scan")
        self.assertRegex(doc["request_id"], r"\Adiag-[0-9a-f]{32}\z")
        args, kwargs = publish.call_args
        self.assertEqual(args[0], "roztash/gw-a/cmd")
        self.assertIs(kwargs["retained"], False)
        command = json.loads(args[1])
        self.assertEqual(command, {"action": "diagnostic_scan", "request_id": doc["request_id"], "ttl_s": 20})

        with self.owner():
            ok, error, current = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": doc["request_id"]}, now=NOW + 1)
        self.assertTrue(ok, error)
        self.assertEqual(current["status"], "pending")
        self.assertEqual(current["devices"], [])

    def test_scan_result_is_correlated_validated_and_not_monitoring_data(self):
        (ok, _, started), _ = self.start()
        request_id = started["request_id"]
        bridge.ingest("roztash/gw-a/diagnostic", json.dumps({
            "request_id": "diag-" + "0" * 32, "type": "scan_done",
            "devices": [{"mac": MAC, "rssi": -1}],
        }), NOW + 2)
        bridge.ingest("roztash/gw-a/diagnostic", json.dumps({
            "request_id": request_id, "type": "scan_done", "devices": [
                {"mac": MAC, "rssi": -71},
                {"mac": "not-a-mac", "rssi": -1},
                {"mac": "aa:bb:cc:dd:ee:02", "rssi": True},
                {"mac": "aa:bb:cc:dd:ee:03", "rssi": -50},
            ],
        }), NOW + 3)
        with self.owner():
            ok, error, current = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": request_id}, now=NOW + 4)
        self.assertTrue(ok, error)
        self.assertEqual(current["status"], "done")
        self.assertEqual(current["devices"], [
            {"mac": "aa:bb:cc:dd:ee:03", "rssi": -50},
            {"mac": MAC, "rssi": -71},
        ])
        self.assertEqual(bridge.db().execute("SELECT count(*) FROM band_observations").fetchone()[0], 0)
        self.assertEqual(bridge.db().execute("SELECT count(*) FROM health").fetchone()[0], 0)
        self.assertEqual(bridge.db().execute("SELECT count(*) FROM vitals").fetchone()[0], 0)
        self.assertEqual(bridge.snapshot(NOW + 4)["bands"], [])

    def test_probe_request_and_result(self):
        with self.owner(), patch.object(bridge, "publish") as publish:
            ok, error, doc = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "probe", "gw": "gw-a", "mac": "bad"}, now=NOW)
        self.assertEqual((ok, error, doc), (False, "invalid mac", {}))
        publish.assert_not_called()

        (ok, error, started), publish = self.start("probe", MAC)
        self.assertTrue(ok, error)
        command = json.loads(publish.call_args.args[1])
        self.assertEqual(command["action"], "diagnostic_probe")
        self.assertEqual(command["mac"], MAC)
        request_id = started["request_id"]
        bridge.ingest("roztash/gw-a/diagnostic", json.dumps({
            "request_id": request_id, "type": "probe_done", "mac": MAC,
            "connected": True, "battery": 90,
        }), NOW + 3)
        with self.owner():
            _, _, current = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": request_id}, now=NOW + 4)
        self.assertEqual(current["status"], "done")
        self.assertIs(current["connected"], True)
        self.assertEqual(current["battery"], 90)

    def test_one_active_request_per_gateway_and_expiry(self):
        (ok, _, first), _ = self.start()
        (ok, error, busy), _ = self.start()
        self.assertFalse(ok)
        self.assertEqual(error, "diagnostic busy")
        self.assertEqual(busy["request_id"], first["request_id"])
        with self.owner():
            _, _, expired = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": first["request_id"]}, now=NOW + 21)
        self.assertEqual(expired["status"], "timeout")

    def test_publish_failure_is_not_reported_as_pending(self):
        with self.owner(), patch.object(bridge, "publish", return_value=(False, "offline")):
            ok, error, doc = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "scan", "gw": "gw-a"}, now=NOW)
        self.assertFalse(ok)
        self.assertEqual(error, "publish failed")
        self.assertEqual(doc["status"], "failed")

    def test_probe_connect_failure_is_not_mislabeled_as_command_rejection(self):
        (ok, _, started), _ = self.start("probe", MAC)
        request_id = started["request_id"]
        bridge.ingest("roztash/gw-a/diagnostic", json.dumps({
            "request_id": request_id, "type": "probe_reject", "mac": MAC,
            "connected": False, "detail": "connect",
        }), NOW + 3)
        with self.owner():
            _, _, current = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": request_id}, now=NOW + 4)
        self.assertEqual(current["status"], "failed")
        self.assertIs(current["connected"], False)
        self.assertEqual(current["detail"], "connect_failed")

    def test_invalid_request_and_result_cannot_complete_another_request(self):
        (ok, _, started), _ = self.start()
        request_id = started["request_id"]
        bridge.ingest("roztash/gw-a/diagnostic", json.dumps({
            "request_id": request_id, "type": "probe_done", "mac": MAC,
            "connected": True,
        }), NOW + 2)
        with self.owner():
            _, _, current = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": request_id}, now=NOW + 3)
        self.assertEqual(current["status"], "pending")
        with self.owner():
            ok, error, _ = bridge.gateway_diagnostic(
                {"actor": ACTOR, "action": "status", "request_id": "unknown"}, now=NOW + 3)
        self.assertEqual((ok, error), (False, "not found"))


if __name__ == "__main__":
    unittest.main()
