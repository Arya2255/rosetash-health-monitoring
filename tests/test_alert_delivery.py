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

    def test_off_shift_hse_rejects_ordinary_vibration_but_accepts_emergency(self):
        bridge.db().execute("UPDATE employees SET weekly_schedule='{}' WHERE mac=?", (HSE1,))
        bridge.db().commit()
        with patch.object(bridge, "publish", return_value=(True, "sent")) as pub:
            ok, error, _ = bridge.command({"action": "vibrate", "mac": HSE1, "gw": "gw-a"})
            self.assertFalse(ok)
            self.assertIn("paused", error)
            ok, error, _ = bridge.command({"action": "vibrate", "mac": HSE1,
                                           "gw": "gw-a", "emergency": True})
        self.assertTrue(ok, error)
        self.assertEqual(json.loads(pub.call_args.args[1])["emergency"], True)

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

    def test_expired_telemetry_closes_episode_and_stale_delivery(self):
        _,commands=self.send_next(NOW)
        old=commands[0]["request_id"]
        at=NOW+bridge.HEALTH_TTL+1
        result,_=self.send_next(at)
        self.assertEqual(result,{})
        episode=bridge.db().execute("SELECT closed_at FROM staff_alert_episode WHERE id=(SELECT episode_id FROM staff_alert_delivery WHERE request_id=?)", (old,)).fetchone()
        delivery=bridge.db().execute("SELECT status FROM staff_alert_delivery WHERE request_id=?", (old,)).fetchone()
        self.assertIsNotNone(episode["closed_at"])
        self.assertEqual(delivery["status"],"closed")

    def test_stale_gateway_delivery_expires_and_releases_gateway_slot(self):
        _,commands=self.send_next(NOW)
        old=commands[0]
        c=bridge.db()
        c.execute("UPDATE staff_alert_delivery SET status='confirmed',confirmed_at=? WHERE target_mac IN (?,?)",
                  (NOW,HSE2,LEAD))
        c.commit()
        for mac in (MAC,HSE1,HSE2,LEAD): self.presence("gw-a",-40,NOW+480,mac)
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":True,"scan_policy_ready":True,
                      "vibration_request_id":True,"vibration_repeats":3}),NOW+480)
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":False}),NOW+481)
        with patch.object(bridge,"publish",return_value=(True,"sent")):
            bridge.dispatch_alert_notifications(NOW+481)
        delivery=c.execute("SELECT status FROM staff_alert_delivery WHERE request_id=?",(old["request_id"],)).fetchone()
        self.assertEqual(delivery["status"],"unconfirmed")

        # Restore gateway availability, raise an independent battery episode,
        # and verify the stale staff ACK no longer reserves the one command slot.
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":True,"scan_policy_ready":True,
                      "vibration_request_id":True,"vibration_repeats":3}),NOW+482)
        self.presence("gw-a",-40,NOW+482,MAC)
        bridge.ingest("roztash/gw-a/vitals",json.dumps({"mac":MAC,"battery":10}),NOW+482)
        with patch.object(bridge,"publish",return_value=(True,"sent")) as pub:
            sent=bridge.dispatch_battery_alerts(NOW+482)
        self.assertEqual(sent,{MAC:"sent"})
        self.assertEqual(json.loads(pub.call_args.args[1])["reason"],"battery_low")

    def test_battery_slot_is_released_when_staff_retry_deadline_is_due(self):
        _,commands=self.send_next(NOW)
        for mac in (MAC,HSE1,HSE2,LEAD): self.presence("gw-a",-40,NOW+120,mac)
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":True,"scan_policy_ready":True,
                      "vibration_request_id":True,"vibration_repeats":3}),NOW+120)
        bridge.ingest("roztash/gw-a/vitals",json.dumps({"mac":MAC,"battery":10}),NOW+120)
        # Production loop gives battery warnings first refusal. An in-flight
        # staff request is not a blocker once its ACK retry is actually due.
        with patch.object(bridge,"publish",return_value=(True,"sent")) as pub:
            sent=bridge.dispatch_battery_alerts(NOW+120)
        self.assertEqual(sent,{MAC:"sent"})
        self.assertEqual(json.loads(pub.call_args.args[1])["reason"],"battery_low")
        self.assertTrue(commands)

    def test_battery_slot_is_released_when_staff_attempt_budget_is_spent(self):
        _,commands=self.send_next(NOW)
        request=commands[0]["request_id"]
        c=bridge.db()
        c.execute("UPDATE staff_alert_delivery SET attempts=?,next_attempt_at=? WHERE request_id=?",
                  (bridge.staff_alert_policy.MAX_ATTEMPTS,NOW+120,request))
        c.commit()
        bridge.ingest("roztash/gw-a/vitals",json.dumps({"mac":MAC,"battery":10}),NOW+1)
        for mac in (MAC,HSE1,HSE2,LEAD): self.presence("gw-a",-40,NOW+1,mac)
        with patch.object(bridge,"publish",return_value=(True,"sent")) as pub:
            result=bridge.dispatch_battery_alerts(NOW+1)
        self.assertEqual(result,{MAC:"sent"})
        self.assertEqual(json.loads(pub.call_args.args[1])["reason"],"battery_low")

    def test_ack_during_publish_failure_is_not_overwritten(self):
        _,commands=self.send_next(NOW)
        command=commands[0]
        for mac in (MAC,HSE1,HSE2,LEAD): self.presence("gw-a",-40,NOW+120,mac)
        bridge.ingest("roztash/gw-a/status",json.dumps({"online":True,"scan_policy_ready":True,
                      "vibration_request_id":True,"vibration_repeats":3}),NOW+120)
        def publish_then_fail(topic,payload,retained=False):
            bridge.ingest("roztash/gw-a/event",json.dumps({**command,"type":"vibrated",
                          "completed_pulses":3}),NOW+1)
            return False,"late publish failure"
        with patch.object(bridge,"publish",side_effect=publish_then_fail):
            result=bridge.dispatch_alert_notifications(NOW+120)
        self.assertEqual(result,{HSE1:"publish_failed"})
        self.assertEqual(bridge.db().execute("SELECT status FROM staff_alert_delivery WHERE request_id=?",
                          (command["request_id"],)).fetchone()[0],"confirmed")

    def test_wrong_target_request_reason_replay_and_old_ack_do_not_confirm(self):
        _,commands=self.send_next(NOW)
        command=commands[0]
        valid={**command,"type":"vibrated","completed_pulses":3}
        for event,at in (({**valid,"mac":HSE2},NOW+1),
                         ({**valid,"request_id":"staff-unrelated"},NOW+1),
                         ({**valid,"reason":"manual"},NOW+1),
                         ({**valid,"replayed":True},NOW+1),
                         (valid,NOW-1)):
            with self.subTest(event=event,at=at):
                bridge.ingest("roztash/gw-a/event",json.dumps(event),at)
                row=bridge.db().execute("SELECT status,completed_pulses FROM staff_alert_delivery WHERE request_id=?",
                                        (command["request_id"],)).fetchone()
                self.assertEqual((row["status"],row["completed_pulses"]),("awaiting_ack",0))
        self.ack(command,NOW+2)
        self.assertEqual(bridge.db().execute("SELECT status FROM staff_alert_delivery WHERE request_id=?",
                          (command["request_id"],)).fetchone()[0],"confirmed")

    def test_confirmed_target_and_partial_count_survive_database_reopen(self):
        _,commands=self.send_next(NOW)
        first=commands[0]
        self.ack(first,NOW+1)
        _,commands=self.send_next(NOW+2)
        second=commands[0]
        self.ack(second,NOW+3,2)
        bridge._db.close()
        bridge._db=None
        rows=bridge.db().execute("SELECT target_mac,status,completed_pulses FROM staff_alert_delivery ORDER BY target_mac").fetchall()
        state={row["target_mac"]:(row["status"],row["completed_pulses"]) for row in rows}
        self.assertEqual(state[HSE1],("confirmed",3))
        self.assertEqual(state[HSE2],("awaiting_ack",2))
        self.assertEqual(self.send_next(NOW+4)[0],{})

    def test_pause_and_employee_removal_close_pending_source_episode(self):
        for reason in ("paused","removed"):
            with self.subTest(reason=reason):
                _,commands=self.send_next(NOW)
                request=commands[0]["request_id"]
                if reason=="paused":
                    bridge.db().execute("UPDATE employees SET scan_paused=1 WHERE mac=?",(MAC,))
                else:
                    bridge.db().execute("DELETE FROM employees WHERE mac=?",(MAC,))
                bridge.db().commit()
                self.send_next(NOW+1)
                row=bridge.db().execute("SELECT d.status,e.closed_at FROM staff_alert_delivery d JOIN staff_alert_episode e ON e.id=d.episode_id WHERE d.request_id=?",(request,)).fetchone()
                self.assertEqual(row["status"],"closed")
                self.assertIsNotNone(row["closed_at"])
                if reason=="paused":
                    bridge.db().execute("UPDATE employees SET scan_paused=0 WHERE mac=?",(MAC,))
                    bridge.db().commit()

if __name__ == "__main__": unittest.main()
