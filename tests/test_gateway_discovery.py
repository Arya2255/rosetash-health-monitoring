"""Gateway discovery checks. UDP traffic stays on IPv4 loopback."""

import asyncio
import json
import socket
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools import gateway_discovery as discovery  # noqa: E402
import views.gateways as gateways_ui  # noqa: E402
import msgpack  # noqa: E402
from flet.controls.base_control import BaseControl  # noqa: E402
from flet.messaging.connection import Connection  # noqa: E402
from flet.messaging.protocol import configure_encode_object_for_msgpack  # noqa: E402
from flet.messaging.session import Session  # noqa: E402
from flet.pubsub.pubsub_hub import PubSubHub  # noqa: E402

_QUERY = b"ROZTASH_GATEWAY_DISCOVERYWHO_IS_THERE"
_REPLY = b"ROZTASH_GATEWAY_DISCOVERYGATEWAY_HERE"
_DEVICE = {
    "v": 1,
    "gw": "gw-lab-1",
    "mac": "02:ab:cd:30:40:51",
    "fw": "0.1.5",
    "ip": "127.0.0.1",
    "transport": "ethernet",
    "mqtt_connected": False,
}


def _packet(**fields):
    return _REPLY + json.dumps(dict(_DEVICE, **fields)).encode("utf-8")


