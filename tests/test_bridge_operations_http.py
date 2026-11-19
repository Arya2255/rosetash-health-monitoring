"""Signed operational API routes over the real local HTTP handler."""
import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_location_policy import ACTOR, MAC, NOW, IsolatedBridge, bridge
from bridge_auth import sign_request
import live


class OperationalHTTPTests(IsolatedBridge):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, {
            "ROZTASH_BRIDGE_AUTH_FILE": str(Path(bridge.DB_PATH).with_suffix(".key"))}))
        self.server = bridge.Server(("127.0.0.1", 0), bridge.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def post(self, path, doc, actor=ACTOR, signed=True):
        body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if signed:
            headers.update(sign_request("POST", path, body, actor))
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request("POST", path, body, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_measurement_endpoint_requires_signed_actor_and_returns_policy_reason(self):
        bridge.upsert_employee({"mac": MAC, "name": "Synthetic"})
        with patch.object(bridge, "request_measurement", return_value=(False, "band unavailable", {})) as request:
            status, body = self.post("/api/measurements", {"mac": MAC, "actor": ACTOR})
            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "band unavailable")
            request.assert_called_once()
        status, body = self.post("/api/measurements", {"mac": MAC, "actor": ACTOR}, signed=False)
        self.assertEqual(status, 401)

    def test_vibration_rejection_distinguishes_registry_from_mqtt_and_work_hours(self):
        self.gateway("gw-a", .2, .3)
        self.employee(schedule={})
        host, port = self.server.server_address
        with patch.object(live, "BRIDGE", f"http://{host}:{port}"), \
                patch.object(live, "MODE", "auto"), patch.object(bridge, "publish") as publish:
            ok, reason = live.send_vibrate(MAC)
            self.assertFalse(ok)
            self.assertIn("وضعیت گیت‌وی", reason)

            bridge.ingest("roztash/gw-a/status", '{"online":true}', bridge.time.time())
            ok, reason = live.send_vibrate(MAC)
            self.assertFalse(ok)
            self.assertIn("ساعت کاری", reason)
            publish.assert_not_called()

    def test_gateway_diagnostic_http_is_signed_and_live_client_polls_status(self):
        with patch.object(bridge, "get_role", return_value="owner"), \
                patch.object(bridge, "publish", return_value=(True, "sent")):
            status, body = self.post("/api/gateways/diagnostics", {
                "actor": ACTOR, "action": "scan", "gw": "gw-a"})
            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            request_id = body["info"]["request_id"]
            host, port = self.server.server_address
            with patch.object(live, "BRIDGE", f"http://{host}:{port}"), \
                    patch.object(live, "MODE", "auto"):
                ok, info = live.gateway_diagnostic(
                    actor=ACTOR, action="status", request_id=request_id)
            self.assertTrue(ok, info)
            self.assertEqual(info["status"], "pending")
        status, body = self.post("/api/gateways/diagnostics", {
            "actor": ACTOR, "action": "status", "request_id": request_id}, signed=False)
        self.assertEqual(status, 401)

    def test_ack_route_persists_and_requires_signed_actor(self):
        self.assertEqual(bridge.upsert_employee({"mac": MAC, "name": "Synthetic"}), (True, ""))
        bridge.db().execute("UPDATE employees SET weekly_schedule=? WHERE mac=?",
                            (json.dumps({"mon": [{"start": "08:00", "end": "16:00"}]}), MAC))
        bridge.db().commit()
        self.assertEqual(bridge.upsert_gateway({"gw": "gw-a", "kind": "installed", "x": .2, "y": .3}), (True, ""))
        bridge.ingest("roztash/gw-a/presence", json.dumps({"bands": [{"mac": MAC, "rssi": -40}]}), NOW)
        bridge.ingest("roztash/gw-a/health", json.dumps({
            "mac": MAC, "state": "done", "avg": 130, "n": 2, "bpm": [130, 130]}), NOW)
        alert = bridge.snapshot(NOW)["alerts_active"][0]
        status, body = self.post("/api/alerts/ack", {"id": alert["id"], "actor": ACTOR})
        self.assertEqual((status, body["ok"]), (200, True))
        self.assertEqual(bridge.snapshot(NOW+1)["alerts_active"][0]["status"], "acknowledged")
        status, body = self.post("/api/alerts/ack", {"id": alert["id"], "actor": ACTOR}, signed=False)
        self.assertEqual(status, 401)

    def test_discovery_endpoint_is_owner_only_and_separates_network_seen_from_online(self):
        found = [{"v": 1, "gw": "gw-found", "mac": "02:00:00:00:00:01", "fw": "v1",
                  "ip": "192.168.1.50", "transport": "ethernet", "mqtt_connected": True}]
        host, port = self.server.server_address
        with patch.object(bridge, "get_role", return_value="owner"), \
                patch.object(bridge, "_host_ip_candidates", return_value=[]), \
                patch("tools.gateway_discovery.discover_gateways", return_value=found), \
                patch.object(live, "BRIDGE", f"http://{host}:{port}"), \
                patch.object(live, "MODE", "auto"):
            self.assertEqual(live.discover_gateways(actor=ACTOR), (True, found))
            row, = live.live_gateways(force=True)
        self.assertEqual(row["gw"], "gw-found")
        self.assertFalse(row["registered"])
        self.assertFalse(row["online"])
        self.assertTrue(row["network_seen"])
        self.assertEqual(row["network_ip"], "192.168.1.50")
        self.assertEqual(bridge.snapshot()["gateways"], [])
        observation = bridge.db().execute(
            "SELECT gw,ip,mqtt_connected FROM network_gateway_observations").fetchone()
        self.assertEqual(tuple(observation), ("gw-found", "192.168.1.50", 1))
        with patch.object(bridge, "get_role", return_value="viewer"):
            status, body = self.post("/api/gateways/discover", {"actor": ACTOR})
        self.assertEqual(status, 403)

    def test_real_offline_episode_survives_restart_and_closes_on_recovery(self):
        self.gateway("gw-a", .2, .3)
        self.gateway("gw-never", .5, .5)
        bridge.ingest("roztash/gw-a/status", '{"online":true}', NOW)
        bridge.ingest("roztash/gw-a/status", '{"online":false}', NOW + 1)
        alert, = bridge.snapshot(NOW + 1)["alerts_active"]
        self.assertEqual((alert["gw"], alert["type"]), ("gw-a", "gateway_offline"))
        self.close_db()
        self.assertEqual(bridge.snapshot(NOW + 2)["alerts_active"][0]["id"], alert["id"])
        bridge.ingest("roztash/gw-a/status", '{"online":true}', NOW + 3)
        self.assertEqual(bridge.snapshot(NOW + 3)["alerts_active"], [])
        boundary = NOW + 3 + bridge.GATEWAY_ONLINE_TTL
        self.assertEqual(bridge.snapshot(boundary)["alerts_active"], [])
        later, = bridge.snapshot(boundary + 1)["alerts_active"]
        self.assertNotEqual(later["id"], alert["id"])


if __name__ == "__main__":
    unittest.main()
