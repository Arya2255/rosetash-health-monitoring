"""Employee deletion, band release and personnel categories on a disposable DB."""
import http.client
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_location_policy import ACTOR, MAC, NOW, IsolatedBridge, bridge
from bridge_auth import sign_request


class EmployeeLifecycleTests(IsolatedBridge):
    def test_delete_preserves_band_and_moves_it_to_inactive_after_restart(self):
        self.employee()
        self.assertEqual(bridge.remove_employee(MAC), (True, ''))
        self.assertEqual(bridge.employees_list(), [])
        self.close_db()
        bands = bridge.snapshot(NOW)['bands_known']
        self.assertEqual(len(bands), 1)
        self.assertEqual(bands[0]['mac'], MAC)
        self.assertIsNone(bands[0]['employee_name'])
        self.assertEqual(bands[0]['assignment_status'], 'inactive')
        self.assertFalse(bands[0]['monitoring_active'])

    def test_delete_retains_label_and_revokes_monitoring_even_if_seen_again(self):
        self.employee()
        bridge.upsert_band({'mac': MAC, 'label': 'Band label', 'note': 'Keep note'})
        self.gateway('gw-a', .2, .3)
        self.presence('gw-a', -40)
        self.assertIn(MAC, bridge.employee_scan_policy(NOW)['active_macs'])
        bridge._scan_policy_wake.clear()
        self.assertEqual(bridge.remove_employee(MAC), (True, ''))
        self.assertTrue(bridge._scan_policy_wake.is_set())
        self.presence('gw-a', -35, NOW+1)
        snap = bridge.snapshot(NOW+2)
        self.assertEqual(snap['employees'], [])
        self.assertEqual(snap['bands'], [])
        self.assertNotIn(MAC, bridge.employee_scan_policy(NOW+2)['active_macs'])
        band = snap['bands_known'][0]
        self.assertEqual((band['label'], band['note']), ('Band label', 'Keep note'))
        self.assertEqual(band['assignment_status'], 'inactive')

    def test_reassign_inactive_band_reactivates_without_old_employee_telemetry(self):
        self.employee()
        self.gateway('gw-a', .2, .3)
        self.presence('gw-a', -40)
        bridge.ingest('roztash/gw-a/health', json.dumps({'mac': MAC, 'state': 'done',
                      'fail': 'none', 'avg': 90, 'n': 1, 'bpm': [90]}), NOW)
        bridge.remove_employee(MAC)
        with patch.object(bridge.time, 'time', return_value=NOW+5):
            bridge.upsert_employee({'mac': MAC, 'name': 'New employee', 'staff_group': 'hse'})
            bridge.set_employee_monitoring({'mac': MAC, 'actor': ACTOR,
                                             'weekly_schedule': {'mon': [{'start':'08:00','end':'16:00'}]}})
        snap = bridge.snapshot(NOW+6)
        self.assertEqual(snap['bands_known'][0]['assignment_status'], 'active')
        self.assertEqual(snap['bands_known'][0]['employee_name'], 'New employee')
        self.assertEqual(snap['employees'][0]['staff_group'], 'hse')
        self.assertIsNone(snap['employees'][0]['health'])
        self.assertFalse(snap['employees'][0]['present'])

    def test_staff_groups_persist_and_partial_updates_preserve_them(self):
        for group in ('employee', 'hse', 'supervisor', 'shift_leader'):
            self.assertEqual(bridge.upsert_employee({'mac': MAC, 'name':'Person', 'staff_group':group}), (True,''))
            bridge.upsert_employee({'mac':MAC,'dept':'Unit'})
            self.assertEqual(bridge.employees_list()[0]['staff_group'],group)
            self.assertEqual(bridge.snapshot(NOW)['employees'][0]['staff_group'],group)
            self.close_db()
        before = bridge.employees_list()[0]
        self.assertEqual(bridge.upsert_employee({'mac':MAC,'staff_group':'owner'}), (False,'invalid staff group'))
        self.assertEqual(bridge.employees_list()[0],before)

    def test_delete_missing_record_does_not_create_band(self):
        self.assertEqual(bridge.remove_employee(MAC), (False,'not found'))
        self.assertEqual(bridge.bands_list(),[])


class EmployeeDeletionHTTPTests(IsolatedBridge):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ,{'ROZTASH_BRIDGE_AUTH_FILE':str(Path(bridge.DB_PATH).with_suffix('.key'))}))
        self.server=bridge.Server(('127.0.0.1',0),bridge.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def delete(self,path,actor=None):
        headers=sign_request('DELETE',path,b'',actor) if actor else {}
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        try:
            conn.request('DELETE',path,headers=headers)
            response=conn.getresponse()
            return response.status,json.loads(response.read())
        finally:conn.close()

    def test_all_admin_roles_can_delete_but_unsigned_and_unknown_users_cannot(self):
        for role in ('owner','viewer'):
            for path in ('/api/employees?mac='+MAC, '/api/employees/'+MAC):
                with self.subTest(role=role,path=path):
                    self.employee()
                    self.assertEqual(self.delete(path)[0],401)
                    self.assertEqual(self.delete(path,'unknown@example.test')[0],403)
                    self.assertEqual(len(bridge.employees_list()),1)
                    with patch.object(bridge,'get_role',side_effect=lambda a:role if a==ACTOR else ''):
                        code,doc=self.delete(path,ACTOR)
                    self.assertEqual((code,doc['ok']),(200,True))
                    self.assertEqual(bridge.employees_list(),[])


if __name__=='__main__':unittest.main()
