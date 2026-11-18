# -*- coding: utf-8 -*-
"""داشبورد لحظه‌ای — فقط کارکنان و هشدارهای واقعی پل."""

import asyncio

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, TEXT_MUTED, WARN, WHITE,
    fa_num, txt,
)
from data import live_status
from layout import filter_row, flow, is_phone, list_card, page_scroll
from components.common import card, pill, stat_card
from components.employee_card import STATUS_ORDER, employee_card

FILTERS = [
    ("all", "همه"), ("danger", "اضطراری"), ("warn", "هشدار"),
    ("ok", "عادی"), ("off", "قطع اتصال"),
]


def dashboard_view(app):
    state = app.state
    generation = state.get("dashboard_gen", 0) + 1
    state["dashboard_gen"] = generation
    current = {"doc": live_status()}
    connection = txt("", size=12, font=FONT_MED, color=TEXT_MUTED,
                     data="dashboard:connection")
    gateway_warning = txt("", size=13, font=FONT_MED, color=WARN,
                          visible=False, data="dashboard:gateways")
    kpi_holder = ft.Container()
    count_text = txt("", size=12, font=FONT, color=TEXT_MUTED)
    empty = txt("", size=13, font=FONT, color=TEXT_MUTED,
                visible=False, data="dashboard:empty")
    grid = ft.GridView(
        expand=True, max_extent=420 if is_phone(app) else 315,
        child_aspect_ratio=1.30, spacing=14, run_spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )
    list_card(app, grid, h=640)

    def open_emp(mac):
        state["back_to"] = "dashboard"
        app.go("employee", mac)

    def refresh():
        doc = current["doc"]
        available = isinstance(doc, dict) and bool(doc.get("ok"))
        rows = [e for e in (doc or {}).get("employees", [])
                if e.get("registered")] if available else []
        connection.value = ("دریافت زنده از پل" if available
                            else "پل محلی در دسترس نیست — اتصال را بررسی کنید")
        alerts = [a for a in (doc or {}).get("alerts_active", [])
                  if a.get("source") == "live" and a.get("status") in ("open", "acknowledged")]
        offline = [a for a in alerts if a.get("type") == "gateway_offline"]
        gateway_warning.visible = available and bool(offline)
        gateway_warning.value = "گیت‌وی آفلاین: " + "، ".join(
            str(a.get("emp") or a.get("gw") or "—") for a in offline)
        averages = [(e.get("health") or {}).get("avg") for e in rows
                    if (e.get("health") or {}).get("state") == "done"
                    and (e.get("health") or {}).get("n")]
        averages = [v for v in averages if isinstance(v, (int, float)) and v > 0]
        avg = fa_num(round(sum(averages) / len(averages))) + " ضربه" if averages else "—"
        present = sum(bool(e.get("present")) for e in rows)
        specs = [
            ("حاضر در شیفت", f"{fa_num(present)} از {fa_num(len(rows))}",
             "کارکنان ثبت‌شده در دید گیت‌وی", ft.Icons.GROUPS, INK, "#E9EBEE"),
            ("هشدار فعال", fa_num(sum(a.get("severity") == "warn" for a in alerts)),
             "نیازمند پیگیری مسئول HSE", ft.Icons.ERROR_OUTLINE, WARN, "#FCF0DC"),
            ("وضعیت اضطراری", fa_num(sum(a.get("severity") == "danger" for a in alerts)),
             "هشدارهای واقعی با شدت اضطراری", ft.Icons.SOS, DANGER, "#FCE7E8"),
            ("میانگین ضربان", avg, "آخرین پنجره‌های معتبر سلامت",
             ft.Icons.MONITOR_HEART, INK, "#E9EBEE"),
        ]
        kpi_holder.visible = available
        kpi_holder.content = flow(app, [ft.Container(expand=True, content=stat_card(*s))
                                        for s in specs], spacing=14)
        selected = state.get("filter", "all")
        if selected != "all":
            rows = [e for e in rows if e.get("status", "off") == selected]
        query = state.get("search", "").strip().casefold()
        if query:
            rows = [e for e in rows if query in str(e.get("name") or "").casefold()]
        rows = sorted(rows, key=lambda e: STATUS_ORDER.get(e.get("status"), 3))
        grid.controls = [employee_card(e, open_emp) for e in rows]
        count_text.value = f"{fa_num(len(rows))} کارکن در این نما" if available else "—"
        empty.visible = available and not rows
        empty.value = ("کارکن ثبت‌شده‌ای وجود ندارد" if not (doc or {}).get("employees")
                       or not any(e.get("registered") for e in doc.get("employees", []))
                       else "کارکنی با این فیلتر پیدا نشد")

    pills_map = {}

    def on_filter(key):
        state["filter"] = key
        for kk, (control, label) in pills_map.items():
            active = kk == key
            control.bgcolor = INK if active else WHITE
            control.border = ft.Border.all(1, INK if active else BORDER)
            label.color = WHITE if active else INK
        refresh()
        app.page.update()

    pill_controls = []
    for key, label in FILTERS:
        c, t = pill(label, active=(state.get("filter", "all") == key),
                    on_click=lambda e, kk=key: on_filter(kk))
        pills_map[key] = (c, t)
        pill_controls.append(c)

    def on_search(event):
        state["search"] = event.control.value or ""
        refresh()
        app.page.update()

    search = ft.TextField(
        hint_text="جستجوی نام کارکن…", prefix_icon=ft.Icons.SEARCH,
        width=None if is_phone(app) else 250, height=44, text_size=13,
        on_change=on_search, data="dashboard:search",
    )
    refresh()

    async def loop():
        while state.get("view") == "dashboard" and state.get("dashboard_gen") == generation:
            await asyncio.sleep(2)
            doc = await asyncio.to_thread(live_status)
            if state.get("view") != "dashboard" or state.get("dashboard_gen") != generation:
                return
            current["doc"] = doc
            refresh()
            try:
                app.page.update()
            except RuntimeError:
                return

    if hasattr(app.page, "run_task"):
        app.page.run_task(loop)
    return page_scroll(app, [
        card(ft.Column([connection, gateway_warning], spacing=6), pad=12),
        kpi_holder,
        ft.Container(content=ft.Row([
            txt("وضعیت لحظه‌ای کارکنان", size=18, font=FONT_B, color=INK), count_text,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.only(top=6)),
        filter_row(app, pill_controls, search), empty, grid,
    ])
