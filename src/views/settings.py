# -*- coding: utf-8 -*-
"""تنظیمات — پشتیبان‌گیری، آستانه‌های هشدار، کاربران و دربارهٔ سامانه."""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt,
)
from components.common import card, kv_row
from views.logs import export_logs  # noqa: E402


def _perm_chip(label):
    return ft.Container(
        content=txt(label, size=11, font=FONT_MED, color=INK),
        bgcolor="#EFF1F3", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
    )


def _user_row(name, role, perm):
    return ft.Row([
        ft.CircleAvatar(radius=15, bgcolor="#E9EBEE",
                        content=ft.Icon(ft.Icons.PERSON, size=14, color=INK)),
        ft.Column([
            txt(name, size=13, font=FONT_MED, color=INK),
            txt(role, size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=1, expand=True),
        _perm_chip(perm),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def settings_view(app):
    # ── پشتیبان‌گیری ──
    backup_card = card(ft.Column([
        txt("پشتیبان‌گیری", size=15, font=FONT_B, color=INK),
        ft.Switch(label="پشتیبان‌گیری ابری روزانه", value=True,
                  on_change=lambda e: app.snack("تنظیم پشتیبان‌گیری ذخیره شد")),
        ft.Row([
            txt("ساعت اجرا", size=13, font=FONT, color=TEXT_MUTED),
            ft.Container(expand=True),
            ft.Dropdown(
                width=120, text_size=13, value="23:00",
                options=[ft.dropdown.Option(key="23:00", text="۲۳:۰۰"),
                         ft.dropdown.Option(key="14:00", text="۱۴:۰۰"),
                         ft.dropdown.Option(key="02:00", text="۰۲:۰۰")],
            ),
        ]),
        ft.Switch(label="پشتیبان‌گیری روی حافظهٔ USB", value=False,
                  on_change=lambda e: app.snack("تنظیم پشتیبان USB ذخیره شد")),
        ft.Row([
            ft.OutlinedButton(
                "پشتیبان‌گیری فوری", icon=ft.Icons.CLOUD_UPLOAD, height=40,
                style=ft.ButtonStyle(color=INK,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.snack("نسخهٔ پشتیبان ساخته شد — نمونه"),
            ),
        ]),
        txt("آخرین نسخهٔ پشتیبان: امروز ۲۳:۰۰ — موفق", size=12, font=FONT, color=TEXT_MUTED),
    ], spacing=8), pad=18)

    # ── آستانه‌های هشدار ──
    def th(label, value):
        return ft.TextField(label=label, value=value, width=132, text_size=13)

    thresholds_card = card(ft.Column([
        txt("آستانه‌های هشدار", size=15, font=FONT_B, color=INK),
        ft.Row([
            th("ضربان بالا", "120"),
            th("ضربان پایین", "50"),
            th("کمینهٔ اکسیژن (٪)", "92"),
        ], spacing=10),
        ft.Row([
            txt("حساسیت تشخیص سقوط", size=13, font=FONT, color=TEXT_MUTED),
            ft.Container(expand=True),
            ft.Dropdown(
                width=120, text_size=13, value="mid",
                options=[ft.dropdown.Option(key="low", text="کم"),
                         ft.dropdown.Option(key="mid", text="متوسط"),
                         ft.dropdown.Option(key="high", text="زیاد")],
            ),
        ]),
        ft.Row([
            ft.Button(
                "ذخیرهٔ آستانه‌ها", height=40,
                style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.snack("آستانه‌های هشدار ذخیره شد — نمونه"),
            ),
        ]),
        txt("اعمال روی همهٔ مچ‌بندها — تخصیص به واحد در فاز ۲", size=11,
            font=FONT, color=TEXT_MUTED),
    ], spacing=10), pad=18)

    # ── کاربران و دسترسی ──
    users_card = card(ft.Column([
        txt("کاربران و سطوح دسترسی", size=15, font=FONT_B, color=INK),
        _user_row("مهندس رستگاری", "مسئول HSE", "دسترسی کامل"),
        _user_row("مهندس کاظمی", "مدیر کارخانه", "فقط گزارش‌ها"),
        _user_row("سرشیفت تولید", "سرشیفت", "هشدارها و حضور"),
        ft.Row([
            ft.OutlinedButton(
                "افزودن کاربر", icon=ft.Icons.PERSON_ADD, height=40,
                style=ft.ButtonStyle(color=INK,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.snack("فرم افزودن کاربر — فاز ۲"),
            ),
        ]),
    ], spacing=10), pad=18)

    # ── دربارهٔ سامانه ──
    about_card = card(ft.Column([
        txt("دربارهٔ سامانه", size=15, font=FONT_B, color=INK),
        kv_row("نسخه", "۰٫۱ — نمونهٔ اولیهٔ رابط کاربری"),
        kv_row("برند", "موتوسل — کارخانه روزتاش"),
        kv_row("فناوری", "Flet — دسکتاپ اتاق HSE"),
        kv_row("وضعیت داده‌ها", "نمایشی — اتصال به بک‌اند در فاز ۲"),
        txt("مستندات کامل طراحی در فایل DESIGN.md مخزن پروژه", size=11,
            font=FONT, color=TEXT_MUTED),
    ], spacing=8), pad=18)

    # ── لاگ برنامه ──
    logs_card = card(ft.Column([
        txt("لاگ برنامه", size=15, font=FONT_B, color=INK),
        txt("رخدادها و خطاهای خود برنامه برای عیب‌یابی — دادهٔ سلامت در لاگ "
            "نوشته نمی‌شود.", size=12, font=FONT, color=TEXT_MUTED),
        ft.Row([
            ft.OutlinedButton(
                "مشاهدهٔ لاگ", icon=ft.Icons.ARTICLE_OUTLINED, height=40,
                style=ft.ButtonStyle(color=INK,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.go("logs"),
            ),
            ft.OutlinedButton(
                "خروجی zip", icon=ft.Icons.DOWNLOAD, height=40,
                style=ft.ButtonStyle(color=INK,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: export_logs(app),
            ),
        ], spacing=10, wrap=True, run_spacing=8),
    ], spacing=8), pad=18)

    return ft.Column([
        ft.Row([
            ft.Container(expand=True, content=ft.Column([backup_card, users_card], spacing=14)),
            ft.Container(expand=True, content=ft.Column([thresholds_card, about_card, logs_card], spacing=14)),
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
    ], scroll=ft.ScrollMode.AUTO, expand=True)
