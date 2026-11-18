"""Employee shift/pause and health interval UI behaviour, without real services."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import flet as ft
import components.employee_form as form
import components.monitoring as monitoring


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)
    for child in getattr(control, "actions", []) or []:
        yield from walk(child)


class FakeApp:
    def __init__(self, role="viewer", width=390):
        self.state = {"view": "employees", "role": role,
                      "logged_in": role in ("viewer", "owner"),
                      "admin_email": "admin@example.test" if role else None}
        self.dialogs = []
        self.messages = []
        self.page = SimpleNamespace(width=width, height=800, update=lambda: None,
                                    show_dialog=self.dialogs.append, pop_dialog=lambda: None)

    def snack(self, msg):
        self.messages.append(msg)


EMP = {"mac": "aa:bb:cc:dd:ee:01", "name": "Test Employee", "registered": True,
       "weekly_schedule": {"mon": [{"start": "08:00", "end": "16:00"}]},
       "scan_paused": False}


class MonitoringUiTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("live_bands", []), ("live_catalogs", {})):
            p = patch.object(form, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def test_all_admins_can_edit_week_and_pause_on_desktop_and_mobile(self):
        for role in ("owner", "viewer"):
            for width in (390, 1340):
                with self.subTest(role=role, width=width):
                    app = FakeApp(role, width)
                    with patch.object(form, "save_employee", return_value=(True, "")) as base, patch.object(form, "save_employee_monitoring", return_value=(True, "")) as policy:
                        dialog = form.open_employee_form(app, emp=EMP)
                        nodes = list(walk(dialog))
                        toggle = next(c for c in nodes if getattr(c, "data", None) == "monitoring:paused")
                        self.assertFalse(toggle.disabled)
                        toggle.value = True
                        start = next(c for c in nodes if getattr(c, "data", None) == "schedule:mon:start:0")
                        self.assertFalse(start.disabled)
                        start.value = "۰۹:۰۰"
                        dialog.actions[1].on_click(None)
                        self.assertEqual(base.call_count, 1)
                        doc = policy.call_args.args[0]
                        self.assertTrue(doc["scan_paused"])
                        self.assertEqual(doc["weekly_schedule"]["mon"][0]["start"], "09:00")
                        self.assertEqual(doc["actor"], "admin@example.test")

    def test_unchanged_pause_is_not_resent_when_editing_hours(self):
        app = FakeApp()
        with patch.object(form,"save_employee",return_value=(True,"")), patch.object(form,"save_employee_monitoring",return_value=(True,"")) as policy:
            dialog=form.open_employee_form(app,emp=EMP)
            next(c for c in walk(dialog) if getattr(c,"data",None)=="schedule:mon:start:0").value="09:00"
            dialog.actions[1].on_click(None)
            self.assertNotIn("scan_paused",policy.call_args.args[0],
                             "a stale form must not resume a pause applied by another admin")

    def test_invalid_hours_do_not_save_anything(self):
        app = FakeApp()
        with patch.object(form, "save_employee") as base, patch.object(form, "save_employee_monitoring") as policy:
            dialog = form.open_employee_form(app, emp=EMP)
            start = next(c for c in walk(dialog) if getattr(c, "data", None) == "schedule:mon:start:0")
            start.value = "29:00"
            dialog.actions[1].on_click(None)
            base.assert_not_called()
            policy.assert_not_called()

    def test_monitoring_write_failure_is_not_reported_as_success(self):
        app = FakeApp()
        with patch.object(form, "save_employee", return_value=(True, "")), patch.object(form, "save_employee_monitoring", return_value=(False, "unavailable")):
            dialog = form.open_employee_form(app, emp=EMP)
            next(c for c in walk(dialog) if getattr(c, "data", None) == "monitoring:paused").value = True
            dialog.actions[1].on_click(None)
            self.assertFalse(app.messages)
            self.assertTrue(any("unavailable" in str(getattr(c, "value", "")) for c in walk(dialog)))

    def test_unknown_role_cannot_enable_monitoring_controls(self):
        dialog = form.open_employee_form(FakeApp(""), emp=EMP)
        nodes = list(walk(dialog))
        self.assertTrue(next(c for c in nodes if getattr(c, "data", None) == "monitoring:paused").disabled)
        self.assertTrue(next(c for c in nodes if getattr(c, "data", None) == "schedule:mon:start:0").disabled)

    def test_viewer_pause_button_and_unavailable_health_warning(self):
        import views.employees as employees_view
        import views.live as live_view
        import views.employee_detail as detail_view
        employee = {**EMP, "shift": "صبح", "status": "warn", "issues": ["measure_unavailable"],
                    "scan_allowed": True, "scheduled_now": True,
                    "monitoring_reason": "active", "present": False}
        app = FakeApp()
        with patch.object(employees_view, "live_employees", return_value=[employee]), patch.object(employees_view, "save_employee_monitoring", return_value=(True, "")) as pause:
            view = employees_view.employees_view(app)
            button = next(c for c in walk(view) if getattr(c, "data", None) == "monitoring:toggle:" + EMP["mac"])
            button.on_click(None)
            self.assertTrue(pause.call_args.args[0]["scan_paused"])
            self.assertEqual(pause.call_args.args[0]["actor"], "admin@example.test")
        with patch.object(live_view, "live_status", return_value={"ok": True,
                "events": [{"kind":"measure_unavailable", "mac":EMP["mac"], "ts":None}]}), patch.object(monitoring, "monitoring_settings", return_value={"health_interval_s":600}):
            view = live_view.live_view(app)
            self.assertTrue(any("نوبت اندازه‌گیری" in str(getattr(c, "value", "")) for c in walk(view)))
        app.state.update(view="employee", emp=EMP["mac"])
        with patch.object(detail_view, "live_employees", return_value=[employee]):
            view = detail_view.employee_detail_view(app)
            warnings = [c for c in walk(view) if isinstance(c, ft.Container)
                        and c.visible and c.bgcolor == "#FCF0DC"
                        and any("نوبت اندازه‌گیری" in str(getattr(child, "value", ""))
                                for child in walk(c))]
            self.assertTrue(warnings, "missing-band warning must be visible even when present=False")

    def test_interval_control_saves_minutes_as_seconds_for_viewer(self):
        app = FakeApp()
        with patch.object(monitoring, "monitoring_settings", return_value={"health_interval_s": 600}), patch.object(monitoring, "save_monitoring_settings", return_value=(True, "")) as save:
            card = monitoring.monitoring_interval_card(app)
            nodes = list(walk(card))
            field = next(c for c in nodes if getattr(c, "data", None) == "monitoring:interval")
            self.assertEqual(field.value, "10")
            button = next(c for c in nodes if getattr(c, "data", None) == "monitoring:save-interval")
            field.value = "۱۵"
            button.on_click(None)
            self.assertEqual(save.call_args.args[0]["health_interval_s"], 900)
            save.reset_mock()
            field.value = "0"
            button.on_click(None)
            save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
