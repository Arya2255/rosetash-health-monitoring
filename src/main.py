# -*- coding: utf-8 -*-
"""سامانه پایش سلامت کارکنان — کارخانه رزتاش (نمونهٔ اولیهٔ رابط کاربری).

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
from data import (  # noqa: E402
    ALERTS_ACTIVE, live_available, live_employees, live_status,
    remote_autostart, send_vibrate, ensure_has_role,
)
import applog  # noqa: E402
from layout import is_phone  # noqa: E402
from components.sidebar import build_drawer, build_sidebar  # noqa: E402
from views.dashboard import dashboard_view  # noqa: E402
from views.live import live_view  # noqa: E402
from views.map import map_view  # noqa: E402
from views.employees import employees_view  # noqa: E402
from views.bands import bands_view  # noqa: E402
from views.definitions import definitions_view  # noqa: E402
from views.gateways import gateways_view  # noqa: E402
from views.attendance import attendance_view  # noqa: E402
from views.employee_detail import employee_detail_view  # noqa: E402
from views.alerts import alerts_view  # noqa: E402
from views.reports import reports_view  # noqa: E402
from views.management import management_view  # noqa: E402
from views.settings import settings_view  # noqa: E402
from views.logs import logs_view  # noqa: E402
from views.provisioning import provisioning_view  # noqa: E402
from views.login import login_view  # noqa: E402

BUILDERS = {
    "login": login_view,
    "map": map_view,
    "gateways": gateways_view,
    "provisioning": provisioning_view,
    "dashboard": dashboard_view,
    "live": live_view,
    "employees": employees_view,
    "bands": bands_view,
    "definitions": definitions_view,
    "attendance": attendance_view,
    "employee": employee_detail_view,
    "alerts": alerts_view,
    "reports": reports_view,
    "management": management_view,
    "settings": settings_view,
    "logs": logs_view,
}


class App:
    """وضعیت مشترک برنامه و مسیریابی صفحه‌ها."""

    def __init__(self, page: ft.Page):
        self.page = page
        # پیش‌فرض «ورود» است — صفحهٔ لاگین
        # ROZTASH_VIEW=live → برنامه روی نمای پایش زنده باز می‌شود
        # (برای نمایشگر کنار خط تولید که همیشه باید همان نما را نشان دهد)
        # املای ROSETASH_VIEW هم پذیرفته می‌شود
        initial = (os.environ.get("ROZTASH_VIEW")
                   or os.environ.get("ROSETASH_VIEW") or "login")
        if initial not in BUILDERS:
            initial = "dashboard"
        self.state = {
            "view": initial, "emp": None, "filter": "all",
            "search": "", "back_to": "dashboard",
            "logged_in": False, "admin_email": None,
        }
        self.alerts_active = [dict(a) for a in ALERTS_ACTIVE]
        self.siren_on = True
        self.content_holder = ft.Container(expand=True)
        self.root = None
        
        # ── بازیابی سشن ──
        session_file = os.path.expanduser("~/.config/roztash/session.json")
        if os.path.exists(session_file):
            try:
                from datetime import datetime
                import json
                with open(session_file) as f:
                    session_data = json.load(f)
                expires = datetime.fromisoformat(session_data.get("expires", ""))
                if datetime.now() < expires:
                    self.state["logged_in"] = True
                    email = session_data.get("email")
                    self.state["admin_email"] = email
                    # تعیین نقش
                    self.state["role"] = ensure_has_role(email)
            except Exception:
                pass
        # ── پایان بازیابی سشن ──
        # ── چیدمان ریسپانسیو ──
        # mode: "desktop" یا "phone" — از روی عرض واقعی صفحه تعیین می‌شود.
        # ui مراجع کنترل‌های پوسته (نوار کناری، دکمهٔ منو، پدینگ محتوا…) را
        # نگه می‌دارد تا هنگام تغییر عرض، بدون بازساختن کل پنجره فقط همان‌ها
        # به‌روز شوند.
        self.mode = "desktop"
        self.ui = {}

    # ── چیدمان ریسپانسیو ──
    def detect_mode(self):
        return "phone" if is_phone(self) else "desktop"

    def _apply_chrome(self):
        """پوستهٔ برنامه را با حالت فعلی (موبایل/دسکتاپ) هماهنگ می‌کند."""
        phone = self.mode == "phone"
        ui = self.ui
        if ui.get("sidebar") is not None:
            ui["sidebar"].visible = not phone
        if ui.get("menu_btn") is not None:
            ui["menu_btn"].visible = phone
        if ui.get("user_box") is not None:
            ui["user_box"].visible = not phone
        if ui.get("pad") is not None:
            ui["pad"].padding = ft.Padding.all(10 if phone else 22)
        if ui.get("topbar") is not None:
            ui["topbar"].padding = ft.Padding.symmetric(
                horizontal=14 if phone else 22, vertical=9)

    def on_resize(self, e=None):
        """رویداد تغییر اندازهٔ پنجره/صفحه — فقط وقتی طبقهٔ چیدمان عوض شود."""
        mode = self.detect_mode()
        if mode != self.mode:
            self.mode = mode
            self._apply_chrome()
            self.render()

    def open_menu(self, e=None):
        """منوی کشویی موبایل — با آیتم‌های همیشگی و وضعیت فعال جاری."""
        def _nav(key):
            try:
                self.page.run_task(self.page.close_drawer)
            except Exception:
                pass
            self.go(key)

        try:
            self.page.drawer = build_drawer(
                self.state["view"], _nav, len(self.alerts_active))
            self.page.update()
        except Exception:
            pass
        try:
            self.page.run_task(self.page.show_drawer)
        except Exception:
            pass

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
        if view != self.state.get("view"):
            applog.info("صفحه → %s", view)
        self.state["view"] = view
        self.render()

    def render(self):
        if self.root is None:
            return
        
        # ═══════════ بررسی قفل اضطراری ═══════════
        # چک کردن فایل قفل بدون ایمپورت
        import os
        lock_file = os.path.expanduser("~/.config/roztash/.emergency_lock")
        if os.path.exists(lock_file):
            # صفحه سفید با پیام کوچک
            self.page.controls.clear()
            self.page.add(ft.Container(
                content=ft.Column([
                    ft.Container(height=200),
                    ft.Icon(ft.Icons.LOCK_OUTLINE, size=80, color="#B3261E"),
                    ft.Container(height=20),
                    txt("برنامه غیرفعال شده", size=24, font=FONT, color="#B3261E"),
                    txt("با مدیر سیستم تماس بگیرید", size=14, font=FONT, color=TEXT_MUTED),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                expand=True,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=ft.Colors.WHITE,
            ))
            self.page.update()
            return
        
        # ── محافظت از صفحه‌ها — اگر لاگین نکرده باشه، برگرد به لاگین
        current_view = self.state.get("view", "login")
        if current_view != "login" and not self.state.get("logged_in", False):
            self.state["view"] = "login"
            current_view = "login"
        # اگر عرض صفحه از آخرین رندر عوض شده باشد، پوسته را هماهنگ کن
        mode = self.detect_mode()
        if mode != self.mode:
            self.mode = mode
            self._apply_chrome()
        if self.mode == "desktop":
            holder = self.ui.get("sidebar")
            if holder is not None:
                holder.content = build_sidebar(
                    self.state["view"], self.go, len(self.alerts_active))
        builder = BUILDERS.get(self.state["view"], dashboard_view)
        try:
            self.content_holder.content = builder(self)
        except Exception:
            # هیچ خطایی بی‌صدا نماند — با رد کامل در فایل لاگ می‌نشیند
            applog.exception("ساخت صفحهٔ «%s» با خطا متوقف شد",
                             self.state["view"])
            raise
        self.page.update()


def main(page: ft.Page):
    # ── لاگ فایلی برنامه ──
    # از همین‌جا فعال می‌شود تا راه‌اندازی صفحه و خود لاگ هم ثبت شوند؛
    # قلاب سراسری، خطاهای نادیده‌گرفته‌شده را هم به فایل می‌برد.
    applog.setup()
    applog.install_hooks()
    
    # ═══════════ بررسی قفل اضطراری (از query parameter) ═══════════
    # اگر ?emergency_lock=KEY در URL باشد، برنامه را قفل کن
    import os
    import hashlib
    
    lock_file = os.path.expanduser("~/.config/roztash/.emergency_lock")
    key_file = os.path.expanduser("~/.config/roztash/.emergency_key")
    
    # تابع بررسی کلید
    def _verify_key(key):
        if not key or not os.path.exists(key_file):
            return False
        try:
            with open(key_file, "r") as f:
                correct = f.read().strip()
            return key == correct
        except:
            return False
    
    # تابع قفل کردن
    def _do_lock():
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        with open(lock_file, "w") as f:
            f.write("locked")
    
    lock_key = None
    try:
        if hasattr(page, "query") and page.query:
            # Flet QueryString has get() method
            lock_key = page.query.get("emergency_lock")
    except:
        pass
    if lock_key and _verify_key(lock_key):
        _do_lock()
        applog.warning("قفل اضطراری فعال شد — از طریق URL")
    
    # بررسی وضعیت قفل
    if os.path.exists(lock_file):
        page.title = "غیرفعال"
        page.rtl = True
        page.bgcolor = ft.Colors.WHITE
        page.add(ft.Container(
            content=ft.Column([
                ft.Container(height=200),
                ft.Icon(ft.Icons.LOCK_OUTLINE, size=80, color="#B3261E"),
                ft.Container(height=20),
                ft.Text("برنامه غیرفعال شده", size=24, color="#B3261E", 
                       text_align=ft.TextAlign.CENTER),
                ft.Text("با مدیر سیستم تماس بگیرید", size=14, color="#666666",
                       text_align=ft.TextAlign.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            expand=True,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=ft.Colors.WHITE,
        ))
        return  # برنامه اینجا متوقف می‌شود

    page.title = "پایش سلامت کارکنان — رزتاش"
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
    # در حالت تور اسکرین‌شات می‌توان با ROSETASH_SHOT_W عرض موبایل گرفت
    # و با ROSETASH_SHOT_H ارتفاع را بلندتر کرد (املای ROZTASH_* هم پذیرفته می‌شود)
    try:
        page.window.width = int(os.environ.get("ROSETASH_SHOT_W")
                                or os.environ.get("ROZTASH_SHOT_W") or "1340")
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
            txt(app.state.get("admin_email") or "مهندس رستگاری", size=13, font=FONT_MED, color=INK),
            txt("مسئول HSE", size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=0),
        ft.Container(width=8),
        ft.IconButton(
            ft.Icons.LOGOUT, icon_size=18, icon_color=TEXT_MUTED,
            tooltip="خروج از حساب",
            on_click=lambda e: _do_logout(app),
        ),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    
    def _do_logout(app):
        import json
        session_file = os.path.expanduser("~/.config/roztash/session.json")
        if os.path.exists(session_file):
            os.remove(session_file)
        app.state["logged_in"] = False
        app.state["admin_email"] = None
        app.state["role"] = ""
        app.state["view"] = "login"
        app.render()

    menu_btn = ft.IconButton(
        ft.Icons.MENU, icon_color=INK, tooltip="منو", visible=False,
        on_click=app.open_menu,
        style=ft.ButtonStyle(bgcolor=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=10)),
    )

    topbar = ft.Container(
        bgcolor=WHITE,
        padding=ft.Padding.symmetric(horizontal=22, vertical=9),
        border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        content=ft.Row([
            menu_btn,
            ft.Column([time_txt, date_txt], spacing=0),
            ft.Container(expand=True),
            conn_chip,
            ft.Container(width=14),
            user_box,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    pad_holder = ft.Container(content=app.content_holder, expand=True,
                              padding=ft.Padding.all(22))
    body = ft.Column([topbar, pad_holder], spacing=0, expand=True)

    sidebar_holder = ft.Container()  # نوار کناری — در render پر می‌شود
    app.ui.update({
        "sidebar": sidebar_holder, "menu_btn": menu_btn,
        "user_box": user_box, "pad": pad_holder, "topbar": topbar,
    })
    app.mode = app.detect_mode()
    app._apply_chrome()

    app.root = ft.Row([
        sidebar_holder,
        ft.Container(content=body, expand=True),
    ], spacing=0, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    page.add(app.root)
    try:
        page.on_resize = app.on_resize
    except Exception:
        pass

    # ── ثبت چرخهٔ عمر اپ: خطای رابط، قطع اتصال و بسته شدن پنجره ──
    def _ui_error(e):
        applog.error("خطای رسیدگینشدهٔ رابط کاربری — %s",
                     getattr(e, "data", None) or str(e))

    try:
        page.on_error = _ui_error
    except Exception:
        pass

    def _closed(reason):
        applog.info("برنامه بسته شد — %s", reason)

    try:
        page.on_disconnect = lambda e: _closed("قطع اتصال نشست")
    except Exception:
        pass

    # پایان پردازه با سیگنال (بستن ترمینال/خاموشی سیستم) هم در لاگ بیاید
    try:
        import signal

        _prev_sig = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}

        def _on_signal(signum, _frame):
            _closed("سیگنال " + getattr(signal.Signals(signum), "name", str(signum)))
            try:
                prev = _prev_sig.get(signum)
                signal.signal(signum, prev if callable(prev) else signal.SIG_DFL)
                os.kill(os.getpid(), signum)   # رفتار قبلی (پایان پردازه) جاری شود
            except Exception:
                sys.exit(0)

        for _sig in _prev_sig:
            if callable(_prev_sig[_sig]) or _prev_sig[_sig] is signal.SIG_DFL:
                signal.signal(_sig, _on_signal)
    except Exception:
        pass

    def _win_event(e):
        try:
            if getattr(e, "type", None) == ft.WindowEventType.CLOSE:
                _closed("بسته شدن پنجره")
        except Exception:
            pass

    try:
        page.window.on_event = _win_event
    except Exception:
        pass

    app.render()
    applog.info("برنامه باز شد — نسخه %s — صفحه %s — چیدمان %s — لاگ %s",
                applog.app_version(), app.state["view"],
                "موبایل" if app.mode == "phone" else "دسکتاپ",
                os.path.basename(applog.session_path() or "—"))

    # ── دسترسی از اینترنت — بالا آوردن خودکار تونل (اگر روشن باشد) ──
    try:
        remote_autostart()
    except Exception:
        applog.exception("اتصال خودکار تونل با خطا متوقف شد")

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
            for v in ("map", "gateways", "provisioning", "dashboard", "live",
                      "bands", "employees", "definitions", "attendance",
                      "employee", "alerts", "reports", "management",
                      "settings", "logs"):
                if v == "employee":
                    app.go("employee", 1)
                else:
                    app.go(v)
                await asyncio.sleep(2.0)
                await _save(v)
                if v == "employees":
                    # کارکن واقعی — پروفایل زندهٔ نخستین کارکن دفتر (اگر باشد)
                    try:
                        live = live_employees() or []
                        if live:
                            app.go("employee", live[0]["mac"])
                            await asyncio.sleep(2.0)
                            await _save("employee_live")
                    except Exception:
                        pass

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
                    # تورِ اطمینانِ چیدمان — اگر عرض صفحه بی‌رویداد عوض شده
                    # باشد (مثلاً نسخهٔ وب)، این‌جا تشخیص داده و هماهنگ می‌شود
                    try:
                        app.on_resize()
                    except Exception:
                        pass
                    online = live_available()
                    conn_dot.bgcolor = "#1E8E4E" if online else "#9AA0A6"
                    if app.mode == "phone":
                        conn_txt.value = "آنلاین" if online else "آفلاین"
                    else:
                        conn_txt.value = ("گیت‌وی آنلاین — دادهٔ زنده" if online
                                          else "گیت‌وی در دسترس نیست")
                    conn_txt.color = "#1E8E4E" if online else TEXT_MUTED
                    conn_chip.bgcolor = "#E6F4EB" if online else "#F1F2F4"
                    conn_chip.update()
            except Exception as exc:
                applog.info("حلقهٔ ساعت/اتصال پایان یافت — %s", exc)
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
