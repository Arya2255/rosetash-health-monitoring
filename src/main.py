# -*- coding: utf-8 -*-
"""سامانه پایش سلامت کارکنان — کارخانه روزتاش (نمونهٔ اولیهٔ رابط کاربری).

اجرا:
    uv run flet run            (دسکتاپ)
    uv run flet run --web      (مرورگر)
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flet as ft  # noqa: E402

from theme import (  # noqa: E402
    BORDER, FONT, FONT_MED, FONTS, INK, PAGE_BG, TEXT_MAIN, TEXT_MUTED, WHITE,
    fa_clock, fa_date, txt,
)
from data import ALERTS_ACTIVE, live_available, live_status, send_vibrate  # noqa: E402
from components.sidebar import build_sidebar  # noqa: E402
from views.dashboard import dashboard_view  # noqa: E402
from views.live import live_view  # noqa: E402
from views.employees import employees_view  # noqa: E402
from views.attendance import attendance_view  # noqa: E402
from views.employee_detail import employee_detail_view  # noqa: E402
from views.alerts import alerts_view  # noqa: E402
from views.reports import reports_view  # noqa: E402
from views.management import management_view  # noqa: E402
from views.settings import settings_view  # noqa: E402

BUILDERS = {
    "dashboard": dashboard_view,
    "live": live_view,
    "employees": employees_view,
    "attendance": attendance_view,
    "employee": employee_detail_view,
    "alerts": alerts_view,
    "reports": reports_view,
    "management": management_view,
    "settings": settings_view,
}


class App:
    """وضعیت مشترک برنامه و مسیریابی صفحه‌ها."""

    def __init__(self, page: ft.Page):
        self.page = page
        # ROZTASH_VIEW=live → برنامه روی نمای پایش زنده باز می‌شود
        # (برای نمایشگر کنار خط تولید که همیشه باید همان نما را نشان دهد)
        # املای ROSETASH_VIEW هم پذیرفته می‌شود
        initial = (os.environ.get("ROZTASH_VIEW")
                   or os.environ.get("ROSETASH_VIEW") or "dashboard")
        if initial not in BUILDERS:
            initial = "dashboard"
        self.state = {
            "view": initial, "emp": None, "filter": "all",
            "search": "", "back_to": "dashboard",
        }
        self.alerts_active = [dict(a) for a in ALERTS_ACTIVE]
        self.siren_on = True
        self.content_holder = ft.Container(expand=True)
        self.root = None

    # ── اقدام‌های مشترک ──
    def snack(self, msg):
        sb = ft.SnackBar(content=ft.Text(msg, font_family=FONT), bgcolor=INK)
        try:
            self.page.show_dialog(sb)
        except Exception:
            self.page.overlay.append(sb)
            sb.open = True
            self.page.update()

    def set_siren(self, on: bool):
        self.siren_on = on
        self.snack("آژیر مرکزی فعال شد" if on else "آژیر مرکزی خاموش شد")
        if on:
            self._vibrate_present_band()
        self.render()

    def _vibrate_present_band(self):
        """هنگام روشن‌شدن آژیر، مچ‌بند کارکنِ در دید را می‌لرزاند.

        هشدار مستقیم به خود کارکن — بهترین تلاش، بی‌صدا اگر چیزی نبود.
        """
        try:
            d = live_status() or {}
            rows = d.get("bands") or d.get("health") or d.get("vitals") or []
            mac = rows[0].get("mac") if rows else ""
            if mac:
                send_vibrate(mac)
                self.snack("مچ‌بند کارکن هم به لرزش افتاد")
        except Exception:
            pass

    def close_alert(self, alert_id):
        self.alerts_active = [a for a in self.alerts_active if a["id"] != alert_id]
        self.snack("رویداد بسته شد و در تاریخچهٔ امروز ثبت گردید")
        self.render()

    # ── مسیریابی ──
    def go(self, view, emp=None):
        if view == "employee":
            self.state["emp"] = emp
        self.state["view"] = view
        self.render()

    def render(self):
        if self.root is None:
            return
        self.root.controls[0] = build_sidebar(
            self.state["view"], self.go, len(self.alerts_active))
        builder = BUILDERS.get(self.state["view"], dashboard_view)
        self.content_holder.content = builder(self)
        self.page.update()


def main(page: ft.Page):
    page.title = "پایش سلامت کارکنان — روزتاش"
    page.rtl = True
    page.padding = 0
    page.spacing = 0
    page.bgcolor = PAGE_BG
    page.fonts = FONTS
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(
        font_family=FONT,
        color_scheme=ft.ColorScheme(
            primary=INK, secondary=INK, surface=WHITE, on_surface=TEXT_MAIN,
        ),
    )

    # ── اندازهٔ پیش‌فرض پنجره (دسکتاپ) ──
    # در حالت تور اسکرین‌شات می‌توان با ROSETASH_SHOT_H ارتفاع را بلندتر گرفت
    # (املای ROZTASH_SHOT_H هم پذیرفته می‌شود)
    try:
        page.window.width = 1340
        page.window.height = int(os.environ.get("ROSETASH_SHOT_H")
                                 or os.environ.get("ROZTASH_SHOT_H") or "720")
    except Exception:
        pass

    app = App(page)

    # ── نوار بالایی ──
    time_txt = txt("", size=16, font=FONT_MED, color=INK)
    date_txt = txt("", size=11, font=FONT, color=TEXT_MUTED)
    # نشان اتصال — از وضعیت واقعی پل محلی پر می‌شود
    conn_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor="#9AA0A6")
    conn_txt = txt("در حال بررسی گیت‌وی…", size=12, font=FONT_MED, color=TEXT_MUTED)
    conn_chip = ft.Container(
        content=ft.Row([conn_dot, conn_txt], spacing=6, tight=True),
        bgcolor="#F1F2F4", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
    )
    user_box = ft.Row([
        ft.CircleAvatar(radius=16, bgcolor="#E9EBEE",
                        content=ft.Icon(ft.Icons.PERSON, size=15, color=TEXT_MAIN)),
        ft.Column([
            txt("مهندس رستگاری", size=13, font=FONT_MED, color=INK),
            txt("مسئول HSE", size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=0),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    topbar = ft.Container(
        bgcolor=WHITE,
        padding=ft.Padding.symmetric(horizontal=22, vertical=9),
        border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        content=ft.Row([
            ft.Column([time_txt, date_txt], spacing=0),
            ft.Container(expand=True),
            conn_chip,
            ft.Container(width=14),
            user_box,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    body = ft.Column([
        topbar,
        ft.Container(content=app.content_holder, expand=True,
                     padding=ft.Padding.all(22)),
    ], spacing=0, expand=True)

    app.root = ft.Row([
        ft.Container(),  # نوار کناری — در render پر می‌شود
        ft.Container(content=body, expand=True),
    ], spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    page.add(app.root)
    app.render()

    # ── تورِ اسکرین‌شات خودکار (فقط در حالت توسعه) ──
    shot_dir = (os.environ.get("ROSETASH_SHOT_DIR")
                or os.environ.get("ROZTASH_SHOT_DIR"))
    if shot_dir and hasattr(page, "run_task"):
        page.enable_screenshots = True

        async def _save(name):
            png = await page.take_screenshot()
            with open(os.path.join(shot_dir, name + ".png"), "wb") as fh:
                fh.write(png)

        async def shot_tour():
            await asyncio.sleep(3)
            for v in ("dashboard", "live", "employees", "attendance", "employee",
                      "alerts", "reports", "management", "settings"):
                if v == "employee":
                    app.go("employee", 1)
                else:
                    app.go(v)
                await asyncio.sleep(2.0)
                await _save(v)

        page.run_task(shot_tour)

    # ── ساعت زنده ──
    async def clock_loop():
        last_check = 0.0
        while True:
            try:
                time_txt.value = fa_clock()
                date_txt.value = fa_date()
                time_txt.update()
                date_txt.update()
                # نشان اتصال هر چند ثانیه از پل محلی تازه می‌شود
                now = time.time()
                if now - last_check >= 5:
                    last_check = now
                    online = live_available()
                    conn_dot.bgcolor = "#1E8E4E" if online else "#9AA0A6"
                    conn_txt.value = ("گیت‌وی آنلاین — دادهٔ زنده" if online
                                      else "گیت‌وی در دسترس نیست")
                    conn_txt.color = "#1E8E4E" if online else TEXT_MUTED
                    conn_chip.bgcolor = "#E6F4EB" if online else "#F1F2F4"
                    conn_chip.update()
            except Exception:
                return
            await asyncio.sleep(1)

    if hasattr(page, "run_task"):
        page.run_task(clock_loop)
    else:
        time_txt.value = fa_clock()
        date_txt.value = fa_date()
        page.update()


if __name__ == "__main__":
    ft.run(main)
