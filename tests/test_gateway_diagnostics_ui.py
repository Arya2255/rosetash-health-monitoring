"""Gateway diagnostic UI: explicit selection, polling and stale-view protection."""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import components.gateway_diagnostics as diagnostics


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from walk(content)
    for child in getattr(control, "controls", None) or []:
        yield from walk(child)


def find_data(control, prefix):
    return [item for item in walk(control) if str(getattr(item, "data", "") or "").startswith(prefix)]


def text(control):
    return "\n".join(str(getattr(item, "value", "")) for item in walk(control))


class Page:
    def __init__(self):
        self.updates = 0
    def update(self):
        self.updates += 1


class App:
    def __init__(self):
        self.page = Page()
        self.state = {"admin_email": "owner@example.test", "role": "owner", "logged_in": True}


ROWS = [{"gw": "gw-a", "label": "Gateway A", "registered": True, "online": False}]
MAC = "aa:bb:cc:dd:ee:01"


class DiagnosticUITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = App()
        self.current = True

    def card(self):
        return diagnostics.gateway_diagnostics_card(self.app, ROWS, lambda: self.current)

    async def test_scan_lists_devices_and_probe_returns_real_connection_result(self):
        responses = [
            (True, {"request_id": "diag-" + "1" * 32, "status": "pending", "devices": []}),
            (True, {"request_id": "diag-" + "1" * 32, "status": "done", "devices": [{"mac": MAC, "rssi": -70}]}),
            (True, {"request_id": "diag-" + "2" * 32, "status": "pending", "devices": []}),
            (True, {"request_id": "diag-" + "2" * 32, "status": "done", "mac": MAC, "connected": True, "battery": 90, "devices": []}),
        ]
        calls = []
        def request(**kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]
        with patch.object(diagnostics.gateway_data, "gateway_diagnostic", side_effect=request), \
                patch.object(diagnostics.asyncio, "sleep", new=AsyncMock()):
            card = self.card()
            scan = find_data(card, "gateway:diagnostic-scan")[0]
            await scan.on_click(None)
            probe = find_data(card, "gateway:diagnostic-probe:" + MAC)[0]
            await probe.on_click(None)
        self.assertEqual(calls[0]["action"], "scan")
        self.assertEqual(calls[0]["gw"], "gw-a")
        self.assertEqual(calls[1]["action"], "status")
        self.assertEqual(calls[2]["action"], "probe")
        self.assertEqual(calls[2]["mac"], MAC)
        self.assertIn("اتصال موفق", text(card))
        self.assertIn("۹۰", text(card))
        self.assertFalse(scan.disabled)

    async def test_empty_scan_is_not_reported_as_a_connection(self):
        responses = [
            (True, {"request_id": "diag-" + "1" * 32, "status": "pending"}),
            (True, {"request_id": "diag-" + "1" * 32, "status": "done", "devices": []}),
        ]
        with patch.object(diagnostics.gateway_data, "gateway_diagnostic", side_effect=responses), \
                patch.object(diagnostics.asyncio, "sleep", new=AsyncMock()):
            card = self.card()
            await find_data(card, "gateway:diagnostic-scan")[0].on_click(None)
        self.assertIn("مچ‌بندی", text(card))
        self.assertNotIn("اتصال موفق", text(card))
        self.assertFalse(find_data(card, "gateway:diagnostic-probe:"))

    async def test_duplicate_click_and_late_result_cannot_touch_disposed_view(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []
        async def slow_request(**kwargs):
            calls.append(kwargs)
            started.set()
            await release.wait()
            return True, {"request_id": "diag-" + "1" * 32, "status": "done", "devices": []}
        async def immediate_request(**kwargs):
            calls.append(kwargs)
            started.set()
            return True, {"request_id": "diag-" + "1" * 32, "status": "done", "devices": []}
        # asyncio.to_thread requires a synchronous callable; block a real worker thread.
        import threading
        thread_started = threading.Event()
        thread_release = threading.Event()
        def request(**kwargs):
            calls.append(kwargs)
            thread_started.set()
            thread_release.wait(2)
            return True, {"request_id": "diag-" + "1" * 32, "status": "done", "devices": []}
        with patch.object(diagnostics.gateway_data, "gateway_diagnostic", side_effect=request):
            card = self.card()
            button = find_data(card, "gateway:diagnostic-scan")[0]
            first = asyncio.create_task(button.on_click(None))
            await asyncio.to_thread(thread_started.wait, 1)
            await button.on_click(None)
            self.assertEqual(len(calls), 1)
            before = self.app.page.updates
            self.current = False
            thread_release.set()
            await asyncio.wait_for(first, 2)
        self.assertEqual(self.app.page.updates, before)

    async def test_owner_role_is_checked_again_before_request(self):
        self.app.state["role"] = "viewer"
        with patch.object(diagnostics.gateway_data, "gateway_diagnostic") as request:
            card = self.card()
            buttons = find_data(card, "gateway:diagnostic-scan")
            self.assertFalse(buttons)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
