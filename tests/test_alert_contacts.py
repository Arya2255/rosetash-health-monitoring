"""Alert contact routing: unit-scoped responsible wristbands."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft
import views.alerts as alerts
import main as app_main
from alert_contacts import hse_contacts, resolve_alert_contact


MAC_WORKER = "aa:bb:cc:dd:ee:01"
MAC_LEAD = "aa:bb:cc:dd:ee:02"
MAC_SUPERVISOR = "aa:bb:cc:dd:ee:03"
MAC_HSE = "aa:bb:cc:dd:ee:04"


class AlertContactRoutingTests(unittest.TestCase):
    def setUp(self):
        self.alert = {
            "id": "a1",
            "emp": "Worker",
            "mac": MAC_WORKER,
            "dept": "تولید روغن — خط روغن ۲",
            "location": "سالن تولید ۲",
        }

    def employee(self, mac, name, group, dept="تولید روغن", present=True, line=""):
        return {"mac": mac, "name": name, "staff_group": group,
                "dept": dept, "line": line, "present": present,
                "registered": True, "scan_allowed": True}

    def test_prefers_present_shift_leader_in_same_unit(self):
        rows = [
            self.employee(MAC_SUPERVISOR, "Supervisor", "supervisor"),
            self.employee(MAC_HSE, "HSE", "hse"),
            self.employee(MAC_LEAD, "Shift lead", "shift_leader"),
        ]
        self.assertEqual(resolve_alert_contact(self.alert, rows)["mac"], MAC_LEAD)

    def test_falls_back_from_shift_leader_to_supervisor_then_hse(self):
        rows = [self.employee(MAC_SUPERVISOR, "Supervisor", "supervisor"),
                self.employee(MAC_HSE, "HSE", "hse")]
        self.assertEqual(resolve_alert_contact(self.alert, rows)["mac"], MAC_SUPERVISOR)
        self.assertEqual(resolve_alert_contact(self.alert, [rows[1]])["mac"], MAC_HSE)

    def test_does_not_contact_worker_or_responsible_of_another_unit(self):
        rows = [
            self.employee(MAC_WORKER, "Worker", "employee"),
            self.employee(MAC_LEAD, "Other lead", "shift_leader", dept="تعمیرات"),
        ]
        self.assertIsNone(resolve_alert_contact(self.alert, rows))

    def test_hse_can_match_unit_through_line(self):
        row = self.employee(MAC_HSE, "HSE", "hse", dept="واحد HSE",
                            line="تولید روغن")
        self.assertEqual(resolve_alert_contact(self.alert, [row])["mac"], MAC_HSE)

    def test_hse_contacts_returns_all_unique_hse_wristbands(self):
        rows = [
            self.employee(MAC_HSE, "HSE 1", "hse"),
            self.employee(MAC_HSE, "HSE duplicate", "hse"),
            self.employee(MAC_LEAD, "Shift lead", "shift_leader"),
        ]
        self.assertEqual([row["mac"] for row in hse_contacts(rows)], [MAC_HSE])


class AlertContactUiTests(unittest.TestCase):
    def walk(self, control):
        yield control
        content = getattr(control, "content", None)
        if isinstance(content, ft.Control):
            yield from self.walk(content)
        for attr in ("controls", "actions"):
            for child in getattr(control, attr, None) or []:
                yield from self.walk(child)

    def test_contact_button_vibrates_responsible_wristband(self):
        messages = []
        app = SimpleNamespace(
            state={"view": "alerts"}, page=SimpleNamespace(width=1340),
            snack=messages.append, acknowledge_alert=lambda _: None,
        )
        issue = {"id": "a1", "source": "live", "type": "hr_high", "severity": "danger",
                 "status": "open", "emp": "Worker", "dept": "تولید روغن — خط روغن ۲",
                 "location": "سالن تولید ۲", "time": "12:00"}
        rows = [{"mac": MAC_LEAD, "name": "Shift lead", "staff_group": "shift_leader",
                 "dept": "تولید روغن", "present": True, "registered": True,
                 "scan_allowed": True}]
        with patch.object(alerts, "live_status", return_value={"ok": True, "alerts_active": [issue]}), \
                patch.object(alerts, "live_employees", return_value=rows), \
                patch.object(alerts, "send_vibrate", return_value=(True, "sent")) as vibrate:
            view = alerts.alerts_view(app)
            button = next(c for c in self.walk(view)
                          if getattr(c, "data", None) == "alerts:contact-responsible")
            button.on_click(None)
        vibrate.assert_called_once_with(MAC_LEAD)
        self.assertTrue(any("سرشیفت" in str(msg) and "ویبره" in str(msg)
                            for msg in messages))

    def test_rendering_live_alerts_does_not_send_vibration_commands(self):
        messages = []
        app = SimpleNamespace(
            state={"view": "alerts"}, page=SimpleNamespace(width=1340),
            alerts_active=[
                {"id": "a-hse", "type": "سقوط", "severity": "danger",
                 "source": "live",
                 "emp": "Worker", "dept": "تولید روغن",
                 "location": "سالن تولید", "time": "12:00"},
                {"id": "a-hse-2", "type": "افت اکسیژن", "severity": "warn",
                 "source": "live",
                 "emp": "Worker 2", "dept": "تعمیرات",
                 "location": "کارگاه", "time": "12:01"},
            ],
            siren_on=False, snack=messages.append, set_siren=lambda _: None,
            close_alert=lambda _: None,
        )
        rows = [
            {"mac": MAC_HSE, "name": "HSE 1", "staff_group": "hse", "present": True, "registered": True},
            {"mac": MAC_SUPERVISOR, "name": "HSE 2", "staff_group": "hse", "present": False, "registered": True},
        ]
        with patch.object(alerts, "live_status", return_value={"ok": True, "alerts_active": app.alerts_active}), \
                patch.object(alerts, "live_employees", return_value=rows), \
                patch.object(alerts, "send_vibrate", return_value=(True, "sent")) as vibrate:
            alerts.alerts_view(app)
            alerts.alerts_view(app)
        vibrate.assert_not_called()

    def test_live_health_alert_refresh_preserves_bridge_id_without_ui_dispatch(self):
        page = SimpleNamespace(web=True, width=1340, height=800)
        app = app_main.App(page)
        app.state.update(logged_in=True, admin_email="owner@example.test", role="owner")
        alert = {"id": "bridge-episode-1", "source": "live", "type": "hr_high",
                 "status": "open", "severity": "danger", "mac": MAC_WORKER}
        with patch.object(app_main, "live_status", return_value={"ok": True, "alerts_active": [alert]}), \
                patch.object(app_main, "send_vibrate") as vibrate:
            app.refresh_live_alerts()
            app.refresh_live_alerts()
        self.assertEqual(app.alerts_active, [alert])
        vibrate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
