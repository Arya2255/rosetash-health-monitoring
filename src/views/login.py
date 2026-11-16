# -*- coding: utf-8 -*-
"""صفحه ورود — احراز هویت با کد OTP."""

import asyncio
import os
import secrets
import time

import flet as ft

from theme import FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt
from data import remote_emails as allowed_emails, get_admin_name
from email_otp import send_otp_email


OTP_STORE = {}
OTP_EXPIRY = 300


class _LoginContainer(ft.Container):
    """Invalidate pending work when the rendered form leaves its page."""

    def did_mount(self):
        self._login_mounted = True

    def will_unmount(self):
        self._login_mounted = False


def _login_view_is_active(app, view_token):
    return (app.state.get("view") == "login"
            and app.state.get("login_view_token") is view_token)


def _login_countdown_is_active(app, view_token, generation, current_generation):
    return (_login_view_is_active(app, view_token)
            and generation == current_generation)


async def _run_countdown(seconds, is_active, on_tick, on_complete, sleep=asyncio.sleep):
    """Run an OTP countdown while its login view remains active."""
    remaining = seconds
    while remaining > 0 and is_active():
        on_tick(remaining)
        remaining -= 1
        await sleep(1)
    if remaining == 0 and is_active():
        on_complete()


def _generate_otp():
    """تولید کد ۶ رقمی تصادفی امن."""
    return f"{secrets.randbelow(1000000):06d}"


def _send_email_otp(email: str, code: str):
    """ارسال کد OTP به ایمیل."""
    ok, err = send_otp_email(email, code)
    if ok:
        print(f"✓ کد تأیید به {email} ارسال شد")
    else:
        print(f"✗ ارسال ایمیل ناموفق: {err}")
    return ok, err


