"""Low-battery alerts: isolated storage, synthetic vitals, mocked radio boundary."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_location_policy import IsolatedBridge, bridge, MAC, NOW, ACTOR


class BatteryAlertTests(IsolatedBridge):
    def setUp(self):
        super().setUp()
        self.employee()
        self.gateway('gw-a',.2,.3)
        self.ready(NOW)

    def ready(self, at, gw='gw-a', rssi=-40, capable=True):
        bridge.ingest('roztash/'+gw+'/status', json.dumps({
            'online':True,'scan_policy_ready':True,'vibration_request_id':capable,
            'fw':'0.5.1-battery'}),at)
        self.presence(gw,rssi,at)

    def vitals(self, level, at=NOW, **extra):
        bridge.ingest('roztash/gw-a/vitals',json.dumps({'mac':MAC,'battery':level,**extra}),at)

    def alerts(self, at=NOW):
        return bridge.snapshot(at)['battery_alerts']

    def test_low_battery_warns_in_software_and_sends_correlated_vibration(self):
        self.vitals(20)
        alerts=self.alerts()
        self.assertEqual(len(alerts),1)
        self.assertEqual(alerts[0]['battery'],20)
        self.assertEqual(alerts[0]['vibration_status'],'pending')
        with patch.object(bridge,'publish',return_value=(True,'sent')) as publish:
            bridge.dispatch_battery_alerts(now=NOW)
            publish.assert_called_once()
            topic,payload=publish.call_args.args[:2]
            self.assertEqual(topic,'roztash/gw-a/cmd')
            doc=json.loads(payload)
            self.assertEqual(doc['action'],'vibrate')
            self.assertEqual(doc['reason'],'battery_low')
            self.assertEqual(doc['mac'],MAC)
            self.assertEqual(doc['ttl_s'],60)
            self.assertTrue(doc['request_id'].startswith('battery-'))
            self.assertFalse(publish.call_args.kwargs.get('retained',False))
        self.assertEqual(self.alerts()[0]['vibration_status'],'awaiting_ack')
        self.assertIsNone(self.alerts()[0]['confirmed_at'])
        bridge.ingest('roztash/gw-a/event',json.dumps({
            'type':'vibrated','mac':MAC,'request_id':doc['request_id'],'reason':'battery_low'}),NOW+1)
        self.assertEqual(self.alerts(NOW+1)[0]['vibration_status'],'confirmed')

    def test_repeated_low_samples_and_restart_do_not_repeat_confirmed_vibration(self):
        self.vitals(19)
        with patch.object(bridge,'publish',return_value=(True,'sent')) as publish:
            bridge.dispatch_battery_alerts(now=NOW)
            request=json.loads(publish.call_args.args[1])
        bridge.ingest('roztash/gw-a/event',json.dumps({
            'type':'vibrated','mac':MAC,'request_id':request['request_id'],'reason':'battery_low'}),NOW+1)
        self.close_db()
        self.vitals(15,NOW+130)
        self.ready(NOW+130)
        with patch.object(bridge,'publish') as publish:
            bridge.dispatch_battery_alerts(now=NOW+130)
            publish.assert_not_called()
        row=bridge.db().execute('SELECT * FROM battery_alert_state WHERE mac=?',(MAC,)).fetchone()
        self.assertEqual(row['attempts'],1)
        self.assertEqual(row['request_id'],request['request_id'])
        self.assertEqual(row['delivery_status'],'confirmed')
        self.assertEqual(bridge.db().execute("SELECT COUNT(*) FROM events WHERE kind='battery_low'").fetchone()[0],1)

    def test_recharge_rearms_only_above_hysteresis_and_creates_new_episode(self):
        self.vitals(10)
        old=bridge.db().execute('SELECT request_id FROM battery_alert_state').fetchone()[0]
        self.vitals(21,NOW+1)
        self.assertEqual(len(self.alerts(NOW+1)),1)
        self.vitals(29,NOW+2)
        self.assertEqual(len(self.alerts(NOW+2)),1)
        self.vitals(30,NOW+3)
        self.assertEqual(self.alerts(NOW+3),[])
        self.vitals(20,NOW+4)
        new=bridge.db().execute('SELECT request_id FROM battery_alert_state').fetchone()[0]
        self.assertNotEqual(old,new)
        self.assertEqual(bridge.db().execute("SELECT COUNT(*) FROM events WHERE kind='battery_low'").fetchone()[0],2)

    def test_invalid_missing_stale_and_replayed_samples_do_not_alert_or_rearm(self):
        for level in (None,True,False,'10',10.0,-1,101):
            self.vitals(level)
        self.vitals(10,replayed=True)
        self.assertEqual(self.alerts(),[])
        self.vitals(10,NOW+1)
        first=bridge.db().execute('SELECT request_id FROM battery_alert_state').fetchone()[0]
        self.vitals(90,NOW)
        self.vitals(90,NOW+1)
        self.vitals(90,NOW+2,replayed=True)
        self.assertEqual(len(self.alerts(NOW+2)),1)
        self.assertEqual(bridge.db().execute('SELECT request_id FROM battery_alert_state').fetchone()[0],first)

    def test_off_shift_paused_unregistered_stale_or_unavailable_never_send(self):
        self.vitals(10)
        for at in (NOW+3601,NOW+8*3600):
            with patch.object(bridge,'publish') as publish:
                bridge.dispatch_battery_alerts(now=at)
                publish.assert_not_called()
            self.assertEqual(self.alerts(at),[])
        with patch.object(bridge.time,'time',return_value=NOW+1):
            self.assertEqual(bridge.set_employee_monitoring({'mac':MAC,'actor':ACTOR,'scan_paused':True}),(True,''))
        with patch.object(bridge,'publish') as publish:
            bridge.dispatch_battery_alerts(now=NOW+1)
            publish.assert_not_called()
        self.assertEqual(self.alerts(NOW+1),[])
        bridge.remove_employee(MAC)
        with patch.object(bridge,'publish') as publish:
            bridge.dispatch_battery_alerts(now=NOW+2)
            publish.assert_not_called()
        self.assertIsNone(bridge.db().execute('SELECT mac FROM battery_alert_state WHERE mac=?',(MAC,)).fetchone())

    def test_retry_is_bounded_and_sent_is_not_confirmed(self):
        self.vitals(5)
        request_ids=[]
        with patch.object(bridge,'publish',return_value=(False,'broker unavailable')) as publish:
            for offset in (0,1,119,120,121,240,360):
                self.ready(NOW+offset)
                bridge.dispatch_battery_alerts(now=NOW+offset)
            self.assertEqual(publish.call_count,3)
            request_ids=[json.loads(c.args[1])['request_id'] for c in publish.call_args_list]
        self.assertEqual(len(set(request_ids)),1)
        self.assertIsNone(self.alerts(NOW+360)[0]['confirmed_at'])
        self.assertEqual(self.alerts(NOW+360)[0]['vibration_status'],'failed')

    def test_unrelated_gateway_manual_ack_wrong_id_and_replay_cannot_confirm(self):
        self.vitals(10)
        with patch.object(bridge,'publish',return_value=(True,'sent')) as publish:
            bridge.dispatch_battery_alerts(now=NOW)
            request=json.loads(publish.call_args.args[1])
        good={'type':'vibrated','mac':MAC,'request_id':request['request_id'],'reason':'battery_low'}
        for gw,doc in [('gw-a',{'type':'vibrated','mac':MAC}),('gw-b',good),
                       ('gw-a',{**good,'request_id':'battery-other'}),
                       ('gw-a',{**good,'replayed':True}),('gw-a',{**good,'reason':'manual'})]:
            bridge.ingest('roztash/'+gw+'/event',json.dumps(doc),NOW+1)
        self.assertIsNone(self.alerts(NOW+1)[0]['confirmed_at'])
        bridge.ingest('roztash/gw-a/event',json.dumps(good),NOW+2)
        self.assertEqual(self.alerts(NOW+2)[0]['vibration_status'],'confirmed')

    def test_older_firmware_keeps_software_warning_without_unsafe_command(self):
        self.ready(NOW,capable=False)
        self.vitals(10)
        with patch.object(bridge,'publish') as publish:
            bridge.dispatch_battery_alerts(now=NOW)
            publish.assert_not_called()
        self.assertEqual(self.alerts()[0]['last_error'],'gateway_update_required')
        self.assertEqual(self.alerts()[0]['attempts'],0)

    def test_success_ack_during_publish_is_not_overwritten(self):
        self.vitals(10)
        def acknowledge(topic,payload,retained=False):
            doc=json.loads(payload)
            bridge.ingest('roztash/gw-a/event',json.dumps({
                'type':'vibrated','mac':MAC,'request_id':doc['request_id'],'reason':'battery_low'}),NOW+1)
            return True,'sent'
        with patch.object(bridge,'publish',side_effect=acknowledge):
            bridge.dispatch_battery_alerts(now=NOW)
        self.assertEqual(self.alerts(NOW+1)[0]['vibration_status'],'confirmed')

    def test_late_retry_does_not_outlive_gateway_duplicate_cache(self):
        self.vitals(10)
        with patch.object(bridge,'publish',return_value=(True,'sent')):
            bridge.dispatch_battery_alerts(now=NOW)
        self.ready(NOW+601)
        self.vitals(9,NOW+601)
        with patch.object(bridge,'publish') as publish:
            bridge.dispatch_battery_alerts(now=NOW+601)
            publish.assert_not_called()
        self.assertEqual(self.alerts(NOW+601)[0]['vibration_status'],'unconfirmed')

    def test_gateway_choice_is_fresh_and_single_flight(self):
        self.gateway('gw-b',.8,.6)
        self.ready(NOW,'gw-b',rssi=-80)
        self.vitals(10)
        other='aa:bb:cc:dd:ee:02'
        self.employee(other)
        self.presence('gw-a',-45,NOW,mac=other)
        bridge.ingest('roztash/gw-a/vitals',json.dumps({'mac':other,'battery':8}),NOW)
        with patch.object(bridge,'publish',return_value=(True,'sent')) as publish:
            bridge.dispatch_battery_alerts(now=NOW)
            self.assertEqual(publish.call_count,1)
            topic,raw=publish.call_args.args[:2]
            self.assertEqual(topic,'roztash/gw-a/cmd')
            request=json.loads(raw)
        bridge.ingest('roztash/gw-a/event',json.dumps({
            'type':'vibrated','mac':request['mac'],'request_id':request['request_id'],'reason':'battery_low'}),NOW+1)
        with patch.object(bridge,'publish',return_value=(True,'sent')) as publish:
            bridge.dispatch_battery_alerts(now=NOW+2)
            self.assertEqual(publish.call_count,1)
            self.assertNotEqual(json.loads(publish.call_args.args[1])['mac'],request['mac'])


if __name__=='__main__':
    unittest.main()
