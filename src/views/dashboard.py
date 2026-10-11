# -*- coding: utf-8 -*-
"""داشبورد لحظه‌ای — صفحهٔ اصلی رصد وضعیت کارکنان."""

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, TEXT_MUTED, WARN, WHITE,
    fa_num, txt,
)
from data import EMPLOYEES, kpis, live_summary
from components.common import card, pill, stat_card
from components.employee_card import STATUS_ORDER, employee_card
from components.alert_banner import emergency_banner

FILTERS = [
    ("all", "همه"), ("danger", "اضطراری"), ("warn", "هشدار"),
    ("ok", "عادی"), ("off", "قطع اتصال"),
]


def _ago(sec):
    """سن یک رویداد به زبان آدمیزاد."""
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{fa_num(sec)} ثانیه پیش"
    if sec < 3600:
        return f"{fa_num(sec // 60)} دقیقه پیش"
    return f"{fa_num(sec // 3600)} ساعت پیش"


def _live_strip(live):
    """نوار دادهٔ زنده — فقط وقتی پل محلی پاسخ می‌دهد."""
    if not live or not live.get("available"):
        return None
    gw = live.get("gateway") or {}
    band = live.get("band") or {}
    health = live.get("health") or {}
    online = bool(gw.get("online"))
    dot = "#1E8E4E" if online else "#9AA0A6"

    def chip(value, label):
        return ft.Column([
            txt(value, size=13, font=FONT_MED, color=INK),
            txt(label, size=10, font=FONT, color=TEXT_MUTED),
        ], spacing=1, tight=True)

    hbpm = health.get("avg")
    band_lbl = (f"حضور مچ‌بند — آنتن {band.get('rssi')}" if band
                else "حضور مچ‌بند — در دید نیست")
    hr_txt = f"{fa_num(round(hbpm))} ضربه در دقیقه" if hbpm is not None else "—"
    hr_lbl = (f"آخرین ضربان — {_ago(health.get('age_s'))}" if hbpm is not None
              else "آخرین ضربان")

    # با چند گیت‌وی یا چند مچ‌بند، چیپ‌ها شمارشی می‌شوند
    n_gw = live.get("gateways_count") or 0
    n_band = live.get("bands_count") or 0
    if n_gw > 1:
        gw_chip = chip(f"{fa_num(n_gw)} گیت‌وی",
                       f"{fa_num(live.get('gateways_online') or 0)} آنلاین")
    else:
        gw_chip = chip(gw.get("gw") or "—", f"گیت‌وی — {gw.get('ip') or '—'}")
    if n_band > 1:
        band_chip = chip(f"{fa_num(n_band)} مچ‌بند", "در دید")
    else:
        band_chip = chip(band.get("mac") or "در دید نیست", band_lbl)

    return ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Container(width=8, height=8, border_radius=4, bgcolor=dot),
                txt("دادهٔ زندهٔ گیت‌وی" if online else "پل محلی — گیت‌وی آفلاین",
                    size=12, font=FONT_MED, color="#1E8E4E" if online else TEXT_MUTED),
            ], spacing=6, tight=True),
            ft.Container(width=1, height=28, bgcolor=BORDER),
            gw_chip,
            band_chip,
            chip(hr_txt, hr_lbl),
        ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=WHITE, border=ft.Border.all(1, BORDER), border_radius=12,
        padding=ft.Padding.symmetric(horizontal=14, vertical=9),
    )


def dashboard_view(app):
    state = app.state
    k = kpis()
    live = _live_strip(live_summary())
    danger_emps = [e for e in EMPLOYEES if e["status"] == "danger"]

    # ── نوار هشدار اضطراری ──
    banner = None
    if danger_emps:
        banner = emergency_banner(
            danger_emps[0],
            on_view=lambda e: app.go("employee", danger_emps[0]["id"]),
            on_siren=lambda e: app.set_siren(False),
        )

    # ── شاخص‌های کلیدی ──
    kpi_row = ft.Row([
        ft.Container(expand=True, content=stat_card(
            "حاضر در شیفت", f'{fa_num(k["present"])} از {fa_num(k["total"])}',
            "ثبت ورود از طریق مچ‌بند", ft.Icons.GROUPS, INK, "#E9EBEE")),
        ft.Container(expand=True, content=stat_card(
            "هشدار فعال", fa_num(k["warn"]),
            "نیازمند پیگیری مسئول HSE", ft.Icons.ERROR_OUTLINE, WARN, "#FCF0DC")),
        ft.Container(expand=True, content=stat_card(
            "وضعیت اضطراری", fa_num(k["danger"]),
            "سقوط — در انتظار اقدام", ft.Icons.SOS, DANGER, "#FCE7E8")),
        ft.Container(expand=True, content=stat_card(
            "میانگین ضربان", f'{fa_num(k["avg_hr"])} ضربه',
            "در دقیقه — همهٔ کارکنان", ft.Icons.MONITOR_HEART, INK, "#E9EBEE")),
    ], spacing=14)

    # ── فیلترها و جستجو ──
    grid = ft.GridView(
        expand=True, max_extent=315, child_aspect_ratio=1.30,
        spacing=14, run_spacing=14, scroll=ft.ScrollMode.AUTO,
    )
    count_text = txt("", size=12, font=FONT, color=TEXT_MUTED)

    def open_emp(emp_id):
        state["back_to"] = "dashboard"
        app.go("employee", emp_id)

    def refresh():
        emps = EMPLOYEES
        if state["filter"] != "all":
            emps = [e for e in emps if e["status"] == state["filter"]]
        q = state.get("search", "").strip()
        if q:
            emps = [e for e in emps if q in e["name"]]
        emps = sorted(emps, key=lambda e: STATUS_ORDER[e["status"]])
        grid.controls = [employee_card(e, open_emp) for e in emps]
        count_text.value = f'{fa_num(len(emps))} کارکن در این نما'

    pills_map = {}

    def on_filter(key):
        state["filter"] = key
        for kk, (c, t_) in pills_map.items():
            active = kk == key
            c.bgcolor = INK if active else WHITE
            c.border = ft.Border.all(1, INK if active else BORDER)
            t_.color = WHITE if active else INK
        refresh()
        app.page.update()

    pill_controls = []
    for key, label in FILTERS:
        c, t_ = pill(label, active=(state["filter"] == key),
                     on_click=lambda e, kk=key: on_filter(kk))
        pills_map[key] = (c, t_)
        pill_controls.append(c)

    search = ft.TextField(
        hint_text="جستجوی نام کارکن…", prefix_icon=ft.Icons.SEARCH,
        width=250, height=44, text_size=13,
        on_change=lambda e: (state.update({"search": e.control.value}), refresh(), app.page.update()),
    )

    refresh()

    controls = []
    if live:
        controls += [live]
    if banner:
        controls += [banner]

    controls += [
        kpi_row,
        ft.Container(
            content=ft.Row(
                [txt("وضعیت لحظه‌ای کارکنان", size=18, font=FONT_B, color=INK),
                 count_text],
                spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(top=6),
        ),
        ft.Row([*pill_controls, ft.Container(expand=True), search], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        grid,
    ]
    return ft.Column(controls, spacing=14, expand=True)
