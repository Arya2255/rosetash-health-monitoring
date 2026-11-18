"""Real UI controls with synthetic bridge snapshots; no network or hardware."""
import asyncio
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft
import views.dashboard as dashboard
import views.alerts as alerts
import views.employee_detail as employee_detail
import main as app_main

MAC = "aa:bb:cc:dd:ee:01"
EMPLOYEE = {
    "mac": MAC, "registered": True, "name": "کارکن واقعی آزمایشی", "dept": "تولید",
    "status": "ok", "present": True, "last_seen_age_s": 7, "zone": "سالن تست",
    "health": {"state": "done", "n": 3, "avg": 83, "age_s": 8},
    "vitals": {"battery": 0, "spo2": 98}, "issues": [],
}


def walk(control):
    if getattr(control, "visible", True) is False:
        return
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


def text(control):
    return "\n".join(str(getattr(c, "value", None) or getattr(c, "content", ""))
                     for c in walk(control)
                     if isinstance(c, ft.Text) or isinstance(getattr(c, "content", None), str))


def tagged(control, tag):
    return next(c for c in walk(control) if getattr(c, "data", None) == tag)


def fake_app(view="dashboard", width=1340):
    app = SimpleNamespace(state={"view": view, "filter": "all", "search": "",
                                 "logged_in": True, "admin_email": "manager@example.test"},
                          alerts_active=[], alerts_history=[], siren_on=False)
    app.messages, app.navigation, app.tasks = [], [], []
    app.page = SimpleNamespace(width=width, height=800, update=lambda: None,
                               run_task=lambda fn, *args: app.tasks.append((fn, args)))
    app.snack = app.messages.append
    app.go = lambda *args: app.navigation.append(args)
    return app


class DashboardTests(unittest.TestCase):
    def build(self, doc, width=1340):
        app = fake_app(width=width)
        with patch.object(dashboard, "live_status", return_value=doc, create=True), \
                patch.object(dashboard, "live_summary", return_value=None, create=True):
            view = dashboard.dashboard_view(app)
        return app, view

    def test_registered_snapshot_employee_card_uses_real_vitals_and_mac_navigation(self):
        for width in (1340, 390):
            with self.subTest(width=width):
                app, view = self.build({"ok": True, "employees": [EMPLOYEE,
                    {**EMPLOYEE, "registered": False, "name": "UNREGISTERED"}],
                    "alerts_active": []}, width)
                rendered = text(view)
                self.assertIn(EMPLOYEE["name"], rendered)
                self.assertNotIn("UNREGISTERED", rendered)
                self.assertIn("۸۳", rendered)
                self.assertIn("۹۸٪", rendered)
                self.assertIn("۰٪", rendered)
                cards = [c for c in walk(view) if getattr(c, "data", None) == "dashboard:employee"]
                self.assertEqual(len(cards), 1)
                cards[0].on_click(None)
                self.assertEqual(app.navigation, [("employee", MAC)])
                self.assertEqual(app.state["back_to"], "dashboard")

    def test_unavailable_and_empty_bridge_never_show_sample_employees(self):
        for doc, expected in ((None, "پل محلی در دسترس نیست"),
                              ({"ok": True, "employees": []}, "کارکن ثبت‌شده‌ای وجود ندارد")):
            with self.subTest(doc=doc):
                _, view = self.build(doc)
                self.assertIn(expected, text(view))
                self.assertNotIn("سقوط", text(view))
                self.assertEqual([c for c in walk(view)
                                  if getattr(c, "data", None) == "dashboard:employee"], [])

    def test_offline_gateway_warning_survives_zero_employees(self):
        _, view = self.build({"ok": True, "employees": [], "alerts_active": [ALERT],
                             "gateways": [{"gw": "not-installed", "online": False}]})
        self.assertIn("gw-synthetic", tagged(view, "dashboard:gateways").value)
        self.assertNotIn("not-installed", text(view))
        self.assertIn("آفلاین", text(view))


ALERT = {"id": "event-persisted-42", "source": "live", "type": "gateway_offline",
         "severity": "warn", "emp": "gw-synthetic", "gw": "gw-synthetic",
         "dept": "تولید", "location": "سالن تست", "time": "2026-11-18T09:00:00+03:30",
         "status": "open"}


class LiveAlertStateTests(unittest.TestCase):
    def test_startup_has_no_sample_alerts_or_simulated_siren(self):
        app = app_main.App(SimpleNamespace(web=True))
        self.assertEqual(app.alerts_active, [])
        self.assertFalse(app.siren_on)

    def test_refresh_uses_persistent_snapshot_events_and_clears_unavailable_state(self):
        app = app_main.App(SimpleNamespace(web=True))
        app.state["logged_in"] = True
        closed = {**ALERT, "id": "closed-1", "status": "closed"}
        doc = {"ok": True, "alerts_active": [ALERT], "alerts_history": [closed]}
        with patch.object(app_main, "live_status", return_value=doc), \
                patch.object(app_main, "live_employees", side_effect=AssertionError("Do not synthesize alerts")):
            app.refresh_live_alerts()
        self.assertEqual(app.alerts_active, [ALERT])
        self.assertEqual(app.alerts_history, [closed])
        with patch.object(app_main, "live_status", return_value=None):
            app.refresh_live_alerts()
        self.assertEqual(app.alerts_active, [])
        self.assertEqual(app.alerts_history, [])

    def test_acknowledgement_uses_actor_and_reads_back_persisted_state(self):
        app = app_main.App(SimpleNamespace(web=True))
        app.state.update(logged_in=True, admin_email="admin@example.test")
        app.messages = []
        app.snack = lambda message: app.messages.append(message)
        app.render = lambda: None
        app.alerts_active = [ALERT]
        acknowledged = {**ALERT, "status": "acknowledged"}
        with patch("data.acknowledge_alert", create=True, return_value=(True, "")) as ack, \
                patch.object(app_main, "live_status", return_value={
                    "ok": True, "alerts_active": [], "alerts_history": [acknowledged]}):
            self.assertTrue(app.acknowledge_alert(ALERT["id"]))
        ack.assert_called_once_with(ALERT["id"], actor="admin@example.test")
        self.assertIn("تأیید هشدار ثبت شد", app.messages)


