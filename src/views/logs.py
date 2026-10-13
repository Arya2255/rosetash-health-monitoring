# -*- coding: utf-8 -*-
"""صفحهٔ «لاگ برنامه» — مشاهدهٔ آخرین خطوط، فیلتر سطح، جستجو و خروجی zip.

لاگ‌ها فایل‌محورند (src/applog.py): هر اجرای برنامه یک فایل سشن در
پوشهٔ logs کنار برنامه می‌سازد. این صفحه فقط می‌خواند؛ چیزی را پاک
نمی‌کند. «خروجی zip» چند سشن اخیر + فایل توضیح را برای ارسال در
پشتیبانی می‌سازد — فایل کنار همان لاگ‌ها (پوشهٔ logs) نوشته می‌شود.

دسترسی: تنظیمات ← کارت «لاگ برنامه» ← «مشاهدهٔ لاگ».
"""

import asyncio
import os

import flet as ft

from theme import (
    BORDER, BRAND_RED, FONT, FONT_B, FONT_MED, INK, INFO, R_BTN, R_CARD,
    TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
import applog
from components.common import SHADOW, back_button, card, pill, section_header
from layout import filter_row, flow, is_phone, list_card, page_scroll

TAIL_LEN = 400      # چند سطر خوانده و نمایش داده می‌شود
REFRESH_S = 2       # فاصلهٔ به‌روزرسانی خودکار صفحه

LEVELS = [("all", "همه"), ("info", "اطلاعات"), ("warn", "هشدار"), ("error", "خطا")]
_LEVEL_FA = {
    "DEBUG": "اشکال‌زدایی", "INFO": "اطلاعات", "WARNING": "هشدار",
    "ERROR": "خطا", "CRITICAL": "بحرانی",
}


def _level_color(level) -> str:
    name = applog._norm_level(level)
    if name in ("ERROR", "CRITICAL"):
        return BRAND_RED
    if name == "WARNING":
        return WARN
    if name == "INFO":
        return INFO
    return TEXT_MUTED


def _line_row(entry) -> ft.Row:
    """یک سطر لاگ — نقطهٔ سطح، متن (قابل انتخاب)، برچسب سطح و ساعت."""
    level = entry.get("level")
    color = _level_color(level)
    label = _LEVEL_FA.get(applog._norm_level(level), str(level or "—"))
    ts = str(entry.get("ts") or "")
    short = ts[11:] if len(ts) > 11 else "—"
    return ft.Row([
        ft.Container(width=6, height=6, border_radius=3, bgcolor=color,
                     margin=ft.Margin.only(top=5)),
        ft.Container(
            content=txt(entry.get("msg") or "", size=12, font=FONT,
                        color=TEXT_MAIN, selectable=True),
            expand=True,
        ),
        txt(label, size=10, font=FONT_MED, color=color),
        txt(short, size=10, font=FONT, color=TEXT_MUTED,
            tooltip=ts or None),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)


def _fmt_bytes(n) -> str:
    kb = (n or 0) / 1024.0
    if kb >= 1024:
        return fa_num(round(kb / 1024.0, 1)) + " مگابایت"
    return fa_num(round(kb)) + " کیلوبایت"


def export_logs(app):
    """خروجی zip از سشن‌های اخیر — کارت تنظیمات هم از همین استفاده می‌کند."""
    path, n, size = applog.export_zip()
    if not path:
        app.snack("خروجی ساخته نشد — هنوز خطی در لاگ ثبت نشده است")
        return None
    app.snack(f"خروجی ساخته شد — {fa_num(n)} فایل، {_fmt_bytes(size)} — "
              f"{os.path.basename(path)}")
    return path


def logs_view(app):
    state = app.state
    gen = state.get("logs_gen", 0) + 1
    state["logs_gen"] = gen
    state.setdefault("logs_level", "all")
    state.setdefault("logs_search", "")
    phone = is_phone(app)

    st = applog.stats()

    def _fetch():
        lv = state.get("logs_level", "all")
        return applog.tail(
            limit=TAIL_LEN,
            level=(None if lv == "all" else lv),
            search=state.get("logs_search", ""),
        )

    lines_col = ft.Column([], spacing=6, scroll=ft.ScrollMode.AUTO)
    count_txt = txt("", size=11, font=FONT, color=TEXT_MUTED)

    def _fill():
        items = _fetch()
        if items:
            lines_col.controls = [_line_row(e) for e in items]
        else:
            msg = ("چیزی با این فیلتر/جستجو پیدا نشد"
                   if (state.get("logs_search") or
                       state.get("logs_level", "all") != "all")
                   else "هنوز خطی در لاگ ثبت نشده — با شروع کارکرد برنامه پر می‌شود")
            lines_col.controls = [ft.Container(
                height=80, alignment=ft.alignment.Alignment(0, 0),
                content=txt(msg, size=13, font=FONT, color=TEXT_MUTED))]
        count_txt.value = f"{fa_num(len(items))} خط — تازه‌ترین خط بالا"
        return items

    # ── فیلتر سطح (قرص‌ها) ──
    pill_refs = {}

    def _set_level(key):
        state["logs_level"] = key
        for k, (cp, tp) in pill_refs.items():
            active = (k == key)
            cp.bgcolor = INK if active else WHITE
            cp.border = ft.Border.all(1, INK if active else BORDER)
            tp.color = WHITE if active else TEXT_MAIN
        _fill()
        app.page.update()

    pills = []
    for key, label in LEVELS:
        cp, tp = pill(label, active=(state.get("logs_level") == key),
                      on_click=lambda e, k=key: _set_level(k))
        pill_refs[key] = (cp, tp)
        pills.append(cp)

    search = ft.TextField(
        hint_text="جستجو در خطوط…", prefix_icon=ft.Icons.SEARCH,
        width=None if phone else 260, height=44, text_size=13,
        value=state.get("logs_search", ""),
        on_change=lambda e: (state.update({"logs_search": e.control.value}),
                             _fill(), app.page.update()),
    )

    refresh_btn = ft.IconButton(
        ft.Icons.REFRESH, tooltip="به‌روزرسانی", icon_color=INK,
        on_click=lambda e: (_fill(), app.page.update()),
        style=ft.ButtonStyle(bgcolor=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
    )
    export_btn = ft.Button(
        "خروجی zip", icon=ft.Icons.DOWNLOAD, height=40,
        on_click=lambda e: export_logs(app),
        style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
    )

    header = ft.Row([
        back_button(lambda e: app.go("settings")),
        ft.Container(content=section_header(
            "لاگ برنامه",
            "رخدادهای خود برنامه برای عیب‌یابی — به‌روزرسانی هر ۲ ثانیه",
        ), expand=True),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    cur_name = os.path.basename(st["current"]) if st.get("current") else "—"
    stats_txt = txt(
        f"{fa_num(st['sessions'])} سشن ذخیره‌شده — {_fmt_bytes(st['bytes'])}"
        f" — سشن جاری: {cur_name}",
        size=12, font=FONT, color=TEXT_MUTED)
    dir_txt = txt("پوشهٔ لاگ: " + str(st["dir"]), size=11, font=FONT,
                  color=TEXT_MUTED, selectable=True)

    # نکته: Row(wrap=True) فرزند expand=True را نمی‌پذیرد (خطای Flutter)؛
    # پس نوار دکمه‌ها جدا و ردیف اصلی با کمک flow ساخته می‌شود.
    info_row = flow(app, [
        ft.Container(content=ft.Column([stats_txt, dir_txt], spacing=1),
                     expand=True),
        ft.Row([refresh_btn, export_btn], spacing=8, tight=True),
    ], spacing=13, row_kw={"vertical_alignment": ft.CrossAxisAlignment.CENTER})

    controls = filter_row(app, pills, trailing=search)

    _count_holder = ft.Row([ft.Container(expand=True), count_txt],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER)

    lines_card = ft.Container(
        content=ft.Column([
            _count_holder,
            ft.Divider(height=1, thickness=1, color=BORDER),
            ft.Container(content=lines_col, expand=True,
                         padding=ft.Padding.only(top=8)),
        ], spacing=6, expand=True),
        padding=ft.Padding.all(12),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        expand=True,
    )
    list_card(app, lines_card, h=460)

    _fill()

    async def _loop():
        while state.get("view") == "logs" and state.get("logs_gen") == gen:
            try:
                _fill()
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(REFRESH_S)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    return page_scroll(app, [header, info_row, controls, lines_card])