def login_view(app):
    """نمایش صفحه ورود با OTP."""
    current_email = {"value": ""}
    countdown = {"value": 0}
    countdown_generation = {"value": 0}
    view_token = object()
    app.state["login_view_token"] = view_token
    is_sending = {"value": False}

    def _view_is_active():
        if (not _login_view_is_active(app, view_token)
                or not getattr(root, "_login_mounted", False)):
            return False
        try:
            return root.page is app.page and app.page.session.connection is not None
        except RuntimeError:
            return False

    def _countdown_is_active(generation):
        return (_view_is_active()
                and generation == countdown_generation["value"])

    loading = ft.ProgressRing(visible=False, width=20, height=20, color=INK,
                              data="login-loading")
    loading_text = txt("", size=12, color=TEXT_MUTED, visible=False,
                       data="login-loading-text")
    error_msg = ft.Text("", size=12, color="#B3261E", font_family=FONT,
                        data="login-error")
    info_msg = ft.Text("", size=12, color="#1E8E4E", font_family=FONT,
                       data="login-info")
    countdown_text = ft.Text("", size=11, color=TEXT_MUTED, font_family=FONT,
                             data="login-countdown")

    email_field = ft.TextField(
        hint_text="ایمیل ادمین", data="login-email", text_size=14, width=300,
        border={
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(side=ft.BorderSide(color=INK)),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(side=ft.BorderSide(color=INK)),
        },
    )
    otp_container = ft.Container(visible=False)
    otp_field = ft.TextField(
        hint_text="کد ۶ رقمی", data="login-code", text_size=14, width=300,
        border={
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(side=ft.BorderSide(color=INK)),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(side=ft.BorderSide(color=INK)),
        },
    )
    request_btn = ft.Button(
        "دریافت کد تأیید", data="login-request", width=300, height=45,
        style=ft.ButtonStyle(
            bgcolor=INK, color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
        ),
    )
    verify_btn = ft.Button(
        "تأیید و ورود", data="login-verify", width=300, height=45,
        style=ft.ButtonStyle(
            bgcolor=INK, color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
        ),
        visible=False,
    )
    resend_btn = ft.Button(
        "ارسال مجدد کد", data="login-resend", width=300, height=40,
        style=ft.ButtonStyle(
            bgcolor=WHITE, color=INK,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
            side=ft.BorderSide(1, INK),
        ),
    )
    resend_container = ft.Container(
        resend_btn, visible=False,
        padding=ft.Padding(top=10, left=0, right=0, bottom=0),
    )
    back_btn = ft.TextButton("ویرایش ایمیل", data="login-back", visible=False)
    otp_container.content = ft.Column([
        txt("کد تأیید:", size=13, font=FONT_MED, color=INK), otp_field,
    ], spacing=5)

    def _set_loading(loading_state: bool, message=""):
        is_sending["value"] = loading_state
        loading.visible = loading_state
        loading_text.visible = loading_state
        loading_text.value = message if loading_state else ""
        request_btn.disabled = loading_state
        email_field.disabled = loading_state or bool(current_email["value"])
        verify_btn.disabled = loading_state
        resend_btn.disabled = loading_state or countdown["value"] > 0
        root.update()

    def _show_error(msg: str):
        error_msg.value = msg
        error_msg.update()

    def _show_info(msg: str):
        info_msg.value = msg
        info_msg.update()

    def _on_request_otp(e):
        if not _view_is_active() or is_sending["value"] or current_email["value"]:
            return
        email = (email_field.value or "").strip().lower()
        if not email:
            _show_error("لطفا ایمیل را وارد کنید")
            return

        generation = countdown_generation["value"] + 1
        countdown_generation["value"] = generation
        error_msg.value = ""
        info_msg.value = ""
        _set_loading(True, "در حال بررسی ایمیل…")

        async def check_and_send():
            try:
                allowed = await asyncio.to_thread(allowed_emails)
                if not _countdown_is_active(generation):
                    return
                if email not in allowed:
                    _show_error("این ایمیل مجاز نیست")
                    return
                current_email["value"] = email
                otp_container.visible = True
                request_btn.visible = False
                verify_btn.visible = True
                resend_container.visible = True
                back_btn.visible = True
                await _send_code(email, generation)
            except Exception:
                if _countdown_is_active(generation):
                    _show_error("بررسی ایمیل انجام نشد؛ دوباره تلاش کنید")
            finally:
                if _countdown_is_active(generation):
                    _set_loading(False)

        app.page.run_task(check_and_send)

    async def _send_code(email, generation):
        code = _generate_otp()
        OTP_STORE[email] = {"code": code, "expires": time.time() + OTP_EXPIRY}
        countdown["value"] = OTP_EXPIRY
        _set_loading(True, "در حال ارسال کد تأیید…")
        _start_countdown()
        try:
            ok, err = await asyncio.to_thread(_send_email_otp, email, code)
        except Exception:
            ok, err = False, "ارسال ایمیل انجام نشد؛ دوباره تلاش کنید"
        if not _countdown_is_active(generation):
            return
        if ok:
            _show_info(f"کد تأیید به {email} ارسال شد")
        else:
            _show_error(f"خطا در ارسال: {err}")

    def _start_countdown():
        generation = countdown_generation["value"]

        async def run():
            await _run_countdown(
                countdown["value"],
                lambda: _countdown_is_active(generation),
                tick, complete,
            )

        def tick(remaining):
            countdown["value"] = remaining - 1
            countdown_text.value = f"ارسال مجدد کد: {remaining // 60}:{remaining % 60:02d}"
            countdown_text.update()

        def complete():
            countdown["value"] = 0
            countdown_text.value = "می‌توانید کد جدید درخواست کنید"
            resend_btn.disabled = is_sending["value"]
            countdown_text.update()
            resend_btn.update()

        app.page.run_task(run)

    def _on_resend(e):
        if not _view_is_active() or is_sending["value"] or countdown["value"] > 0:
            return
        email = current_email["value"]
        if not email:
            return
        generation = countdown_generation["value"] + 1
        countdown_generation["value"] = generation
        error_msg.value = ""
        info_msg.value = ""
        _set_loading(True, "در حال ارسال کد تأیید…")

        async def resend():
            try:
                await _send_code(email, generation)
            finally:
                if _countdown_is_active(generation):
                    _set_loading(False)

        app.page.run_task(resend)

    def _on_verify(e):
        if not _view_is_active() or is_sending["value"]:
            return
        email = current_email["value"]
        entered_code = (otp_field.value or "").strip()
        if not entered_code:
            _show_error("لطفا کد را وارد کنید")
            return
        stored = OTP_STORE.get(email)
        if not stored:
            _show_error("کد منقضی شده - کد جدید درخواست کنید")
            return
        if time.time() > stored["expires"]:
            del OTP_STORE[email]
            _show_error("کد منقضی شده - کد جدید درخواست کنید")
            return
        if entered_code != stored["code"]:
            _show_error("کد اشتباه است")
            otp_field.value = ""
            otp_field.update()
            return

        countdown_generation["value"] += 1
        otp_field.disabled = True
        _set_loading(True, "در حال ورود…")
        del OTP_STORE[email]

        # Only desktop may persist its login on this machine. Web state belongs
        # to this Flet page/session, never to a file shared by all visitors.
        if not getattr(app.page, "web", False):
            from datetime import datetime, timedelta
            import json
            session_data = {
                "email": email,
                "expires": (datetime.now() + timedelta(days=1)).isoformat()
            }
            session_file = os.path.expanduser("~/.config/roztash/session.json")
            os.makedirs(os.path.dirname(session_file), exist_ok=True)
            with open(session_file, "w") as f:
                json.dump(session_data, f)

        from data import ensure_has_role
        role = ensure_has_role(email)
        app.state["logged_in"] = True
        app.state["admin_email"] = email
        app.state["admin_name"] = get_admin_name(email)
        app.state["role"] = role
        app.go("map")

    def _on_back(e):
        if not _view_is_active():
            return
        countdown_generation["value"] += 1
        current_email["value"] = ""
        countdown["value"] = 0
        email_field.value = ""
        otp_container.visible = False
        otp_field.value = ""
        otp_field.disabled = False
        request_btn.visible = True
        verify_btn.visible = False
        resend_container.visible = False
        back_btn.visible = False
        info_msg.value = ""
        error_msg.value = ""
        countdown_text.value = ""
        _set_loading(False)

    request_btn.on_click = _on_request_otp
    verify_btn.on_click = _on_verify
    resend_btn.on_click = _on_resend
    back_btn.on_click = _on_back
    email_field.on_submit = _on_request_otp
    otp_field.on_submit = _on_verify

    root = _LoginContainer(
        data="login-view",
        content=ft.Column([
            txt("سامانه پایش سلامت رزتاش", size=24, font=FONT_B, color=INK),
            txt("ورود ادمین", size=16, font=FONT_MED, color=TEXT_MUTED),
            ft.Container(height=40),
            txt("ایمیل:", size=13, font=FONT_MED, color=INK),
            email_field, loading, loading_text, otp_container,
            error_msg, info_msg, countdown_text,
            ft.Container(height=15),
            request_btn, verify_btn, resend_container, back_btn,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
        alignment=ft.alignment.Alignment(0, 0),
        padding=40, expand=True,
    )
    return root