class AlertsTests(unittest.TestCase):
    def test_only_snapshot_active_history_are_shown_without_siren_or_dispatch_claims(self):
        app = fake_app("alerts")
        app.alerts_active = [{**ALERT, "source": "demo", "emp": "SAMPLE"}]
        closed = {**ALERT, "id": "old-7", "emp": "HISTORY-SYNTHETIC", "status": "closed"}
        with patch.object(alerts, "live_status", return_value={"ok": True,
                "alerts_active": [ALERT], "alerts_history": [closed]}):
            view = alerts.alerts_view(app)
        rendered = text(view)
        self.assertIn("gw-synthetic", rendered)
        self.assertIn("HISTORY-SYNTHETIC", rendered)
        self.assertNotIn("SAMPLE", rendered)
        self.assertNotIn("آژیر", rendered)
        self.assertNotIn("اعزام", rendered)
        self.assertIn("گیت‌وی آفلاین", rendered)
        self.assertIn("بسته‌شده", rendered)


class ManualMeasurementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = fake_app("employee")
        self.app.state.update(emp=MAC, empd_gen=0, admin_email="admin@example.test")
        self.employee = {**EMPLOYEE, "scan_allowed": True, "scan_paused": False}

    def build(self):
        with patch.object(employee_detail, "live_employees", return_value=[self.employee]):
            self.view = employee_detail.employee_detail_view(self.app)
        self.initial_task_count = len(self.app.tasks)
        return tagged(self.view, "employee:measure")

    async def test_registered_profile_manual_measurement_sends_actor_and_shows_pending_response(self):
        button = self.build()
        self.assertFalse(button.disabled)
        with patch("data.send_measure", return_value=(True, "درخواست در صف قرار گرفت")) as send:
            button.on_click(None)
            self.assertTrue(button.disabled)
            task_count = len(self.app.tasks)
            button.on_click(None)
            self.assertEqual(len(self.app.tasks), task_count)
            handler, args = self.app.tasks[-1]
            await handler(*args)
        send.assert_called_once_with(MAC, actor="admin@example.test")
        feedback = tagged(self.view, "employee:measure-feedback")
        self.assertIn("در صف", feedback.value)
        self.assertTrue(button.disabled)

    async def test_manual_measurement_rejection_is_shown_and_pause_policy_disables_button(self):
        self.employee["scan_allowed"] = False
        self.employee["scan_paused"] = True
        button = self.build()
        self.assertTrue(button.disabled)
        with patch("data.send_measure", create=True, return_value=(False, "paused")) as send:
            button.on_click(None)
            self.assertEqual(len(self.app.tasks), self.initial_task_count)
            send.assert_not_called()
            self.employee["scan_allowed"] = True
            self.employee["scan_paused"] = False
            button.disabled = False
            button.on_click(None)
            self.assertTrue(button.disabled)
            handler, args = self.app.tasks[-1]
            await handler(*args)
        send.assert_called_once_with(MAC, actor="admin@example.test")
        feedback = tagged(self.view, "employee:measure-feedback")
        self.assertEqual(feedback.value, "paused")

    async def test_profile_reads_persisted_manual_result_and_blocks_queued_duplicate(self):
        self.employee["manual_measurement"] = {"request_id": "measure-synthetic", "status": "queued"}
        button = self.build()
        self.assertTrue(button.disabled)
        self.assertIn("صف", tagged(self.view, "employee:measure-feedback").value)
        button.on_click(None)
        self.assertEqual(len(self.app.tasks), self.initial_task_count)

        self.employee["manual_measurement"] = {"request_id": "measure-synthetic", "status": "done", "bpm": 81}
        button = self.build()
        self.assertFalse(button.disabled)
        self.assertIn("۸۱", tagged(self.view, "employee:measure-feedback").value)

    async def test_late_measurement_completion_after_navigation_does_not_update_old_view(self):
        button = self.build()
        gate = threading.Event()
        started = threading.Event()

        def pending(*_args, **_kwargs):
            started.set()
            if not gate.wait(2):
                raise TimeoutError("test did not release measurement")
            return True, "completed"

        with patch("data.send_measure", create=True, side_effect=pending) as send:
            button.on_click(None)
            handler, args = self.app.tasks[-1]
            task = asyncio.create_task(handler(*args))
            await asyncio.to_thread(started.wait, 2)
            self.assertTrue(started.is_set())
            self.app.state["view"] = "dashboard"
            self.app.state["empd_gen"] += 1
            gate.set()
            await task
        send.assert_called_once_with(MAC, actor="admin@example.test")
        self.assertEqual(self.app.messages, [])
        self.assertTrue(button.disabled)


if __name__ == "__main__":
    unittest.main()
