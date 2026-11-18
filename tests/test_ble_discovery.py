"""Host BLE parsing and owner authorization; radios use explicit test doubles."""
import asyncio
import http.client
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'backend'), str(ROOT / 'tests')]
import ble_discovery as ble
from bridge_auth import sign_request
from test_location_policy import ACTOR, IsolatedBridge, bridge

MAC = 'aa:bb:cc:dd:ee:01'


class BleDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_results_are_deduplicated_and_sorted_by_signal(self):
        advertisements = {
            'first': (SimpleNamespace(address=MAC.upper(), name=None),
                      SimpleNamespace(local_name='Band A', rssi=-75)),
            'repeat': (SimpleNamespace(address=MAC, name='ignored'),
                       SimpleNamespace(local_name=None, rssi=-64)),
            'second': (SimpleNamespace(address='AA:BB:CC:DD:EE:02', name=None),
                       SimpleNamespace(local_name=None, rssi=-83)),
            'bad': (SimpleNamespace(address='not-a-mac', name='Ignore'),
                    SimpleNamespace(local_name='Ignore', rssi=-22)),
        }
        discover = AsyncMock(return_value=advertisements)
        with patch.dict(sys.modules, {'bleak': SimpleNamespace(BleakScanner=SimpleNamespace(discover=discover))}):
            rows = await ble.discover_nearby(timeout_s=100)
        self.assertEqual([r['mac'] for r in rows], [MAC, 'aa:bb:cc:dd:ee:02'])
        self.assertEqual((rows[0]['name'], rows[0]['rssi']), ('Band A', -64))
        self.assertEqual(rows[1]['name'], 'بدون نام')
        discover.assert_awaited_once()
        self.assertTrue(discover.await_args.kwargs['return_adv'])
        self.assertLessEqual(discover.await_args.kwargs['timeout'], 12)

    async def test_active_scan_collects_scan_response_names_without_connecting(self):
        discover = AsyncMock(return_value={})
        scanner = SimpleNamespace(discover=discover)
        with patch.dict(sys.modules, {'bleak': SimpleNamespace(BleakScanner=scanner)}):
            await ble.discover_nearby()
        self.assertEqual(discover.await_args.kwargs['scanning_mode'], 'active')

    async def test_explicit_passive_mode_and_linux_adapter_are_preserved(self):
        discover = AsyncMock(return_value={})
        with patch.dict(sys.modules, {'bleak': SimpleNamespace(BleakScanner=SimpleNamespace(discover=discover))}), \
                patch.dict(os.environ, {'ROZTASH_BLE_ADAPTER': 'hci-test'}), \
                patch.object(ble.sys, 'platform', 'linux'):
            await ble.discover_nearby(timeout_s=0, passive=True)
        self.assertEqual(discover.await_args.kwargs['scanning_mode'], 'passive')
        self.assertEqual(discover.await_args.kwargs['timeout'], 2)
        self.assertEqual(discover.await_args.kwargs['bluez'], {'adapter': 'hci-test'})

    async def test_missing_package_reports_installation_error(self):
        with patch.dict(sys.modules, {'bleak': None}):
            with self.assertRaisesRegex(RuntimeError, 'نصب نشده'):
                await ble.discover_nearby()

    async def test_no_controller_reports_actionable_error(self):
        discover = AsyncMock(side_effect=RuntimeError('adapter unavailable'))
        with patch.dict(sys.modules, {'bleak': SimpleNamespace(BleakScanner=SimpleNamespace(discover=discover))}):
            with self.assertRaisesRegex(RuntimeError, 'بلوتوث'):
                await ble.discover_nearby()


class BleAuthorizationTests(IsolatedBridge):
    def test_only_owner_is_allowed_and_denied_calls_never_start_radio(self):
        for actor, role in (('', 'owner'), (ACTOR, 'viewer'), (ACTOR, ''), ('unknown@example.test', '')):
            with self.subTest(actor=actor, role=role), \
                    patch.object(bridge, 'get_role', return_value=role), \
                    patch.object(ble, 'discover_nearby', new_callable=AsyncMock) as scan:
                with self.assertRaises(PermissionError):
                    bridge.discover_bands_for_admin(actor)
                scan.assert_not_awaited()

    def test_busy_scan_does_not_start_another_radio_scan(self):
        with patch.object(bridge, 'get_role', return_value='owner'), \
                patch.object(ble, 'discover_nearby', new_callable=AsyncMock) as scan:
            bridge._ble_discovery_lock.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, 'در حال اجراست'):
                    bridge.discover_bands_for_admin(ACTOR)
            finally:
                bridge._ble_discovery_lock.release()
            scan.assert_not_awaited()

    def test_failed_scan_releases_lock_for_retry(self):
        with patch.object(bridge, 'get_role', return_value='owner'), \
                patch.object(ble, 'discover_nearby', new_callable=AsyncMock,
                             side_effect=[RuntimeError('radio off'), []]):
            with self.assertRaises(RuntimeError):
                bridge.discover_bands_for_admin(ACTOR)
            self.assertEqual(bridge.discover_bands_for_admin(ACTOR), [])

    def test_http_signature_permissions_errors_and_no_automatic_registration(self):
        self.enterContext(patch.dict(os.environ, {
            'ROZTASH_BRIDGE_AUTH_FILE': str(Path(bridge.DB_PATH).with_suffix('.key'))}))
        server = bridge.Server(('127.0.0.1', 0), bridge.Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def request(actor=None):
            path = '/api/bands/scan'
            headers = sign_request('GET', path, b'', actor) if actor else {}
            conn = http.client.HTTPConnection(*server.server_address, timeout=5)
            try:
                conn.request('GET', path, headers=headers)
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        try:
            with patch.object(ble, 'discover_nearby', new_callable=AsyncMock,
                              return_value=[{'mac': MAC, 'name': 'Synthetic band', 'rssi': -50}]) as scan:
                self.assertEqual(request()[0], 401)
                self.assertEqual(request(ACTOR)[0], 403)
                scan.assert_not_awaited()
                with patch.object(bridge, 'get_role', return_value='owner'):
                    code, doc = request(ACTOR)
                self.assertEqual((code, doc['ok']), (200, True))
                self.assertEqual(doc['devices'][0]['mac'], MAC)
                scan.assert_awaited_once()
                self.assertEqual(bridge.bands_list(), [])
                self.assertEqual(bridge.employees_list(), [])
            with patch.object(bridge, 'get_role', return_value='owner'), \
                    patch.object(ble, 'discover_nearby', new_callable=AsyncMock, side_effect=RuntimeError('radio off')):
                code, doc = request(ACTOR)
                self.assertEqual((code, doc['ok'], doc['error']), (503, False, 'radio off'))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == '__main__':
    unittest.main()
