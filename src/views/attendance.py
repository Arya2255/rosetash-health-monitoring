# -*- coding: utf-8 -*-
"""حضور و غیاب — ساعت ورود و خروج، ساعات کار و آخرین مکان هر کارکن."""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_CARD, TEXT_MUTED, WARN, WHITE,
    fa_date, fa_hours, fa_num, txt,
)
from data import EMPLOYEES, attendance_summary
from components.common import SHADOW, att_chip, avatar_circle, pill, stat_card

ATT_FILTERS = [
    ("all", "همه"),
    ("present", "حاضر"),
    ("left", "خارج‌شده"),
    ("late", "تأخیردار"),
    ("away", "مرخصی و غایب"),
]


def _matches(emp, key):
    a = emp["attendance"]
    if key == "all":
        return True
    if key == "late":
        return a["late_min"] > 0
    if key == "away":
        return a["status"] in ("leave", "absent")
    return a["status"] == key


def attendance_view(app):
    state = app.state
    state.setdefault("att_filter", "all")
    k = attendance_summary()

    # ── شاخص‌های کلیدی ──
    kpi_row = ft.Row([
        ft.Container(expand=True, content=stat_card(
            "حاضر در کارخانه", f'{fa_num(k["present"])} نفر',
            "ثبت خودکار از طریق مچ‌بند", ft.Icons.HOW_TO_REG, "#1E8E4E", "#E6F4EB")),
        ft.Container(expand=True, content=stat_card(
            "خارج‌شده", f'{fa_num(k["left"])} نفر',
            "پایان شیفت یا خروج زودهنگام", ft.Icons.LOGOUT, "#5B6B7B", "#ECEEF0")),
        ft.Container(expand=True, content=stat_card(
            "تأخیر امروز", f'{fa_num(k["late"])} نفر',
            "ورود بعد از ساعت ۰۷:۰۰", ft.Icons.SCHEDULE, WARN, "#FCF0DC")),
        ft.Container(expand=True, content=stat_card(
            "میانگین ساعات کار", fa_hours(k["avg_min"]),
            "میانگین روز کاری کارکنان", ft.Icons.TIMER, INK, "#E9EBEE")),
    ], spacing=14)

    # ── فیلترها و جستجو ──
    list_holder = ft.ListView(expand=True, spacing=0)
    count_text = txt("", size=12, font=FONT, color=TEXT_MUTED)
    pills_map = {}

    def open_emp(eid):
        state["back_to"] = "attendance"
        app.go("employee", eid)

    def refresh():
        q = state.get("att_search", "").strip()
        emps = [e for e in EMPLOYEES if _matches(e, state["att_filter"])]
        if q:
            emps = [e for e in emps if q in e["name"]]
        emps = sorted(emps, key=lambda e: (e["attendance"]["status"] != "present",
                                           -(e["attendance"]["work_min"])))
        rows = []
        for i, emp in enumerate(emps):
            a = emp["attendance"]
            entered = fa_num(a["entered"]) if a["entered"] else "—"
            if a["exited"]:
                exited, exit_color = fa_num(a["exited"]), TEXT_MUTED
            elif a["status"] == "present":
                exited, exit_color = "در کارخانه", "#1E8E4E"
            else:
                exited, exit_color = "—", TEXT_MUTED
            work = fa_hours(a["work_min"]) if a["entered"] else "—"
            late = f'{fa_num(a["late_min"])} د' if a["late_min"] else "—"
            late_color = WARN if a["late_min"] else TEXT_MUTED
            place = a["last_zone"] or (emp["location"] if emp["location"] != "—" else "—")
            if a["status"] == "present" and a["last_zone"]:
                place = f'{a["last_zone"]} • اکنون'
            rows.append(ft.Container(
                content=ft.Row([
                    ft.Container(width=250, content=ft.Row([
                        avatar_circle(emp["name"], r=16),
                        ft.Column([
                            txt(emp["name"], size=14, font=FONT_MED, color=INK),
                            txt(f'{emp["dept"]} • {emp["line"]}', size=11, font=FONT,
                                color=TEXT_MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=1, expand=True),
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)),
                    ft.Container(width=64, content=txt(entered, size=13, font=FONT_MED, color=INK)),
                    ft.Container(width=110, content=txt(exited, size=12, font=FONT, color=exit_color)),
                    ft.Container(width=110, content=txt(work, size=12, font=FONT, color=TEXT_MUTED)),
                    ft.Container(width=70, content=txt(late, size=12, font=FONT_MED, color=late_color)),
                    ft.Container(width=132, content=att_chip(a["status"], a["coverage"])),
                    ft.Container(expand=True, content=ft.Row([
                        ft.Icon(ft.Icons.LOCATION_ON, size=14, color=TEXT_MUTED),
                        txt(place, size=12, font=FONT, color=TEXT_MUTED, expand=True,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=5, tight=True)),
                    ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color="#B9BEC3"),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)) if i < len(emps) - 1 else None,
                on_click=lambda e, eid=emp["id"]: open_emp(eid),
            ))
        list_holder.controls = rows
        count_text.value = f'{fa_num(len(emps))} کارکن'

    def on_filter(key):
        state["att_filter"] = key
        for kk, (c, t_) in pills_map.items():
            active = kk == key
            c.bgcolor = INK if active else WHITE
            c.border = ft.Border.all(1, INK if active else BORDER)
            t_.color = WHITE if active else INK
        refresh()
        app.page.update()

    pill_controls = []
    for key, label in ATT_FILTERS:
        c, t_ = pill(label, active=(state["att_filter"] == key),
                     on_click=lambda e, kk=key: on_filter(kk))
        pills_map[key] = (c, t_)
        pill_controls.append(c)

    search = ft.TextField(
        hint_text="جستجوی نام کارکن…", prefix_icon=ft.Icons.SEARCH,
        width=250, height=44, text_size=13,
        on_change=lambda e: (state.update({"att_search": e.control.value}),
                             refresh(), app.page.update()),
    )

    refresh()

    header = ft.Row([
        ft.Column([
            txt("حضور و غیاب", size=20, font=FONT_B, color=INK),
            txt(f'امروز — {fa_date()} • {fa_num(k["total"])} کارکن', size=12, font=FONT,
                color=TEXT_MUTED),
        ], spacing=2),
        ft.Container(expand=True),
        count_text,
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    cols = ft.Row([
        ft.Container(width=250, content=txt("کارکن", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=64, content=txt("ورود", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=110, content=txt("خروج", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=110, content=txt("ساعات کار", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=70, content=txt("تأخیر", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=132, content=txt("وضعیت", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(expand=True, content=txt("آخرین مکان", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=18),
    ], spacing=12)

    table_card = ft.Container(
        content=ft.Column([
            ft.Container(content=cols, padding=ft.Padding.only(left=14, right=14, top=12, bottom=8),
                         border=ft.Border.only(bottom=ft.BorderSide(1, BORDER))),
            list_holder,
        ], spacing=0),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        expand=True,
    )

    return ft.Column([
        header,
        kpi_row,
        ft.Row([*pill_controls, ft.Container(expand=True), search], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        table_card,
    ], spacing=14, expand=True)
