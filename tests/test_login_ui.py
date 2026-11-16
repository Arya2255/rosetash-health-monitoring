"""Login handlers and account chrome exercised with mounted Flet controls.

The transport is in-memory; external mail/authorization and user files are isolated.
This checks serialization and handlers, not Flutter's visual rendering.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft
import msgpack
from flet.controls.base_control import BaseControl
from flet.messaging.connection import Connection
from flet.messaging.protocol import configure_encode_object_for_msgpack
from flet.messaging.session import Session
from flet.pubsub.pubsub_hub import PubSubHub
import main as app_main
import admin_roles
import views.login as login

EMAIL = "manager@example.com"
NAME = "مسئول آزمایشی"


def walk(control, visible_only=False):
    if visible_only and not getattr(control, "visible", True):
        return
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from walk(content, visible_only)
    for child in getattr(control, "controls", []) or []:
        yield from walk(child, visible_only)


def by_tag(control, tag):
    return next(c for c in walk(control) if getattr(c, "data", None) == tag)


class MemoryConnection(Connection):
    def __init__(self, loop):
        super().__init__()
        self.loop = loop
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.pubsubhub = PubSubHub(loop, self.executor)
        self.messages = []

    def send_message(self, message):
        self.messages.append(self.encode(message))

    def encode(self, value):
        return msgpack.packb(value, default=configure_encode_object_for_msgpack(BaseControl))


class LoginUiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = MemoryConnection(asyncio.get_running_loop())
        self.session = Session(self.conn)
        self.page = self.session.page
        self.page.width = 1340
        self.page.height = 800
        self.conn.encode(self.session.get_page_patch())
        self.tasks = []
        self.gates = []
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.session_file = Path(self.tmp.name) / "session.json"
        expanduser = os.path.expanduser

        def isolated_path(path):
            if path.startswith("~/.config/roztash/"):
                return str(Path(self.tmp.name) / Path(path).name)
            return expanduser(path)

        self.patchers = [
            patch.dict(os.environ, {"ROZTASH_CONFIG_HOME": self.tmp.name}),
            patch.object(os.path, "expanduser", side_effect=isolated_path),
            patch.object(admin_roles, "ROLES_FILE", str(Path(self.tmp.name) / "admin_roles.json")),
            patch.object(ft.Page, "run_task", self.schedule),
            patch.object(login, "allowed_emails", return_value=[EMAIL]),
            patch.object(login, "_send_email_otp", return_value=(True, "")),
            patch.object(login, "_generate_otp", return_value="123456"),
            patch.object(login, "get_admin_name", return_value=NAME),
            patch.object(app_main, "get_admin_name", return_value=NAME),
        ]
        self.mocks = [p.start() for p in self.patchers]
        self.app = SimpleNamespace(page=self.page, state={"view": "login", "logged_in": False})
        self.app.go = lambda view: self.app.state.update(view=view)
        self.root = login.login_view(self.app)
        self.page.add(self.root)
        login.OTP_STORE.clear()

    def schedule(self, handler, *args, **kwargs):
        task = asyncio.create_task(handler(*args, **kwargs))
        self.tasks.append(task)
        return task

    async def asyncTearDown(self):
        for gate in self.gates:
            gate.set()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for p in reversed(self.patchers):
            p.stop()
        self.conn.executor.shutdown(wait=True)
        login.OTP_STORE.clear()

    async def until(self, predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.005)

    def control(self, tag):
        return by_tag(self.root, "login-" + tag)

    def request(self):
        self.control("email").value = EMAIL
        self.control("request").on_click(None)

    async def finish_request(self):
        self.request()
        await asyncio.wait_for(self.tasks[0], 3)

    def block(self, result):
        gate = threading.Event()
        started = threading.Event()
        self.gates.append(gate)

        def pending(*_args):
            started.set()
            if not gate.wait(3):
                raise TimeoutError("Test did not release service")
            return result

        return gate, started, pending

    async def test_loading_precedes_email_lookup_and_duplicate_click_is_ignored(self):
        gate, started, pending = self.block([EMAIL])
        with patch.object(login, "allowed_emails", side_effect=pending) as lookup:
            self.request()
            self.assertTrue(self.control("loading").visible)
            self.assertEqual(self.control("loading-text").value, "در حال بررسی ایمیل…")
            self.assertTrue(self.control("request").disabled)
            self.assertTrue(self.control("email").disabled)
            self.control("email").on_submit(None)
            self.assertEqual(len(self.tasks), 1)
            await self.until(started.is_set)
            self.assertTrue(self.control("loading").visible)
            gate.set()
            await asyncio.wait_for(self.tasks[0], 3)
            self.assertEqual(lookup.call_count, 1)
        self.assertFalse(self.control("loading").visible)
        self.assertTrue(self.control("verify").visible)

    async def test_loading_covers_sending_and_prevents_verify_and_resend(self):
        gate, started, pending = self.block((True, ""))
        with patch.object(login, "_send_email_otp", side_effect=pending) as send:
            self.request()
            await self.until(started.is_set)
            self.assertEqual(self.control("loading-text").value, "در حال ارسال کد تأیید…")
            self.assertTrue(self.control("verify").disabled)
            self.control("code").value = "123456"
            self.control("verify").on_click(None)
            self.control("resend").on_click(None)
            self.assertFalse(self.app.state["logged_in"])
            self.assertFalse(self.session_file.exists())
            gate.set()
            await asyncio.wait_for(self.tasks[0], 3)
            self.assertEqual(send.call_count, 1)
        self.assertFalse(self.control("loading").visible)
        self.assertFalse(self.control("verify").disabled)

    async def test_rejected_email_and_lookup_failure_allow_retry(self):
        for result in ([], OSError("unavailable")):
            with self.subTest(result=result):
                kwargs = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with patch.object(login, "allowed_emails", **kwargs), patch.object(login, "_send_email_otp") as send:
                    self.request()
                    await asyncio.wait_for(self.tasks[-1], 3)
                    self.assertFalse(self.control("loading").visible)
                    self.assertFalse(self.control("request").disabled)
                    self.assertFalse(self.control("email").disabled)
                    self.assertTrue(self.control("error").value)
                    self.assertFalse(self.control("verify").visible)
                    send.assert_not_called()

    async def test_pending_lookup_does_not_send_after_navigation_replacement_or_detach(self):
        for action in ("navigate", "replace", "detach"):
            with self.subTest(action=action):
                self.app.state["view"] = "login"
                self.root = login.login_view(self.app)
                self.page.controls = [self.root]
                self.page.update()
                gate, started, pending = self.block([EMAIL])
                with patch.object(login, "allowed_emails", side_effect=pending), patch.object(login, "_send_email_otp") as send:
                    self.request()
                    task = self.tasks[-1]
                    await self.until(started.is_set)
                    if action == "navigate":
                        self.app.state["view"] = "map"
                    elif action == "replace":
                        self.page.controls = [login.login_view(self.app)]
                        self.page.update()
                    else:
                        self.page.controls.clear()
                        self.page.update()
                    updates_before = len(self.conn.messages)
                    gate.set()
                    await asyncio.wait_for(task, 3)
                    send.assert_not_called()
                    self.assertEqual(len(self.conn.messages), updates_before)

    async def test_back_then_new_request_ignores_old_mail_completion(self):
        gate, started, pending = self.block((True, ""))
        with patch.object(login, "_send_email_otp", side_effect=pending):
            self.request()
            old_task = self.tasks[0]
            await self.until(started.is_set)
            self.control("back").on_click(None)
            self.assertFalse(self.control("loading").visible)
            self.assertFalse(self.control("request").disabled)
            check_gate, check_started, check_pending = self.block([EMAIL])
            with patch.object(login, "allowed_emails", side_effect=check_pending):
                self.request()
                new_task = self.tasks[-1]
                await self.until(check_started.is_set)
                gate.set()
                await asyncio.wait_for(old_task, 3)
                self.assertTrue(self.control("loading").visible)
                self.assertEqual(self.control("loading-text").value, "در حال بررسی ایمیل…")
                self.assertEqual(self.control("info").value, "")
                check_gate.set()
                await asyncio.wait_for(new_task, 3)

    async def test_wrong_code_keeps_countdown_and_success_loads_identity(self):
        await self.finish_request()
        countdown_task = self.tasks[-1]
        self.control("code").value = "999999"
        self.control("verify").on_click(None)
        self.assertEqual(self.control("error").value, "کد اشتباه است")
        self.assertFalse(countdown_task.done())
        self.assertFalse(self.app.state["logged_in"])
        self.control("code").value = "123456"
        self.control("verify").on_click(None)
        self.assertTrue(self.app.state["logged_in"])
        self.assertEqual(self.app.state["admin_email"], EMAIL)
        self.assertEqual(self.app.state["admin_name"], NAME)
        self.assertEqual(self.app.state["view"], "map")
        self.assertEqual(json.loads(self.session_file.read_text())["email"], EMAIL)

    async def test_mail_failure_clears_loading_and_keeps_edit_email_available(self):
        with patch.object(login, "_send_email_otp", side_effect=OSError("mail down")):
            await self.finish_request()
        self.assertFalse(self.control("loading").visible)
        self.assertTrue(self.control("error").value)
        self.control("back").on_click(None)
        self.assertFalse(self.control("email").disabled)
        self.assertTrue(self.control("request").visible)
        self.assertEqual(self.control("error").value, "")

    async def test_resend_expires_then_sends_once_with_loading(self):
        with patch.object(login, "OTP_EXPIRY", 0):
            await self.finish_request()
            await self.until(lambda: not self.control("resend").disabled)
            gate, started, pending = self.block((True, ""))
            with patch.object(login, "_send_email_otp", side_effect=pending) as send:
                self.control("resend").on_click(None)
                task = self.tasks[-1]
                self.control("resend").on_click(None)
                await self.until(started.is_set)
                self.assertTrue(self.control("loading").visible)
                self.assertTrue(self.control("resend").disabled)
                gate.set()
                await asyncio.wait_for(task, 3)
                self.assertEqual(send.call_count, 1)
            self.assertFalse(self.control("loading").visible)

    def start_shell(self):
        real_app = app_main.App
        captured = []

        def build(page):
            app = real_app(page)
            captured.append(app)
            return app

        with patch.object(app_main, "App", side_effect=build), \
                patch.object(app_main, "remote_autostart"), \
                patch.object(app_main.applog, "setup"), \
                patch.object(app_main.applog, "install_hooks"), \
                patch.object(ft.Page, "run_task", return_value=None), \
                patch.dict(app_main.BUILDERS, {"map": lambda app: ft.Text("Test map")}), \
                patch("signal.signal"):
            self.page.controls.clear()
            app_main.main(self.page)
        return captured[0]

    async def test_account_is_hidden_until_login_refreshed_after_login_and_cleared_on_logout(self):
        app = self.start_shell()
        self.assertFalse(app.ui["user_box"].visible)
        self.assertEqual(app.ui["user_name"].value, "")
        self.assertEqual(app.ui["user_email"].value, "")
        self.assertNotIn("account-logout", [c.data for c in walk(app.root, True)])
        self.root = app.content_holder.content
        self.app = app
        await self.finish_request()
        self.control("code").value = "123456"
        with patch.dict(app_main.BUILDERS, {"map": lambda app: ft.Text("Test map")}):
            self.control("verify").on_click(None)
            self.assertTrue(app.ui["user_box"].visible)
            self.assertEqual(app.ui["user_name"].value, NAME)
            self.assertEqual(app.ui["user_email"].value, EMAIL)
            self.page.width = 390
            app.on_resize()
            self.assertTrue(app.ui["user_box"].visible)
        by_tag(app.root, "account-logout").on_click(None)
        self.assertFalse(app.ui["user_box"].visible)
        self.assertEqual(app.ui["user_name"].value, "")
        self.assertEqual(app.ui["user_email"].value, "")
        self.assertNotIn("account-logout", [c.data for c in walk(app.root, True)])
        self.assertEqual(app.state["view"], "login")
        self.assertFalse(self.session_file.exists())

    async def test_restored_session_opens_app_with_current_saved_name(self):
        self.session_file.write_text(json.dumps({
            "email": EMAIL, "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }))
        app = self.start_shell()
        self.assertTrue(app.state["logged_in"])
        self.assertEqual(app.state["view"], "map")
        self.assertTrue(app.ui["user_box"].visible)
        self.assertEqual(app.ui["user_name"].value, NAME)
        self.assertEqual(app.ui["user_email"].value, EMAIL)

    async def test_web_does_not_restore_the_hosts_desktop_session(self):
        self.session_file.write_text(json.dumps({
            "email": EMAIL, "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }))
        self.page.web = True
        app = self.start_shell()
        self.assertFalse(app.state["logged_in"])
        self.assertEqual(app.state["view"], "login")
        self.assertFalse(app.ui["user_box"].visible)

    async def test_web_login_does_not_persist_a_shared_session_for_other_visitors(self):
        self.page.web = True
        await self.finish_request()
        self.control("code").value = "123456"
        self.control("verify").on_click(None)
        self.assertTrue(self.app.state["logged_in"])
        self.assertFalse(self.session_file.exists())
        second_session = Session(self.conn)
        second_session.page.web = True
        visitor = app_main.App(second_session.page)
        self.assertFalse(visitor.state["logged_in"])

    async def test_web_logout_keeps_the_desktop_session_file(self):
        self.page.web = True
        app = self.start_shell()
        desktop_session = json.dumps({
            "email": "desktop@example.com",
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        })
        self.session_file.write_text(desktop_session)
        app.state.update(logged_in=True, admin_email=EMAIL, admin_name=NAME)
        app._apply_chrome()
        by_tag(app.root, "account-logout").on_click(None)
        self.assertFalse(app.state["logged_in"])
        self.assertTrue(self.session_file.exists())
        self.assertEqual(self.session_file.read_text(), desktop_session)

    async def test_missing_name_does_not_invent_a_person_for_the_account(self):
        self.session_file.write_text(json.dumps({
            "email": EMAIL,
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }))
        with patch.object(app_main, "get_admin_name", return_value=""):
            app = self.start_shell()
        self.assertTrue(app.ui["user_box"].visible)
        self.assertEqual(app.ui["user_name"].value, "نام مسئول ثبت نشده")
        self.assertEqual(app.ui["user_email"].value, EMAIL)


if __name__ == "__main__":
    unittest.main()
