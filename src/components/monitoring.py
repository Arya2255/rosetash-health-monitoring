"""Shared weekly work-hours editor and periodic health-monitoring controls."""
from __future__ import annotations

import flet as ft

from data import (can_manage_employee_scanning, monitoring_settings,
                  save_monitoring_settings)
from employee_schedule import DAY_KEYS, DAY_LABELS, normalize_schedule
from theme import BORDER, DANGER, FONT, FONT_B, INK, TEXT_MUTED, txt
from components.common import card

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def monitoring_admin(app) -> bool:
    state = app.state
    return bool(state.get("logged_in") and state.get("admin_email")
                and can_manage_employee_scanning(state.get("role", "")))


class WeeklyScheduleEditor:
    def __init__(self, app, schedule, *, enabled):
        self.app = app
        self.enabled = enabled
        self.original = normalize_schedule(schedule)
        self.days = {}
        rows = []
        for day in DAY_KEYS:
            intervals = self.original.get(day) or [{"start": "08:00", "end": "16:00"}]
            checkbox = ft.Checkbox(label=DAY_LABELS[day], value=bool(self.original.get(day)),
                                   disabled=not enabled, data=f"schedule:{day}:enabled")
            fields = []
            for index, interval in enumerate(intervals):
                start = ft.TextField(label="شروع", value=interval["start"], width=104,
                                     text_size=13, disabled=not enabled or not checkbox.value,
                                     data=f"schedule:{day}:start:{index}")
                end = ft.TextField(label="پایان", value=interval["end"], width=104,
                                   text_size=13, disabled=not enabled or not checkbox.value,
                                   data=f"schedule:{day}:end:{index}")
                fields.append((start, end))
            self.days[day] = (checkbox, fields)

            def toggle(event, controls=fields):
                for pair in controls:
                    for control in pair:
                        control.disabled = not self.enabled or not event.control.value
                self.app.page.update()

            checkbox.on_change = toggle
            rows.append(ft.Column([
                checkbox,
                *[ft.Row(list(pair), wrap=True, spacing=8) for pair in fields],
            ], spacing=5))
        self.control = ft.Column([
            txt("برنامهٔ کاری هفتگی", size=14, font=FONT_B, color=INK),
            txt("ساعت‌ها به وقت ایران است. روزهای انتخاب‌نشده پایش نمی‌شوند. "
                "اگر پایان از شروع زودتر باشد، شیفت تا روز بعد ادامه دارد.",
                size=12, font=FONT, color=TEXT_MUTED),
            *rows,
        ], spacing=10)

    def value(self):
        schedule = {}
        for day, (checkbox, fields) in self.days.items():
            if checkbox.value:
                schedule[day] = [{"start": start.value or "", "end": end.value or ""}
                                 for start, end in fields]
        return normalize_schedule(schedule)


def monitoring_reason_text(employee):
    reason = employee.get("monitoring_reason")
    if employee.get("scan_paused") or reason == "paused":
        return "پایش با دستور مدیر متوقف است"
    if reason == "unconfigured" or ("weekly_schedule" in employee and not employee["weekly_schedule"]):
        return "برنامهٔ کاری ثبت نشده است"
    if reason == "outside_shift" or employee.get("scheduled_now") is False:
        return "خارج از ساعت کاری"
    if employee.get("scan_allowed") or reason == "active":
        return "پایش در ساعت کاری فعال است"
    return ""


def monitoring_interval_card(app):
    allowed = monitoring_admin(app)
    current = monitoring_settings() if allowed else None
    seconds = (current or {}).get("health_interval_s")
    minutes = str(int(seconds) // 60) if isinstance(seconds, (int, float)) else ""
    interval = ft.TextField(label="فاصلهٔ پایش سلامت — دقیقه", value=minutes,
                            hint_text="۱۰", width=250, text_size=13,
                            disabled=not allowed or current is None,
                            keyboard_type=ft.KeyboardType.NUMBER,
                            input_filter=ft.NumbersOnlyInputFilter(),
                            data="monitoring:interval")
    message = txt("" if current is not None else
                  "برای تغییر زمان پایش، پل به‌روز و حساب مدیر لازم است.",
                  size=12, font=FONT, color=TEXT_MUTED)

    def save(event):
        if not monitoring_admin(app):
            app.snack("اجازهٔ تغییر زمان پایش را ندارید")
            return
        try:
            raw = str(interval.value or "").strip().translate(_DIGITS)
            if not raw.isascii() or not raw.isdigit():
                raise ValueError
            value = int(raw)
            if not 1 <= value <= 1440:
                raise ValueError
        except (TypeError, ValueError):
            message.value = "فاصلهٔ پایش باید عددی بین ۱ تا ۱۴۴۰ دقیقه باشد"
            message.color = DANGER
            app.page.update()
            return
        ok, error = save_monitoring_settings({"actor": app.state["admin_email"],
                                              "health_interval_s": value * 60})
        message.value = ("زمان پایش ذخیره شد؛ گیتوی‌ها پس از دریافت تنظیمات اعمال می‌کنند."
                         if ok else error)
        message.color = TEXT_MUTED if ok else DANGER
        app.page.update()

    button = ft.Button("ذخیرهٔ زمان پایش", on_click=save,
                       disabled=not allowed or current is None,
                       data="monitoring:save-interval")
    return card(ft.Column([
        txt("زمان‌بندی اندازه‌گیری سلامت", size=15, font=FONT_B, color=INK),
        txt("مکان در طول شیفت از سیگنال مچ‌بند به‌روز می‌شود. اندازه‌گیری سلامت "
            "با فاصلهٔ انتخابی، برای هر گیتوی به‌ترتیب انجام می‌شود.",
            size=12, font=FONT, color=TEXT_MUTED),
        ft.Row([interval, button], wrap=True, spacing=10), message,
    ], spacing=10), pad=14)
