"""Loopback integration: real MQTT transport, bridge HTTP and app client, synthetic data."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "backend")]
import admin_roles
import bridge
import live
from employee_schedule import DAY_KEYS, TEHRAN

MAC = "aa:bb:cc:dd:ee:01"
ACTOR = "operator@example.test"


@unittest.skipUnless(all(shutil.which(t) for t in ('mosquitto','mosquitto_pub','mosquitto_sub')),
                     "Mosquitto required for actual MQTT integration")
class LoopbackIntegration(unittest.TestCase):
    def test_application_save_policy_transport_location_pause_and_restart(self):
        with tempfile.TemporaryDirectory(prefix='monitoring-integration-') as directory:
            root = Path(directory)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0)); mqtt_port = probe.getsockname()[1]
            conf = root/'broker.conf'
            conf.write_text(f'listener {mqtt_port} 127.0.0.1\nallow_anonymous true\npersistence false\n')
            broker = subprocess.Popen(['mosquitto','-c',str(conf)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.addCleanup(self.stop_process,broker)
            for attempt in range(30):
                try:
                    with socket.create_connection(('127.0.0.1',mqtt_port),timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                self.fail('loopback broker did not start')
            with patch.object(bridge,'DB_PATH',str(root/'state.db')), patch.object(bridge,'PHOTOS_DIR',str(root/'photos')), patch.object(bridge,'_db',None), patch.object(bridge,'MQTT_PORT',str(mqtt_port)), patch.object(bridge,'MQTT_HOST','127.0.0.1'), patch.object(bridge,'get_role',side_effect=lambda actor:'viewer' if actor==ACTOR else ''), patch.dict(os.environ,{'ROZTASH_BRIDGE_AUTH_FILE':str(root/'auth.key')}):
                bridge._scan_policy_cleared.clear();bridge._scan_policy_last.clear()
                server = bridge.Server(('127.0.0.1',0),bridge.Handler)
                serving = threading.Thread(target=server.serve_forever,daemon=True);serving.start()
                try:
                    with patch.object(live,'BRIDGE',f'http://127.0.0.1:{server.server_address[1]}'), patch.object(live,'MODE','auto'):
                        self.assertEqual(live.save_employee({'mac':MAC,'name':'Integration Fixture'}),(True,''))
                        self.assertEqual(bridge.upsert_gateway({'gw':'gw-a','kind':'installed','zone':'A','x':.2,'y':.3}),(True,''))
                        self.assertEqual(bridge.upsert_gateway({'gw':'gw-b','kind':'installed','zone':'B','x':.7,'y':.8}),(True,''))
                        schedule={day:[{'start':'00:00','end':'12:00'},{'start':'12:00','end':'00:00'}] for day in DAY_KEYS}
                        self.assertEqual(live.save_employee_monitoring({'mac':MAC,'actor':ACTOR,'weekly_schedule':schedule}),(True,''))
                        self.assertEqual(live.save_monitoring_settings({'actor':ACTOR,'health_interval_s':900}),(True,''))
                        self.assertEqual(live.monitoring_settings()['health_interval_s'],900)
                        # Actual UDP/radio isn't simulated as proof: only MQTT transport is real here.
                        sub = subprocess.Popen(['mosquitto_sub','-h','127.0.0.1','-p',str(mqtt_port),'-t','roztash/gw-a/scan-policy','-C','2','-W','5','-F','%r %p'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        self.addCleanup(self.stop_process,sub)
                        time.sleep(.15)
                        delivered=bridge.publish_scan_policies()
                        out,err=sub.communicate(timeout=7)
                        self.assertEqual(sub.returncode,0,err)
                        # First empty packet clears a legacy retained lease.
                        retained,payload=next(line for line in out.splitlines() if '{' in line).split(' ',1)
                        self.assertEqual(retained,'0')
                        wire=json.loads(payload)
                        self.assertEqual(wire['active_macs'],[MAC]);self.assertEqual(wire['health_macs'],[MAC])
                        self.assertEqual(wire['health_interval_s'],900)
                        self.assertEqual(delivered,{'gw-a':'sent','gw-b':'sent'})
                        # Publish synthetic sighting packets through the broker, read them as the bridge does.
                        receiver=subprocess.Popen(['mosquitto_sub','-h','127.0.0.1','-p',str(mqtt_port),'-t','roztash/+/presence','-C','2','-W','5','-F','%t %p'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        self.addCleanup(self.stop_process,receiver);time.sleep(.15)
                        for gw,rssi in (('gw-a',-40),('gw-b',-80)):
                            subprocess.run(['mosquitto_pub','-h','127.0.0.1','-p',str(mqtt_port),'-t',f'roztash/{gw}/presence','-m',json.dumps({'bands':[{'mac':MAC,'rssi':rssi,'age_ms':0}]})],check=True,timeout=4)
                        messages,err=receiver.communicate(timeout=7)
                        self.assertEqual(receiver.returncode,0,err)
                        for line in messages.splitlines():
                            topic,body=line.split(' ',1);bridge.ingest(topic,body)
                        emp=live.live_employees(force=True)[0]
                        self.assertEqual(emp['gw'],'gw-a');self.assertEqual(emp['zone'],'A')
                        self.assertEqual(emp['location']['x'],.2)
                        self.assertEqual(live.save_employee_monitoring({'mac':MAC,'actor':ACTOR,'scan_paused':True}),(True,''))
                        emp=live.live_employees(force=True)[0]
                        self.assertFalse(emp['present']);self.assertTrue(emp['scan_paused'])
                        self.assertIsNone(emp['location'])
                        self.assertEqual(bridge.employee_scan_policy()['active_macs'],[])
                        self.assertEqual(live.save_employee_monitoring({'mac':MAC,'actor':ACTOR,'scan_paused':False}),(True,''))
                        self.assertFalse(live.live_employees(force=True)[0]['present'])
                        bridge._db.close();bridge._db=None
                        self.assertEqual(live.monitoring_settings()['health_interval_s'],900)
                        employee=live.live_employees(force=True)[0]
                        self.assertEqual(employee['name'],'Integration Fixture')
                        self.assertEqual(employee['weekly_schedule'],schedule)
                        # Synthetic wearable boundary, real MQTT transport both directions.
                        bridge.ingest('roztash/gw-a/status',json.dumps({'online':True,
                            'scan_policy_ready':True,'vibration_request_id':True,'fw':'0.5.2-alerts'}))
                        bridge.ingest('roztash/gw-a/presence',json.dumps({'bands':[
                            {'mac':MAC,'rssi':-42,'age_ms':0}]}))
                        bridge.ingest('roztash/gw-a/vitals',json.dumps({'mac':MAC,'battery':12}))
                        alert=live.live_status(force=True)['battery_alerts'][0]
                        self.assertEqual(alert['vibration_status'],'pending')
                        command_sub=subprocess.Popen(['mosquitto_sub','-h','127.0.0.1','-p',str(mqtt_port),
                            '-t','roztash/gw-a/cmd','-C','1','-W','5','-F','%r %p'],
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        self.addCleanup(self.stop_process,command_sub)
                        time.sleep(.15)
                        bridge.dispatch_battery_alerts()
                        command_output,err=command_sub.communicate(timeout=7)
                        self.assertEqual(command_sub.returncode,0,err)
                        retained,raw=command_output.strip().split(' ',1)
                        self.assertEqual(retained,'0')
                        command=json.loads(raw)
                        self.assertEqual(command['mac'],MAC)
                        self.assertEqual(command['reason'],'battery_low')
                        self.assertEqual(live.live_status(force=True)['battery_alerts'][0]['vibration_status'],'awaiting_ack')
                        ack_sub=subprocess.Popen(['mosquitto_sub','-h','127.0.0.1','-p',str(mqtt_port),
                            '-t','roztash/gw-a/event','-C','1','-W','5','-F','%t %p'],
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        self.addCleanup(self.stop_process,ack_sub)
                        time.sleep(.15)
                        ack={'type':'vibrated','mac':MAC,'request_id':command['request_id'],'reason':'battery_low'}
                        subprocess.run(['mosquitto_pub','-h','127.0.0.1','-p',str(mqtt_port),
                            '-t','roztash/gw-a/event','-m',json.dumps(ack)],check=True,timeout=4)
                        ack_output,err=ack_sub.communicate(timeout=7)
                        self.assertEqual(ack_sub.returncode,0,err)
                        topic,body=ack_output.strip().split(' ',1);bridge.ingest(topic,body)
                        self.assertEqual(live.live_status(force=True)['battery_alerts'][0]['vibration_status'],'confirmed')
                        print('LOOPBACK_INTEGRATION_PASS: HTTP, MQTT policies, location, pause, restart, battery command and synthetic ACK')
                finally:
                    server.shutdown();server.server_close();serving.join(2)
                    if bridge._db is not None:
                        bridge._db.close();bridge._db=None
            self.stop_process(broker)

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


if __name__=='__main__':
    unittest.main()
