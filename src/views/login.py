# -*- coding: utf-8 -*-
"""صفحه ورود — احراز هویت با کد OTP."""

import secrets
import time
import threading
import os

import flet as ft

from theme import FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt
from remote import allowed_emails
from email_otp import send_otp_email


# ذخیره موقت کدهای OTP
OTP_STORE = {}
OTP_EXPIRY = 300


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
    # متغیرهای وضعیت
    current_email = {"value": ""}
    countdown = {"value": 0}
    is_sending = {"value": False}
    
    # لودینگ
    loading = ft.ProgressRing(visible=False, width=20, height=20, color=INK)
    
    # پیام‌ها
    error_msg = ft.Text("", size=12, color="#B3261E", font_family=FONT)
    info_msg = ft.Text("", size=12, color="#1E8E4E", font_family=FONT)
    countdown_text = ft.Text("", size=11, color=TEXT_MUTED, font_family=FONT)
    
    # فیلد ایمیل
    email_field = ft.TextField(
        hint_text="ایمیل ادمین",
        text_size=14,
        width=300,
        border_color=INK,
        focused_border_color=INK,
    )
    
    # فیلد OTP
    otp_container = ft.Container(visible=False)
    otp_field = ft.TextField(
        hint_text="کد ۶ رقمی",
        text_size=14,
        width=300,
        border_color=INK,
        focused_border_color=INK,
    )
    
    # دکمه درخواست کد
    request_btn = ft.Button(
        "دریافت کد تأیید",
        width=300,
        height=45,
        style=ft.ButtonStyle(
            bgcolor=INK,
            color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
        ),
    )
    
    # دکمه تأیید
    verify_btn = ft.Button(
        "تأیید و ورود",
        width=300,
        height=45,
        style=ft.ButtonStyle(
            bgcolor=INK,
            color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
        ),
        visible=False,
    )
    
    # دکمه ارسال مجدد
    resend_container = ft.Container(
        ft.Button(
            "ارسال مجدد کد",
            width=300,
            height=40,
            style=ft.ButtonStyle(
                bgcolor=WHITE,
                color=INK,
                shape=ft.RoundedRectangleBorder(radius=R_BTN),
                side=ft.BorderSide(1, INK),
            ),
        ),
        visible=False,
        padding=ft.Padding(top=10, left=0, right=0, bottom=0),
    )
    
    # دکمه بازگشت
    back_btn = ft.TextButton(
        "ویرایش ایمیل",
        visible=False,
    )
    
    # محتوای OTP
    otp_container.content = ft.Column([
        txt("کد تأیید:", size=13, font=FONT_MED, color=INK),
        otp_field,
    ], spacing=5)
    
    resend_btn = resend_container.content
    
    def _set_loading(loading_state: bool):
        is_sending["value"] = loading_state
        loading.visible = loading_state
        request_btn.disabled = loading_state
        request_btn.update()
        loading.update()
    
    # لودینگ برای تأیید کد
    def _set_verify_loading(loading_state: bool):
        loading.visible = loading_state
        verify_btn.disabled = loading_state
        email_field.disabled = loading_state
        otp_field.disabled = loading_state
        loading.update()
        verify_btn.update()
        email_field.update()
        otp_field.update()
    
    def _show_error(msg: str):
        error_msg.value = msg
        error_msg.update()
    
    def _show_info(msg: str):
        info_msg.value = msg
        info_msg.update()
    
    def _on_request_otp(e):
        email = (email_field.value or "").strip().lower()
        
        # ═══════════ DEBUG LOG ═══════════
        print(f"\n=== DEBUG: OTP Request ===")
        print(f"Input email: '{email}'")
        
        if not email:
            _show_error("لطفا ایمیل را وارد کنید")
            return
        
        allowed = allowed_emails()
        print(f"Allowed emails: {allowed}")
        print(f"Comparison: email in allowed = {email in allowed}")
        print(f"Email type: {type(email)}")
        if allowed:
            print(f"First allowed email type: {type(allowed[0])}")
            print(f"Comparison result: '{email}' == '{allowed[0]}' = {email == allowed[0]}")
        print("===========================\n")
        
        if email not in allowed:
            _show_error("این ایمیل مجاز نیست")
            return
        
        _set_loading(True)
        
        code = _generate_otp()
        OTP_STORE[email] = {"code": code, "expires": time.time() + OTP_EXPIRY}
        
        def _send_in_background():
            ok, err = _send_email_otp(email, code)
            def _update_ui():
                _set_loading(False)
                if ok:
                    _show_info(f"کد تأیید به {email} ارسال شد")
                else:
                    _show_error(f"خطا در ارسال: {err}")
            app.page.run_thread(_update_ui)
        
        thread = threading.Thread(target=_send_in_background, daemon=True)
        thread.start()
        
        current_email["value"] = email
        
        email_field.disabled = True
        otp_container.visible = True
        request_btn.visible = False
        verify_btn.visible = True
        resend_container.visible = True
        resend_container.content.visible = True
        back_btn.visible = True
        
        countdown["value"] = OTP_EXPIRY
        _start_countdown()
        
        email_field.update()
        otp_container.update()
        request_btn.update()
        verify_btn.update()
        resend_container.update()
        back_btn.update()
    
    def _start_countdown():
        if countdown["value"] > 0:
            mins = countdown["value"] // 60
            secs = countdown["value"] % 60
            countdown_text.value = f"ارسال مجدد کد: {mins}:{secs:02d}"
            countdown_text.update()
            countdown["value"] -= 1
            
            t = threading.Timer(1.0, _start_countdown)
            t.daemon = True
            t.start()
        else:
            countdown_text.value = "می‌توانید کد جدید درخواست کنید"
            resend_btn.disabled = False
            countdown_text.update()
            resend_btn.update()
    
    def _on_resend(e):
        if countdown["value"] > 0:
            return
        
        email = current_email["value"]
        if not email:
            return
        
        _set_loading(True)
        
        code = _generate_otp()
        OTP_STORE[email] = {"code": code, "expires": time.time() + OTP_EXPIRY}
        
        def _send_in_background():
            ok, err = _send_email_otp(email, code)
            def _update_ui():
                _set_loading(False)
                if ok:
                    _show_info("کد جدید ارسال شد")
                else:
                    _show_error(f"خطا: {err}")
            app.page.run_thread(_update_ui)
        
        thread = threading.Thread(target=_send_in_background, daemon=True)
        thread.start()
        
        countdown["value"] = OTP_EXPIRY
        resend_btn.disabled = True
        _start_countdown()
    
    def _on_verify(e):
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
        
        _set_verify_loading(True)
        
        del OTP_STORE[email]
        
        # ذخیره سشن برای یک روز
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
        
        # تعیین و ذخیره نقش
        from data import ensure_has_role
        role = ensure_has_role(email)
        
        app.state["logged_in"] = True
        app.state["admin_email"] = email
        app.state["role"] = role
        app.go("map")
    
    def _on_back(e):
        email_field.disabled = False
        email_field.value = ""
        otp_container.visible = False
        otp_field.value = ""
        request_btn.visible = True
        verify_btn.visible = False
        resend_container.visible = False
        back_btn.visible = False
        info_msg.value = ""
        countdown_text.value = ""
        
        email_field.update()
        otp_container.update()
        request_btn.update()
        verify_btn.update()
        resend_container.update()
        back_btn.update()
        info_msg.update()
        countdown_text.update()
    
    # اتصال handler ها
    request_btn.on_click = _on_request_otp
    verify_btn.on_click = _on_verify
    resend_btn.on_click = _on_resend
    back_btn.on_click = _on_back
    email_field.on_submit = _on_request_otp
    otp_field.on_submit = _on_verify
    
    return ft.Container(
        content=ft.Column([
            txt("سامانه پایش سلامت رزتاش", size=24, font=FONT_B, color=INK),
            txt("ورود ادمین", size=16, font=FONT_MED, color=TEXT_MUTED),
            
            ft.Container(height=40),
            
            txt("ایمیل:", size=13, font=FONT_MED, color=INK),
            email_field,
            
            loading,
            
            otp_container,
            
            error_msg,
            info_msg,
            countdown_text,
            
            ft.Container(height=15),
            
            request_btn,
            verify_btn,
            resend_container,
            back_btn,
            
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
        alignment=ft.alignment.Alignment(0, 0),
        padding=40,
        expand=True,
    )