class GatewayDiscoveryTests(unittest.TestCase):
    def _loopback_scan(self, *replies):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as responder, \
                ThreadPoolExecutor(max_workers=1) as worker:
            responder.bind(("127.0.0.1", 0))
            responder.settimeout(1)

            def reply():
                query, peer = responder.recvfrom(1024)
                for packet in replies:
                    responder.sendto(packet, peer)
                return query

            received = worker.submit(reply)
            rows = discovery.discover_gateways(timeout_s=0.2, targets=[responder.getsockname()])
            self.assertEqual(received.result(timeout=1), _QUERY)
        return rows

    def test_loopback_finds_device_even_without_mqtt(self):
        self.assertEqual(self._loopback_scan(_packet()), [_DEVICE])

    def test_loopback_peer_address_is_authoritative_and_mac_is_canonical(self):
        expected = dict(_DEVICE, ip="127.0.0.1", mac=_DEVICE["mac"])
        self.assertEqual(self._loopback_scan(
            _packet(ip="192.0.2.123", mac=_DEVICE["mac"].upper())), [expected])

    def test_rejects_invalid_version_identity_address_transport_and_oversize(self):
        malformed = [
            _REPLY + b"{",
            _REPLY + b"[]",
            _REPLY + b"null",
            _REPLY + b"\xff",
            _packet(v=True),
            _packet(v=2),
            _packet(v=1.0),
            _packet(gw="GW-lab-1"),
            _packet(gw=" gw-lab-1"),
            _packet(gw="gw/lab/1"),
            _packet(gw="a" * 24),
            _packet(mac="not-a-mac"),
            _packet(fw=""),
            _packet(ip="not-an-ip"),
            _packet(ip="::1"),
            _packet(transport="wifi"),
            _packet(mqtt_connected=1),
            _packet() + b" " * 600,
        ]
        self.assertEqual(self._loopback_scan(*malformed), [])

    def test_deduplicates_same_identity_and_rejects_conflicting_macs(self):
        other_mac = "02:10:20:30:40:52"
        self.assertEqual(self._loopback_scan(
            _packet(), _packet(), _packet(mac=other_mac), _packet(),
            _packet(mac=other_mac), _packet()), [])

    def test_duplicate_replies_return_one_device(self):
        self.assertEqual(self._loopback_scan(_packet(), _packet()), [_DEVICE])

    def test_reported_mqtt_connection_never_creates_online_or_registry_status(self):
        rows = self._loopback_scan(_packet(mqtt_connected=True, online=True,
                                          registered=True, password="test-only-secret"))
        self.assertEqual(rows, [dict(_DEVICE, mqtt_connected=True)])

    def test_same_mac_claiming_different_gateway_ids_is_rejected(self):
        self.assertEqual(self._loopback_scan(
            _packet(), _packet(gw="gw-other"), _packet(), _packet(gw="gw-other")), [])

    def test_failed_adapter_does_not_abort_real_loopback_round_trip(self):
        real_socket = socket.socket
        attempts = []

        class StaleAdapterSocket(real_socket):
            def bind(self, address):
                raise OSError("synthetic stale adapter")

        def fail_first_client_socket(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                return StaleAdapterSocket(*args, **kwargs)
            return real_socket(*args, **kwargs)

        with real_socket(socket.AF_INET, socket.SOCK_DGRAM) as responder, \
                ThreadPoolExecutor(max_workers=1) as worker:
            responder.bind(("127.0.0.1", 0))
            responder.settimeout(1)

            def reply():
                query, peer = responder.recvfrom(1024)
                responder.sendto(_packet(), peer)
                return query

            received = worker.submit(reply)
            with patch.object(discovery.socket, "socket", side_effect=fail_first_client_socket):
                rows = discovery.discover_gateways(timeout_s=0.2,
                    targets=[("127.0.0.1", 1), responder.getsockname()])
            self.assertEqual(received.result(timeout=1), _QUERY)
            self.assertEqual(rows, [_DEVICE])

    def test_all_socket_setup_failures_report_error_instead_of_no_replies(self):
        with patch.object(discovery.socket, "socket", side_effect=OSError("adapter failure")):
            with self.assertRaises(OSError):
                discovery.discover_gateways(timeout_s=0.05, targets=[("127.0.0.1", 1)])

    def test_ignores_invalid_reply_prefix(self):
        self.assertEqual(self._loopback_scan(b"INVALID" + _packet()), [])

    def test_targets_broadcast_each_valid_non_loopback_interface_and_global(self):
        self.assertEqual(discovery._broadcast_targets([{
            "ip": "10.23.20.4", "prefix": "20", "iface": "ethernet-test"}, {
            "ip": "127.0.0.1", "prefix": "8", "iface": "loopback-test"}, {
            "ip": "bad", "prefix": "24", "iface": "invalid-test"}]), [
                ("10.23.31.255", 19199, "10.23.20.4", "ethernet-test"),
                ("255.255.255.255", 19199, None, ""),
            ])

    def test_zero_timeout_does_not_send(self):
        self.assertEqual(discovery.discover_gateways(timeout_s=0, targets=[("127.0.0.1", 1)]), [])
        for timeout in (-0.01, float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                discovery.discover_gateways(timeout_s=timeout)

    def test_silent_loopback_responder_respects_deadline(self):
        import time
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as silent:
            silent.bind(("127.0.0.1", 0))
            started = time.monotonic()
            rows = discovery.discover_gateways(timeout_s=0.06, targets=[silent.getsockname()])
            elapsed = time.monotonic() - started
            silent.settimeout(0.2)
            self.assertEqual(silent.recvfrom(1024)[0], _QUERY)
        self.assertEqual(rows, [])
        self.assertLess(elapsed, 0.5)

    def test_non_ipv4_and_empty_explicit_targets_never_fall_back_to_broadcast(self):
        with patch.object(discovery.socket, "socket") as create:
            for targets in ([], [("::1", 19199)], [("localhost", 19199)]):
                self.assertEqual(discovery.discover_gateways(targets=targets), [])
            create.assert_not_called()


class _GatewayUiPage:
    def __init__(self):
        self.tasks = []
        self.updates = 0
        self.dialogs = []

    def run_task(self, handler):
        import asyncio
        task = asyncio.create_task(handler())
        self.tasks.append(task)
        return task

    def update(self):
        self.updates += 1

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        if self.dialogs:
            return self.dialogs.pop()


class _GatewayUiApp:
    def __init__(self, role="owner", live=True):
        self.state = {"view": "gateways", "logged_in": True, "role": role,
                      "admin_email": "manager@example.test"}
        self.page = _GatewayUiPage()
        self.live = live
        self.rendered = 0
        self.snacks = []

    def render(self):
        self.rendered += 1

    def snack(self, message):
        self.snacks.append(message)


def _walk_text(root):
    values = []
    for control in _controls(root):
        for field in ("value", "content"):
            value = getattr(control, field, None)
            if isinstance(value, str):
                values.append(value)
    return "\n".join(values)


def _controls(root):
    found = [root]
    content = getattr(root, "content", None)
    if content is not None and not isinstance(content, str):
        found.extend(_controls(content))
    for child in getattr(root, "controls", None) or ():
        found.extend(_controls(child))
    return found


def _button(root, data):
    return next(control for control in _controls(root)
                if getattr(control, "data", None) == data)


def _controls_text(root):
    values = []
    for control in _controls(root):
        value = getattr(control, "value", None)
        if isinstance(value, str):
            values.append(value.replace("\u200c", ""))
    return "\n".join(values)


class GatewayUiDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_search_result_keeps_registry_and_heartbeat_status(self):
        import data
        app = _GatewayUiApp()
        found = dict(_DEVICE, ip="10.2.3.4", mqtt_connected=True)
        registered = dict(found, registered=True, kind="installed",
                          label="Registered test", online=False, live=False)
        with patch.object(data, "discover_gateways", return_value=(True, [found])), \
                patch.object(gateways_ui, "live_gateways",
                             side_effect=[[registered], [registered]]) as live:
            page = gateways_ui.gateways_view(app)
            await _button(page, "gateway:discover").on_click(None)
            self.assertEqual(live.call_args.kwargs, {"force": True})
            results = _button(page, "gateway:discovery-results")
            self.assertNotIn("کشفشده", _controls_text(results))
            self.assertIn("نصبشده", _controls_text(results))
            self.assertIn("بروکر MQTT متصل", _controls_text(results))
            self.assertNotIn("آنلاین", _controls_text(results))
            self.assertFalse(any(getattr(c, "data", None) == "gateway:define:" + found["gw"]
                                 for c in _controls(results)))

    async def test_bridge_absence_does_not_show_sample_gateways(self):
        import data
        app = _GatewayUiApp()
        with patch.object(gateways_ui, "live_gateways", return_value=None):
            page = gateways_ui.gateways_view(app)
        self.assertIn("پل محلی در دسترس نیست", _controls_text(page))
        for sample in data.MAP_GATEWAYS:
            for field in ("gw", "label"):
                if sample.get(field):
                    self.assertNotIn(str(sample[field]).replace("\u200c", ""),
                                     _controls_text(page))

    async def test_only_authenticated_gateway_manager_can_discover_when_bridge_up(self):
        sys.path.insert(0, str(ROOT / "src"))
        import views.gateways as gateways_ui
        for role, logged_in, live, enabled in (
                ("owner", True, True, True), ("viewer", True, True, False),
                ("owner", False, True, False), ("owner", True, False, False)):
            with self.subTest(role=role, logged_in=logged_in, live=live):
                app = _GatewayUiApp(role=role, live=live)
                app.state["logged_in"] = logged_in
                with patch.object(gateways_ui, "live_gateways",
                                  return_value=[] if live else None):
                    page = gateways_ui.gateways_view(app)
                button = _button(page, "gateway:discover")
                self.assertEqual(button.visible, enabled)
                self.assertEqual(button.disabled, not enabled)

    async def test_repeated_clicks_send_one_search_and_report_rejection(self):
        sys.path.insert(0, str(ROOT / "src"))
        import data
        import views.gateways as gateways_ui
        app = _GatewayUiApp()
        response = threading.Event()
        entered = threading.Event()
        calls = []

        def blocked_search(*, actor):
            calls.append(actor)
            entered.set()
            if not response.wait(2):
                raise TimeoutError("test did not unblock fake discovery")
            return False, "network discovery failed"

        with patch.object(data, "discover_gateways", side_effect=blocked_search,
                          create=True), patch.object(gateways_ui, "live_gateways",
                                                    return_value=[]):
            page = gateways_ui.gateways_view(app)
            button = _button(page, "gateway:discover")
            app.page.tasks.append(asyncio.create_task(button.on_click(None)))
            app.page.tasks.append(asyncio.create_task(button.on_click(None)))
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            self.assertTrue(button.disabled)
            self.assertEqual(calls, ["manager@example.test"])
            response.set()
            await asyncio.gather(*app.page.tasks)
            self.assertEqual(app.rendered, 0)
            self.assertEqual(button.content, "جستجوی گیت‌وی در شبکه")
            self.assertIn("network discovery failed", _controls_text(page))

    async def test_stale_completion_does_not_update_replaced_view(self):
        sys.path.insert(0, str(ROOT / "src"))
        import data
        import views.gateways as gateways_ui
        app = _GatewayUiApp()
        response = threading.Event()
        entered = threading.Event()

        def blocked_search(*, actor):
            entered.set()
            if not response.wait(2):
                raise TimeoutError("test did not unblock fake discovery")
            return True, [{"gw": "gw-test-8", "ip": "10.2.3.4",
                           "fw": "fw-8", "mac": "02:10:20:30:40:58",
                           "transport": "ethernet", "mqtt_connected": False}]

        with patch.object(data, "discover_gateways", side_effect=blocked_search,
                          create=True), patch.object(gateways_ui, "live_gateways",
                                                    return_value=[]):
            page = gateways_ui.gateways_view(app)
            app.page.tasks.append(asyncio.create_task(
                _button(page, "gateway:discover").on_click(None)))
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            app.state["view"] = "map"
            response.set()
            await asyncio.gather(*app.page.tasks)
            self.assertEqual(app.rendered, 0)
            self.assertEqual(app.page.updates, 1)

    async def test_search_counts_only_this_result_and_define_requires_confirmation(self):
        sys.path.insert(0, str(ROOT / "src"))
        import data
        import views.gateways as gateways_ui
        from components import gateway_form

        found = {"gw": "gw-test-8", "ip": "10.2.3.4", "fw": "fw-8",
                 "mac": "02:10:20:30:40:58", "transport": "ethernet",
                 "mqtt_connected": False}
        live_rows = [dict(found, registered=False, network_seen=False,
                          network_ip=None, network_mac=None,
                          network_mqtt_connected=None, online=False, live=False)]
        app = _GatewayUiApp()
        app.page.show_dialog = lambda dialog: app.page.dialogs.append(dialog)
        searches = []
        form_opened = []

        with patch.object(data, "discover_gateways",
                          side_effect=lambda *, actor: (searches.append(actor) or
                                                        (True, [found])), create=True), \
                patch.object(gateways_ui, "live_gateways", side_effect=[[], live_rows]), \
                patch.object(gateways_ui, "open_gateway_form",
                             side_effect=lambda *args, **kwargs:
                             form_opened.append((args, kwargs))):
            page = gateways_ui.gateways_view(app)
            search = _button(page, "gateway:discover")
            app.page.tasks.append(asyncio.create_task(search.on_click(None)))
            await asyncio.gather(*app.page.tasks)
            self.assertEqual(searches, ["manager@example.test"])
            self.assertIn("۱ گیتوی در شبکه دیده شد", _controls_text(page))
            self.assertEqual(_controls_text(page).count("گیتوی در شبکه دیده شد"), 1)
            self.assertIn("بروکر MQTT جدا", _controls_text(page))

            define = _button(page, "gateway:define:gw-test-8")
            define.on_click(None)
            self.assertTrue(app.page.dialogs)
            self.assertFalse(form_opened, "a discovery sighting must not register itself")
            dialog = app.page.dialogs[-1]
            self.assertIn("10.2.3.4", _walk_text(dialog))
            self.assertIn("fw-8", _walk_text(dialog))
            dialog.actions[1].on_click(None)
            self.assertEqual(len(form_opened), 1)

    async def test_empty_search_does_not_count_preexisting_network_sightings(self):
        sys.path.insert(0, str(ROOT / "src"))
        import data
        import views.gateways as gateways_ui
        app = _GatewayUiApp()
        prior = [{"gw": "gw-old", "network_seen": True, "registered": False}]
        with patch.object(data, "discover_gateways", return_value=(True, []),
                          create=True), patch.object(gateways_ui, "live_gateways",
                                                     side_effect=[prior, prior]):
            page = gateways_ui.gateways_view(app)
            app.page.tasks.append(asyncio.create_task(
                _button(page, "gateway:discover").on_click(None)))
            await asyncio.gather(*app.page.tasks)
            self.assertIn("در این جستجو گیتویای پاسخ نداد", _controls_text(page))


class _MemoryConnection(Connection):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.pubsubhub = PubSubHub(loop, self.executor)
        self.messages = []

    def encode(self, message):
        return msgpack.packb(message, default=configure_encode_object_for_msgpack(BaseControl))

    def send_message(self, message):
        self.messages.append(self.encode(message))


class MountedGatewayDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unmounted_or_replaced_view_ignores_late_discovery_result(self):
        import data
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                connection = _MemoryConnection(asyncio.get_running_loop())
                session = Session(connection)
                connection.encode(session.get_page_patch())
                app = _GatewayUiApp()
                app.page = session.page
                released, entered = threading.Event(), threading.Event()

                def blocked_search(*, actor):
                    entered.set()
                    if not released.wait(2):
                        raise TimeoutError("test did not release discovery")
                    return True, [dict(_DEVICE)]

                try:
                    with patch.object(data, "discover_gateways", side_effect=blocked_search), \
                            patch.object(gateways_ui, "live_gateways", return_value=[]) as live:
                        root = gateways_ui.gateways_view(app)
                        app.page.add(root)
                        button = _button(root, "gateway:discover")
                        task = asyncio.create_task(session.dispatch_event(button._i, "click", None))
                        self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                        self.assertTrue(root._gateway_mounted)
                        next_root = gateways_ui.gateways_view(app) if replacement else None
                        app.page.controls = [next_root] if next_root else []
                        app.page.update()
                        self.assertTrue(root._gateway_disposed)
                        released.set()
                        await asyncio.wait_for(task, 2)
                        self.assertFalse(any(call.kwargs.get("force") for call in live.call_args_list))
                        if replacement:
                            self.assertFalse(_button(next_root, "gateway:discover").disabled)
                            self.assertFalse(_button(next_root, "gateway:discovery-status").visible)
                finally:
                    released.set()
                    connection.executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
