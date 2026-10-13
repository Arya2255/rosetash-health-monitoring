# -*- coding: utf-8 -*-
"""تنظیمات — پشتیبان‌گیری، آستانه‌های هشدار، کاربران و دربارهٔ سامانه."""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt,
)
from components.common import card, kv_row
from views.logs import export_logs  # noqa: E402
from layout import flow
from data import (
    remote_add_email, remote_down, remote_remove_email,
    remote_set_autostart, remote_setup, remote_status,
)


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
        ], spacing=10, wrap=True, run_spacing=10),
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

    # ── دسترسی از اینترنت — تونل کلادفلر و قفل ورود ایمیلی ──
    rs = remote_status() or {}
    if rs.get("running") and rs.get("locked"):
        net_color = "#1E8E4E"
    elif rs.get("running"):
        net_color = "#B26900"
    else:
        net_color = "#9AA0A6"

    def _net_setup(e=None):
        ok, msg = remote_setup()
        app.snack(msg)
        app.render()

    def _net_down(e=None):
        ok, msg = remote_down()
        app.snack(msg)
        app.render()

    def _net_auto(e):
        ok, msg = remote_set_autostart(bool(e.control.value))
        app.snack(msg)

    def _net_add(e=None):
        ok, msg = remote_add_email(net_new_email.value or "")
        app.snack(msg)
        if ok:
            net_new_email.value = ""
            app.render()

    def _net_rm(addr):
        def _do(e=None):
            ok, msg = remote_remove_email(addr)
            app.snack(msg)
            app.render()
        return _do

    def _net_copy(e=None):
        url = rs.get("url") or ""
        try:
            svc = getattr(app.page, "services", None)
            if svc is not None and url:
                clip = ft.Clipboard()
                svc.append(clip)
                clip.set(url)
                app.snack("آدرس کپی شد")
            else:
                app.snack("کپی خودکار ممکن نشد — آدرس را دستی انتخاب کن")
        except Exception:
            app.snack("کپی خودکار ممکن نشد — آدرس را دستی انتخاب کن")

    net_new_email = ft.TextField(hint_text="ایمیل ادمین", text_size=13,
                                 expand=True)

    net_email_rows = [
        ft.Row([
            ft.Icon(ft.Icons.MAIL_OUTLINE, size=16, color=INK),
            ft.Container(content=txt(addr, size=13, font=FONT, color=INK),
                         expand=True),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16,
                          icon_color="#B3261E", tooltip="حذف",
                          on_click=_net_rm(addr)),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        for addr in (rs.get("emails") or [])
    ] or [txt("هنوز ایمیلی تعریف نشده — اولین ایمیل ادمین را اضافه کن.",
              size=12, font=FONT, color=TEXT_MUTED)]

    net_card = card(ft.Column([
        txt("دسترسی از اینترنت", size=15, font=FONT_B, color=INK),
        txt("پنل از بیرون با قفل ایمیلی کلادفلر باز می‌شود — فقط "
            "ایمیل‌های زیر کد ورود می‌گیرند.",
            size=12, font=FONT, color=TEXT_MUTED),
        ft.Row([
            ft.Container(width=8, height=8, border_radius=4,
                         bgcolor=net_color),
            txt("وضعیت: " + (rs.get("label") or "—"), size=13,
                font=FONT_MED, color=INK),
            ft.Container(expand=True),
            ft.IconButton(ft.Icons.REFRESH, icon_size=18, icon_color=INK,
                          tooltip="به‌روزرسانی",
                          on_click=lambda e: app.render()),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        txt(rs.get("detail") or "", size=11, font=FONT, color=TEXT_MUTED),
        ft.Row([
            ft.Button("راه‌اندازی و اتصال", icon=ft.Icons.LINK, height=38,
                      style=ft.ButtonStyle(
                          bgcolor=INK, color=WHITE,
                          shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                      on_click=_net_setup),
            ft.OutlinedButton("قطع اتصال", icon=ft.Icons.LINK_OFF, height=38,
                              style=ft.ButtonStyle(
                                  color=INK,
                                  shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                              on_click=_net_down),
        ], spacing=10, wrap=True, run_spacing=8),
        ft.Switch(label="اتصال خودکار هنگام اجرای برنامه",
                  value=bool(rs.get("auto_start")), on_change=_net_auto),
        ft.Divider(height=1, color=BORDER),
        ft.Row([
            txt("آدرس پنل:", size=12, font=FONT, color=TEXT_MUTED),
            ft.Container(content=ft.Text(rs.get("url") or "—", size=13,
                                         font_family=FONT, color=INK,
                                         selectable=True), expand=True),
            ft.IconButton(ft.Icons.COPY, icon_size=16, icon_color=INK,
                          tooltip="کپی آدرس", on_click=_net_copy),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Divider(height=1, color=BORDER),
        txt("ایمیل‌های مجاز ورود", size=13, font=FONT_MED, color=INK),
        *net_email_rows,
        ft.Row([
            net_new_email,
            ft.Button("افزودن", icon=ft.Icons.PERSON_ADD, height=38,
                      style=ft.ButtonStyle(
                          bgcolor=INK, color=WHITE,
                          shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                      on_click=_net_add),
        ], spacing=8),
        txt("هر تغییر بلافاصله روی کلادفلر اعمال می‌شود؛ کد ورود به "
            "همین ایمیل‌ها فرستاده می‌شود.",
            size=11, font=FONT, color=TEXT_MUTED),
    ], spacing=8), pad=18)

    # ── دربارهٔ سامانه ──
    about_card = card(ft.Column([
        txt("دربارهٔ سامانه", size=15, font=FONT_B, color=INK),
        kv_row("نسخه", "۰٫۱ — نمونهٔ اولیهٔ رابط کاربری"),
        kv_row("برند", "موتوسل — کارخانه رزتاش"),
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
        flow(app, [
            ft.Container(expand=True, content=ft.Column([backup_card, net_card, users_card], spacing=14)),
            ft.Container(expand=True, content=ft.Column([thresholds_card, about_card, logs_card], spacing=14)),
        ], spacing=14, row_kw={"vertical_alignment": ft.CrossAxisAlignment.START}),
    ], scroll=ft.ScrollMode.AUTO, expand=True)
