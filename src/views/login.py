# -*- coding: utf-8 -*-
"""صفحه ورود — احراز هویت با کد OTP."""

import random
import time
import threading

import flet as ft

from theme import FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt
from remote import allowed_emails
from email_otp import send_otp_email


# ذخیره موقت کدهای OTP
OTP_STORE = {}  # {email: {"code": "123456", "expires": timestamp}}
OTP_EXPIRY = 300  # 5 دقیقه


def _generate_otp():
    """تولید کد ۶ رقمی."""
    return str(random.randint(100000, 999999))


def _send_email_otp(email: str, code: str):
    """ارسال کد OTP به ایمیل."""
    ok, err = send_otp_email(email, code)
    if ok:
        print(f"✓ کد تأیید به {email} ارسال شد")
    else:
        print(f"✗ ارسال ایمیل ناموفق: {err}")


def login_view(app):
    """نمایش صفحه ورود با OTP."""
    # متغیرهای وضعیت
    current_email = {"value": ""}
    countdown = {"value": 0}
    
    # فیلد ایمیل
    email_field = ft.TextField(
        hint_text="ایمیل ادمین",
        text_size=14,
        width=300,
        border_color=INK,
        focused_border_color=INK,
    )
    
    # فیلد OTP (در ظرف جداگانه)
    otp_container = ft.Container(visible=False)
    otp_field = ft.TextField(
        hint_text="کد ۶ رقمی",
        text_size=14,
        width=300,
        border_color=INK,
        focused_border_color=INK,
    )
    
    # پیام‌ها
    error_msg = ft.Text("", size=12, color="#B3261E", font_family=FONT)
    info_msg = ft.Text("", size=12, color="#1E8E4E", font_family=FONT)
    countdown_text = ft.Text("", size=11, color=TEXT_MUTED, font_family=FONT)
    
    # دکمه درخواست کد
    def _show_otp_sent_message(email: str):
        info_msg.value = f"کد تأیید به {email} ارسال شد"
        info_msg.update()
    
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
    resend_btn = ft.Button(
        "ارسال مجدد کد",
        width=300,
        height=40,
        style=ft.ButtonStyle(
            bgcolor=WHITE,
            color=INK,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
            side=ft.BorderSide(1, INK),
        ),
        visible=False,
    )
    
    # دکمه بازگشت
    back_btn = ft.TextButton(
        "ویرایش ایمیل",
        visible=False,
    )
    
    # ساخت محتوای OTP
    otp_container.content = ft.Column([
        txt("کد تأیید:", size=13, font=FONT_MED, color=INK),
        otp_field,
    ], spacing=5)
    
    def _on_request_otp(e):
        email = (email_field.value or "").strip().lower()
        
        if not email:
            error_msg.value = "لطفا ایمیل را وارد کنید"
            error_msg.update()
            return
        
        allowed = allowed_emails()
        if email not in allowed:
            error_msg.value = "این ایمیل مجاز نیست"
            error_msg.update()
            return
        
        # تولید کد
        code = _generate_otp()
        OTP_STORE[email] = {"code": code, "expires": time.time() + OTP_EXPIRY}
        
        # ارسال به ایمیل
        _send_email_otp(email, code)
        _show_otp_sent_message(email)
        
        # ذخیره ایمیل
        current_email["value"] = email
        
        # تغییر نمایش
        email_field.disabled = True
        otp_container.visible = True
        request_btn.visible = False
        verify_btn.visible = True
        resend_btn.visible = True
        back_btn.visible = True
        
        # شروع شمارش معکوس
        countdown["value"] = OTP_EXPIRY
        _start_countdown()
        
        # آپدیت همه
        email_field.update()
        otp_container.update()
        request_btn.update()
        verify_btn.update()
        resend_btn.update()
        back_btn.update()
        info_msg.update()
        error_msg.update()
    
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
        
        code = _generate_otp()
        OTP_STORE[email] = {"code": code, "expires": time.time() + OTP_EXPIRY}
        _send_email_otp(email, code)
        
        countdown["value"] = OTP_EXPIRY
        resend_btn.disabled = True
        _start_countdown()
        
        info_msg.value = "کد جدید ارسال شد"
        info_msg.update()
        resend_btn.update()
    
    def _on_verify(e):
        email = current_email["value"]
        entered_code = (otp_field.value or "").strip()
        
        if not entered_code:
            error_msg.value = "لطفا کد را وارد کنید"
            error_msg.update()
            return
        
        stored = OTP_STORE.get(email)
        if not stored:
            error_msg.value = "کد منقضی شده - کد جدید درخواست کنید"
            error_msg.update()
            return
        
        if time.time() > stored["expires"]:
            del OTP_STORE[email]
            error_msg.value = "کد منقضی شده - کد جدید درخواست کنید"
            error_msg.update()
            return
        
        if entered_code != stored["code"]:
            error_msg.value = "کد اشتباه است"
            error_msg.update()
            return
        
        # ورود موفق
        del OTP_STORE[email]
        
        app.state["logged_in"] = True
        app.state["admin_email"] = email
        app.go("map")
    
    def _on_back(e):
        email_field.disabled = False
        email_field.value = ""
        otp_container.visible = False
        otp_field.value = ""
        request_btn.visible = True
        verify_btn.visible = False
        resend_btn.visible = False
        back_btn.visible = False
        info_msg.value = ""
        countdown_text.value = ""
        
        email_field.update()
        otp_container.update()
        request_btn.update()
        verify_btn.update()
        resend_btn.update()
        back_btn.update()
        info_msg.update()
        countdown_text.update()
    
    # اتصال handler ها
    request_btn.on_click = _on_request_otp
    verify_btn.on_click = _on_verify
    resend_btn.on_click = _on_resend
    back_btn.on_click = _on_back
    
    return ft.Container(
        content=ft.Column([
            # هدر
            txt("سامانه پایش سلامت رزتاش", size=24, font=FONT_B, color=INK),
            txt("ورود ادمین", size=16, font=FONT_MED, color=TEXT_MUTED),
            
            ft.Container(height=40),
            
            # ایمیل
            txt("ایمیل:", size=13, font=FONT_MED, color=INK),
            email_field,
            
            # OTP
            otp_container,
            
            # پیام‌ها
            error_msg,
            info_msg,
            countdown_text,
            
            ft.Container(height=15),
            
            # دکمه‌ها
            request_btn,
            verify_btn,
            resend_btn,
            back_btn,
            
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0),
        alignment=ft.alignment.Alignment(0, 0),
        padding=40,
        expand=True,
    )