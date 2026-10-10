# -*- coding: utf-8 -*-
"""فهرست کارکنان — نمای فشرده با جستجو."""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_CARD, TEXT_MUTED, WHITE, fa_num, txt,
)
from data import EMPLOYEES
from components.common import SHADOW, avatar_circle, status_chip
from components.employee_card import STATUS_ORDER


def employees_view(app):
    state = app.state
    list_holder = ft.ListView(expand=True, spacing=0)

    def open_emp(eid):
        state["back_to"] = "employees"
        app.go("employee", eid)

    count_text = txt("", size=12, font=FONT, color=TEXT_MUTED)

    def refresh():
        q = state.get("emp_search", "").strip()
        emps = [e for e in EMPLOYEES if (not q or q in e["name"])]
        emps = sorted(emps, key=lambda e: STATUS_ORDER[e["status"]])
        rows = []
        for i, emp in enumerate(emps):
            hr_txt = fa_num(emp["hr"]) if emp["hr"] else "—"
            rows.append(ft.Container(
                content=ft.Row([
                    avatar_circle(emp["name"], r=16),
                    ft.Column([
                        txt(emp["name"], size=14, font=FONT_MED, color=INK),
                        txt(f'{emp["dept"]} • {emp["line"]}', size=11, font=FONT,
                            color=TEXT_MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, expand=True),
                    ft.Container(width=90, content=txt(f'شیفت {emp["shift"]}', size=12,
                                                       font=FONT, color=TEXT_MUTED)),
                    ft.Container(width=80, content=txt(f'{hr_txt} ضربه', size=12,
                                                       font=FONT_MED, color=INK)),
                    ft.Container(width=150, content=txt(emp["location"], size=12, font=FONT,
                                                        color=TEXT_MUTED, max_lines=1,
                                                        overflow=ft.TextOverflow.ELLIPSIS)),
                    status_chip(emp["status"]),
                    ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color="#B9BEC3"),
                ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)) if i < len(emps) - 1 else None,
                on_click=lambda e, eid=emp["id"]: open_emp(eid),
            ))
        list_holder.controls = rows
        count_text.value = f'{fa_num(len(emps))} کارکن'

    search = ft.TextField(
        hint_text="جستجوی نام کارکن…", prefix_icon=ft.Icons.SEARCH,
        width=250, height=44, text_size=13,
        on_change=lambda e: (state.update({"emp_search": e.control.value}),
                             refresh(), app.page.update()),
    )

    refresh()

    header = ft.Row([
        txt("کارکنان", size=20, font=FONT_B, color=INK),
        count_text,
        ft.Container(expand=True),
        search,
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    table_card = ft.Container(
        content=list_holder,
        padding=ft.Padding.symmetric(vertical=4),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        expand=True,
    )

    return ft.Column([header, table_card], spacing=14, expand=True)
