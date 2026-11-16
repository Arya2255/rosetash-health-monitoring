"""Admin profile storage and real settings callbacks, isolated from user data."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock, patch

import flet as ft

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import admin_roles
import data
import views.settings as settings


def walk(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child)


class AdminProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="admin-profile-", dir=os.environ["TMPDIR"],
        )
        self.addCleanup(temporary.cleanup)
        self.roles_file = Path(temporary.name) / "config" / "admin_roles.json"
        self.enterContext(patch.object(admin_roles, "ROLES_FILE", str(self.roles_file)))
        self.enterContext(patch.object(admin_roles, "DEFAULT_OWNER", "owner@example.test"))
        self.enterContext(patch.object(admin_roles.applog, "info"))
        self.enterContext(patch.object(admin_roles.applog, "error"))
        self.enterContext(patch.object(settings, "DEFAULT_OWNER", "owner@example.test"))
        self.enterContext(patch.object(settings, "remote_status", return_value={}))
        self.enterContext(patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network call")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("Unexpected network call")))

    def seed(self, document):
        self.roles_file.parent.mkdir(parents=True, exist_ok=True)
        self.roles_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def saved(self):
        return json.loads(self.roles_file.read_text(encoding="utf-8"))

    def test_name_persists_under_normalized_email_without_changing_other_data(self):
        original = {
            "roles": {"viewer@example.test": "viewer", "other@example.test": "viewer"},
            "names": {"other@example.test": "مدیر آزمایشی دیگر"},
            "custom": {"keep": [1, 2]},
        }
        self.seed(original)

        ok, message = admin_roles.set_admin_name("  Viewer@Example.Test  ", "  نام آزمایشی  ")

        self.assertTrue(ok, message)
        self.assertEqual(admin_roles.get_admin_name(" VIEWER@EXAMPLE.TEST "), "نام آزمایشی")
        document = self.saved()
        self.assertEqual(document["roles"], original["roles"])
        self.assertEqual(document["custom"], original["custom"])
        self.assertEqual(document["names"], {
            "other@example.test": "مدیر آزمایشی دیگر",
            "viewer@example.test": "نام آزمایشی",
        })
        self.assertIn("updated_at", document)

    def test_invalid_names_including_clearing_leave_saved_profile_unchanged(self):
        self.seed({
            "roles": {"viewer@example.test": "viewer"},
            "names": {"viewer@example.test": "نام قبلی"},
            "custom": "keep",
        })
        before = self.roles_file.read_bytes()
        invalid_names: tuple[Any, ...] = (
            "", "   ", None, 42, "ن" * 121, "نام\nتازه", "نام\tتازه",
            "نام\x00تازه", "نام\x7fتازه", "نام\u2028تازه", "\u200c", "نام\u202eتازه",
        )
        for name in invalid_names:
            with self.subTest(name=repr(name)):
                ok, message = admin_roles.set_admin_name("viewer@example.test", name)
                self.assertFalse(ok)
                self.assertTrue(message)
                self.assertEqual(self.roles_file.read_bytes(), before)

    def test_invalid_email_does_not_create_profile_file(self):
        invalid_emails: tuple[Any, ...] = ("", "  ", None, "invalid")
        for email in invalid_emails:
            with self.subTest(email=email):
                ok, message = admin_roles.set_admin_name(email, "نام آزمایشی")
                self.assertFalse(ok)
                self.assertTrue(message)
                self.assertFalse(self.roles_file.exists())

    def test_persian_name_with_half_space_and_length_boundary_is_supported(self):
        name = "نام\u200cآزمایشی"
        ok, message = admin_roles.set_admin_name("viewer@example.test", name)
        self.assertTrue(ok, message)
        self.assertEqual(admin_roles.get_admin_name("viewer@example.test"), name)
        ok, message = admin_roles.set_admin_name("viewer@example.test", "ن" * 120)
        self.assertTrue(ok, message)
        self.assertEqual(admin_roles.get_admin_name("viewer@example.test"), "ن" * 120)

    def test_removing_admin_cleans_only_that_accounts_name(self):
        self.seed({
            "roles": {"viewer@example.test": "viewer", "other@example.test": "viewer"},
            "names": {"viewer@example.test": "نام حذف‌شدنی", "other@example.test": "نام دیگر"},
            "custom": "keep",
        })
        ok, message = admin_roles.remove_admin("  VIEWER@EXAMPLE.TEST  ")
        self.assertTrue(ok, message)
        self.assertEqual(self.saved()["roles"], {"other@example.test": "viewer"})
        self.assertEqual(self.saved()["names"], {"other@example.test": "نام دیگر"})
        self.assertEqual(self.saved()["custom"], "keep")
        self.assertEqual(admin_roles.get_admin_name("viewer@example.test"), "")

    def test_owner_can_save_own_name_but_cannot_be_removed(self):
        ok, message = admin_roles.set_admin_name(" OWNER@EXAMPLE.TEST ", "نام مالک آزمایشی")
        self.assertTrue(ok, message)
        before = self.roles_file.read_bytes()
        ok, message = admin_roles.remove_admin("owner@example.test")
        self.assertFalse(ok)
        self.assertEqual(self.roles_file.read_bytes(), before)
        self.assertEqual(admin_roles.get_role("owner@example.test"), "owner")

    def test_missing_name_returns_empty_without_creating_config(self):
        emails: tuple[Any, ...] = ("viewer@example.test", "owner@example.test", "", None)
        for email in emails:
            with self.subTest(email=email):
                self.assertEqual(admin_roles.get_admin_name(email), "")
        self.assertFalse(self.roles_file.exists())

    def make_app(self, **state):
        return SimpleNamespace(
            state={"view": "settings", "logged_in": True,
                   "admin_email": "viewer@example.test", "admin_name": "نام قبلی", **state},
            page=SimpleNamespace(width=1340, overlay=[], update=Mock()),
            render=Mock(), snack=Mock(), go=Mock(),
        )

    def profile_controls(self, app):
        controls = list(walk(settings.settings_view(app)))
        field = next((c for c in controls if getattr(c, "data", None) == "admin-profile-name"), None)
        save = next((c for c in controls if getattr(c, "data", None) == "admin-profile-save"), None)
        assert isinstance(field, ft.TextField), "Profile name field missing"
        assert isinstance(save, ft.Button), "Profile save button missing"
        return field, save

    def test_data_layer_exports_profile_api(self):
        self.assertIs(getattr(data, "get_admin_name", None), admin_roles.get_admin_name)
        self.assertIs(getattr(data, "set_admin_name", None), admin_roles.set_admin_name)

    def test_settings_save_callback_persists_name_and_refreshes_state_before_render(self):
        self.seed({"roles": {"viewer@example.test": "viewer"},
                   "names": {"viewer@example.test": "نام قبلی"}})
        app = self.make_app(admin_email=" Viewer@Example.Test ")
        field, save = self.profile_controls(app)
        self.assertEqual(field.value, "نام قبلی")
        field.value = "  نام تازه آزمایشی  "
        seen_names = []
        app.render.side_effect = lambda: seen_names.append(app.state["admin_name"])

        save.on_click(SimpleNamespace(control=save))

        self.assertEqual(admin_roles.get_admin_name("viewer@example.test"), "نام تازه آزمایشی")
        self.assertEqual(app.state["admin_name"], "نام تازه آزمایشی")
        self.assertEqual(seen_names, ["نام تازه آزمایشی"])
        app.render.assert_called_once_with()
        app.snack.assert_called_once()

    def test_settings_profile_requires_login_and_email(self):
        for state in ({"logged_in": False}, {"admin_email": ""}, {"admin_email": None},
                      {"admin_email": "   "}):
            with self.subTest(state=state):
                controls = list(walk(settings.settings_view(self.make_app(**state))))
                self.assertFalse(any(getattr(c, "data", None) in
                                     ("admin-profile-name", "admin-profile-save") for c in controls))

    def test_settings_empty_name_does_not_clear_profile_or_refresh(self):
        self.seed({"roles": {"viewer@example.test": "viewer"},
                   "names": {"viewer@example.test": "نام قبلی"}})
        app = self.make_app()
        field, save = self.profile_controls(app)
        field.value = "   "

        save.on_click(SimpleNamespace(control=save))

        self.assertEqual(admin_roles.get_admin_name("viewer@example.test"), "نام قبلی")
        self.assertEqual(app.state["admin_name"], "نام قبلی")
        app.render.assert_not_called()
        app.snack.assert_called_once()

    def test_settings_write_failure_keeps_existing_name_and_state(self):
        self.seed({"roles": {"viewer@example.test": "viewer"},
                   "names": {"viewer@example.test": "نام قبلی"}})
        app = self.make_app()
        field, save = self.profile_controls(app)
        field.value = "نام تازه"
        before = self.roles_file.read_bytes()

        with patch.object(admin_roles, "_write_roles", side_effect=PermissionError("read-only")):
            save.on_click(SimpleNamespace(control=save))

        self.assertEqual(self.roles_file.read_bytes(), before)
        self.assertEqual(app.state["admin_name"], "نام قبلی")
        app.render.assert_not_called()
        app.snack.assert_called_once()
        self.assertIn("ذخیره نشد", app.snack.call_args.args[0])

    def test_stale_profile_callback_cannot_save_after_logout_or_account_change(self):
        self.seed({"roles": {"viewer@example.test": "viewer"},
                   "names": {"viewer@example.test": "نام قبلی"}})
        before = self.roles_file.read_bytes()
        for next_state in ({"logged_in": False, "admin_email": None, "admin_name": ""},
                           {"admin_email": "other@example.test", "admin_name": "نام دیگر"}):
            with self.subTest(next_state=next_state):
                app = self.make_app()
                field, save = self.profile_controls(app)
                field.value = "نام تازه"
                app.state.update(next_state)
                expected_state = dict(app.state)

                save.on_click(SimpleNamespace(control=save))

                self.assertEqual(self.roles_file.read_bytes(), before)
                self.assertEqual(app.state, expected_state)
                app.render.assert_not_called()

    def test_profile_available_for_both_roles_without_changing_owner_sections(self):
        for email in ("viewer@example.test", "owner@example.test"):
            for width in (1340, 390):
                with self.subTest(email=email, width=width):
                    app = self.make_app(admin_email=email)
                    app.page.width = width
                    self.profile_controls(app)
                    texts = [c.value for c in walk(settings.settings_view(app)) if isinstance(c, ft.Text)]
                    self.assertIn("حساب کاربری", texts)
                    self.assertEqual("مدیریت ادمین‌ها" in texts, email == "owner@example.test")
                    self.assertEqual("دسترسی از اینترنت" in texts, email == "owner@example.test")


if __name__ == "__main__":
    unittest.main()
