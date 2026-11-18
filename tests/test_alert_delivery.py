"""Durable automatic health-alert delivery with synthetic bands and gateway ACKs."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_location_policy import IsolatedBridge, bridge, MAC, NOW

HSE1 = "aa:bb:cc:dd:ee:21"
HSE2 = "aa:bb:cc:dd:ee:22"
LEAD = "aa:bb:cc:dd:ee:23"

class DeliveryTests(IsolatedBridge):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(bridge, "log"))
        for mac, group, unit in ((MAC,"employee","Unit A"),(HSE1,"hse","Unit A"),
                                 (HSE2,"hse","Unit B"),(LEAD,"shift_leader","Unit A")):
            self.employee(mac)
            bridge.upsert_employee({"mac":mac,"name":group,"staff_group":group,
                                    "company":"Factory","dept":unit,"line":"Line 1"})
        self.gateway("gw-a", .2, .3)
        for mac in (MAC,HSE1,HSE2,LEAD): self.presence("gw-a",-40,NOW,mac)
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":True,"scan_policy_ready":True,
                      "vibration_request_id":True,"vibration_repeats":3}),NOW)
        bridge.ingest("roztash/gw-a/health",json.dumps({"mac":MAC,"state":"done",
                      "avg":130,"n":1,"bpm":[130],"wearing":True}),NOW)

    def send_next(self, at):
        with patch.object(bridge,"publish",return_value=(True,"sent")) as pub:
            result=bridge.dispatch_alert_notifications(at)
        return result, [json.loads(call.args[1]) for call in pub.call_args_list]

    def ack(self, doc, at, pulses=3):
        bridge.ingest("roztash/gw-a/event",json.dumps({**doc,"type":"vibrated",
                      "completed_pulses":pulses}),at)

    def test_gateway_queue_serializes_all_hse_and_local_contact(self):
        expected=[(HSE1,True),(HSE2,True),(LEAD,False)]
        for offset,(mac,emergency) in enumerate(expected):
            result,commands=self.send_next(NOW+offset*2)
            self.assertEqual(len(commands),1)
            command=commands[0]
            self.assertEqual(command["mac"],mac)
            self.assertEqual(command.get("emergency",False),emergency)
            self.assertEqual(command["reason"],"staff_alert")
            self.assertEqual(command["repeats"],3)
            self.assertTrue(command["request_id"])
            self.assertEqual(result,{mac:"sent"})
            self.ack(command,NOW+offset*2+1)
        self.assertEqual(bridge.dispatch_alert_notifications(NOW+8),{})

    def test_partial_ack_is_not_confirmation_and_same_request_resumes_before_next_target(self):
        _,commands=self.send_next(NOW)
        command=commands[0]
        self.ack(command,NOW+1,pulses=2)
        row=bridge.db().execute("SELECT status,completed_pulses FROM staff_alert_delivery WHERE request_id=?",
                                (command["request_id"],)).fetchone()
        self.assertEqual((row["status"],row["completed_pulses"]),("awaiting_ack",2))
        self.assertEqual(bridge.dispatch_alert_notifications(NOW+2),{})
        for mac in (MAC,HSE1,HSE2,LEAD): self.presence("gw-a",-40,NOW+120,mac)
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":True,"scan_policy_ready":True,
                      "vibration_request_id":True,"vibration_repeats":3}),NOW+120)
        with patch.object(bridge,"publish",return_value=(True,"sent")) as pub:
            result=bridge.dispatch_alert_notifications(NOW+120)
        retry=json.loads(pub.call_args.args[1])
        self.assertEqual(result,{HSE1:"sent"})
        self.assertEqual(retry["request_id"],command["request_id"])
        self.assertEqual(retry["completed_pulses"],2)
        self.ack(command,NOW+121,pulses=3)
        row=bridge.db().execute("SELECT status,completed_pulses FROM staff_alert_delivery WHERE request_id=?",
                                (command["request_id"],)).fetchone()
        self.assertEqual((row["status"],row["completed_pulses"]),("confirmed",3))
        result,next_commands=self.send_next(NOW+122)
        self.assertEqual((result,next_commands[0]["mac"]),({HSE2:"sent"},HSE2))

    def test_unrelated_gateway_cannot_confirm(self):
        _,commands=self.send_next(NOW)
        command=commands[0]
        bridge.ingest("roztash/other-gw/event",json.dumps({**command,"type":"vibrated",
                      "completed_pulses":3}),NOW+1)
        self.assertEqual(bridge.db().execute("SELECT status FROM staff_alert_delivery WHERE request_id=?",
                          (command["request_id"],)).fetchone()[0],"awaiting_ack")

    def test_supervisor_alert_routes_every_hse(self):
        bridge.upsert_employee({"mac":MAC,"staff_group":"supervisor"})
        result,commands=self.send_next(NOW)
        self.assertEqual((result,commands[0]["mac"],commands[0].get("emergency")),({HSE1:"sent"},HSE1,True))
        self.ack(commands[0],NOW+1)
        result,commands=self.send_next(NOW+2)
        self.assertEqual((result,commands[0]["mac"],commands[0].get("emergency")),({HSE2:"sent"},HSE2,True))

    def test_health_recovery_closes_episode_and_new_alert_opens_fresh_delivery(self):
        _,commands=self.send_next(NOW)
        old=commands[0]["request_id"]
        bridge.ingest("roztash/gw-a/health",json.dumps({"mac":MAC,"state":"done","avg":78,"n":1,"wearing":True}),NOW+1)
        bridge.dispatch_alert_notifications(NOW+1)
        self.assertEqual(bridge.db().execute("SELECT status FROM staff_alert_delivery WHERE request_id=?",
                          (old,)).fetchone()[0],"closed")
        bridge.ingest("roztash/gw-a/health",json.dumps({"mac":MAC,"state":"done","avg":130,"n":1,"wearing":True}),NOW+2)
        result,commands=self.send_next(NOW+2)
        self.assertEqual(result,{HSE1:"sent"})
        self.assertNotEqual(commands[0]["request_id"],old)

if __name__ == "__main__": unittest.main()
