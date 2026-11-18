"""Regression tests for OTP countdown lifetime and console confidentiality."""
import asyncio
import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import views.login as login
import email_otp


class LoginCountdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_countdown_stops_without_touching_controls_after_view_changes(self):
        class App:
            def __init__(self):
                self.state = {"view": "login", "login_view_token": object()}

        app = App()
        token = app.state["login_view_token"]
        rendered = []
        finished = []

        async def leave_view(_delay):
            app.state["view"] = "map"

        await login._run_countdown(
            3, lambda: login._login_view_is_active(app, token),
            rendered.append, lambda: finished.append(True), sleep=leave_view,
        )

        self.assertEqual(rendered, [3])
        self.assertEqual(finished, [])

    async def test_older_countdown_stops_after_resend_starts_new_generation(self):
        app = type("App", (), {
            "state": {"view": "login", "login_view_token": object()}
        })()
        token = app.state["login_view_token"]
        current_generation = 1
        rendered = []
        finished = []

        async def resend(_delay):
            nonlocal current_generation
            current_generation = 2

        await login._run_countdown(
            3,
            lambda: login._login_countdown_is_active(
                app, token, 1, current_generation),
            rendered.append,
            lambda: finished.append(True),
            sleep=resend,
        )

        self.assertEqual(rendered, [3])
        self.assertEqual(finished, [])

    def test_replaced_login_view_rejects_callbacks_from_old_view(self):
        class App:
            def __init__(self):
                self.state = {"view": "login", "login_view_token": object()}

        app = App()
        old_token = app.state["login_view_token"]
        app.state["login_view_token"] = object()
        self.assertFalse(login._login_view_is_active(app, old_token))
        self.assertTrue(login._login_view_is_active(
            app, app.state["login_view_token"]))

    async def test_countdown_reenables_resend_when_time_expires(self):
        rendered = []
        finished = []

        async def immediate_sleep(_delay):
            return None

        await login._run_countdown(
            3, lambda: True, rendered.append,
            lambda: finished.append(True), sleep=immediate_sleep,
        )

        self.assertEqual(rendered, [3, 2, 1])
        self.assertEqual(finished, [True])


class OtpConsoleDebugTests(unittest.TestCase):
    def test_otp_is_printed_for_local_testing_only(self):
        output = io.StringIO()
        with patch.object(email_otp, "config", return_value={"smtp": {}}), \
                patch.dict(os.environ, {"ROZTASH_OTP_CONSOLE_DEBUG": "1"}):
            with contextlib.redirect_stdout(output):
                ok, error = email_otp.send_otp_email("local-test@example.com", "739104")

        self.assertFalse(ok)
        self.assertIn("تنظیمات ایمیل ناقص است", error)
        self.assertIn("739104", output.getvalue())

    def test_otp_is_not_printed_without_explicit_local_test_flag(self):
        output = io.StringIO()
        with patch.object(email_otp, "config", return_value={"smtp": {}}), \
                patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(output):
                ok, _error = email_otp.send_otp_email("local-test@example.com", "739104")
        self.assertFalse(ok)
        self.assertNotIn("739104", output.getvalue())


if __name__ == "__main__":
    unittest.main()
