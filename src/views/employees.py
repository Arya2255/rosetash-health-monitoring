# -*- coding: utf-8 -*-
"""فهرست کارکنان — دفتر واقعی کارکنان، متصل به پل زنده.

حالت زنده: فهرست از دفتر پل می‌آید — هر کارکن ثبت‌شده با وضعیت، ضربان و
مکان واقعی؛ به‌همراه مچ‌بندهای در دید که هنوز ثبت نشده‌اند. ثبت و ویرایش
از همین صفحه انجام می‌شود (فرم مشترک با پروفایل).

حالت نمایشی: اگر پل در دسترس نباشد، فهرست نمونهٔ فاز ۱ نمایش داده
می‌شود و برچسب «دادهٔ نمایشی» بالای صفحه دیده می‌شود.
"""

import asyncio

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN, R_CARD,
    TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
from data import EMPLOYEES, live_employees, photo_src
from components.common import (
    ISSUE_LABELS, SHADOW, avatar_circle, person_avatar, rel_age, status_chip,
)
from components.employee_card import STATUS_ORDER
from components.employee_form import open_employee_form

STATUS_RANK = {"danger": 0, "warn": 1, "ok": 2, "off": 3}


def employees_view(app):
    state = app.state
    state.setdefault("emp_search", "")
    gen = state.get("emp_gen", 0) + 1
    state["emp_gen"] = gen

    last = {"doc": None}
    list_holder = ft.ListView(expand=True, spacing=0)
    count_text = txt("", size=12, font=FONT, color=TEXT_MUTED)

    # ── چیپ حالت داده — زنده یا نمایشی ──
    mode_dot = ft.Container(width=7, height=7, border_radius=4, bgcolor=OFFLINE)
    mode_txt = txt("در حال بررسی پل محلی…", size=12, font=FONT_MED,
                   color=TEXT_MUTED)
    mode_chip = ft.Container(
        content=ft.Row([mode_dot, mode_txt], spacing=6, tight=True),
        bgcolor="#F1F2F4", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
    )

    demo_banner = ft.Container(
        visible=False,
        content=ft.Row([
            ft.Icon(ft.Icons.CLOUD_OFF, size=18, color=WARN),
            txt("پل محلی در دسترس نیست — این فهرست دادهٔ نمایشی است",
                size=13, font=FONT_MED, color=WARN, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor="#FCF0DC", border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )

    # ── کارت مچ‌بندهای ثبت‌نشده ──
    unassigned_col = ft.Column([], spacing=8)
    unassigned_count = txt("", size=11, font=FONT, color=TEXT_MUTED)
    unassigned_card = ft.Container(
        visible=False,
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.WATCH, size=16, color=INK),
                txt("مچ‌بند در دید — هنوز ثبت نشده", size=14,
                    font=FONT_MED, color=INK),
                ft.Container(expand=True),
                unassigned_count,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            unassigned_col,
        ], spacing=10),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        padding=14,
    )

    def _open_emp(mac):
        state["back_to"] = "employees"
        app.go("employee", mac)

    def _refresh_now():
        _apply(live_employees(force=True))
        try:
            app.page.update()
        except Exception:
            pass

    def _register_band(mac):
        open_employee_form(app, mac=mac, on_saved=_refresh_now)

    add_btn = ft.Button(
        "افزودن کارکن", icon=ft.Icons.PERSON_ADD, height=40, visible=False,
        style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=lambda e: open_employee_form(app, on_saved=_refresh_now),
    )

    # ── ردیف کارکن واقعی ──
    def _live_row(e):
        st = e.get("status") or "off"
        issues = e.get("issues") or []
        issue_lbl = ISSUE_LABELS.get(issues[0], issues[0]) if issues else ""
        h = e.get("health") or {}
        hr = h.get("avg") if (h.get("state") == "done" and h.get("n")) else None
        hr_txt = fa_num(round(hr)) if hr else "—"
        parts = [p for p in (e.get("company"), e.get("dept"), e.get("line"),
                             e.get("role")) if p]
        sub = " • ".join(parts) if parts else "بدون مشخصات — برای ویرایش کلیک کن"
        loc = e.get("zone") or e.get("gw") or "—"
        if not e.get("present"):
            loc = "—"
        name_col = [
            txt(e.get("name") or "مچ‌بند ثبت‌نشده", size=14, font=FONT_MED,
                color=INK),
            txt(sub, size=11, font=FONT, color=TEXT_MUTED, max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS),
        ]
        if issue_lbl and st in ("warn", "danger"):
            name_col.append(txt(issue_lbl, size=11, font=FONT,
                                color=DANGER if st == "danger" else WARN,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
        return ft.Container(
            content=ft.Row([
                person_avatar(e, r=16),
                ft.Column(name_col, spacing=1, expand=True),
                ft.Container(width=70, content=txt(f'شیفت {e.get("shift") or "—"}',
                                                   size=12, font=FONT,
                                                   color=TEXT_MUTED)),
                ft.Container(width=80, content=txt(f'{hr_txt} ضربه', size=12,
                                                   font=FONT_MED, color=INK)),
                ft.Container(width=140, content=txt(loc, size=12, font=FONT,
                                                    color=TEXT_MUTED,
                                                    max_lines=1,
                                                    overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Container(width=140, content=status_chip(st)),
                ft.Container(width=110, content=txt(
                    rel_age(e.get("last_seen_age_s")), size=11, font=FONT,
                    color=TEXT_MUTED)),
                ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color="#B9BEC3"),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
            on_click=lambda ev, m=e["mac"]: _open_emp(m),
        )

    # ── ردیف مچ‌بند ثبت‌نشده ──
    def _unassigned_row(e):
        rssi = e.get("rssi")
        rssi_txt = fa_num(round(rssi)) if rssi is not None else "—"
        label = e.get("band_label")
        title = (f'مچ‌بند «{label}» — بدون کارکن' if label
                 else "مچ‌بند ثبت‌نشده")
        return ft.Row([
            avatar_circle("؟", r=16, bg="#F1F2F4", fg=TEXT_MUTED),
            ft.Column([
                txt(title, size=14, font=FONT_MED, color=INK),
                txt(f'{e.get("mac")} — آنتن {rssi_txt} — {rel_age(e.get("last_seen_age_s"))}',
                    size=11, font=FONT, color=TEXT_MUTED, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=1, expand=True),
            ft.Container(width=140, content=status_chip("ok")),
            ft.TextButton("ثبت کارکن", icon=ft.Icons.PERSON_ADD,
                          on_click=lambda ev, m=e["mac"]: _register_band(m)),
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # ── ردیف حالت نمایشی (فاز ۱) ──
    def _mock_rows(q):
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
                            color=TEXT_MUTED, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, expand=True),
                    ft.Container(width=90, content=txt(f'شیفت {emp["shift"]}', size=12,
                                                       font=FONT, color=TEXT_MUTED)),
                    ft.Container(width=80, content=txt(f'{hr_txt} ضربه', size=12,
                                                       font=FONT_MED, color=INK)),
                    ft.Container(width=150, content=txt(emp["location"], size=12,
                                                        font=FONT, color=TEXT_MUTED,
                                                        max_lines=1,
                                                        overflow=ft.TextOverflow.ELLIPSIS)),
                    status_chip(emp["status"]),
                    ft.Icon(ft.Icons.CHEVRON_LEFT, size=18, color="#B9BEC3"),
                ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border=ft.Border.only(bottom=ft.BorderSide(1, BORDER))
                if i < len(emps) - 1 else None,
                on_click=lambda e, eid=emp["id"]: (state.update(
                    {"back_to": "employees"}), app.go("employee", eid)),
            ))
        return rows

    # ── رندر فهرست از آخرین داده ──
    def _render():
        doc = last["doc"]
        q = state.get("emp_search", "").strip()
        if doc is None:
            list_holder.controls = _mock_rows(q)
            count_text.value = f'{fa_num(len(EMPLOYEES))} کارکن — نمایشی'
            return
        reg = [e for e in doc if e.get("registered")]
        uns = [e for e in doc if not e.get("registered")]
        shown = reg
        if q:
            ql = q.lower()
            shown = [e for e in reg
                     if ql in (e.get("name") or "").lower()
                     or ql in (e.get("dept") or "").lower()
                     or ql in (e.get("mac") or "").lower()]
        shown = sorted(shown, key=lambda e: (not e.get("present"),
                                             STATUS_RANK.get(e.get("status"), 9),
                                             e.get("name") or ""))
        if shown:
            list_holder.controls = [_live_row(e) for e in shown]
        else:
            msg = ("چیزی با این جستجو پیدا نشد" if q else
                   "هنوز کارکنی ثبت نشده — با «افزودن کارکن» یا دکمهٔ ثبت "
                   "روی مچ‌بندهای در دید شروع کن")
            list_holder.controls = [ft.Container(
                height=80, alignment=ft.Alignment.CENTER,
                content=txt(msg, size=13, font=FONT, color=TEXT_MUTED))]
        count_text.value = (f'{fa_num(len(reg))} کارکن ثبت‌شده'
                            + (f' — {fa_num(len(uns))} مچ‌بند ثبت‌نشده'
                               if uns else ""))
        if uns:
            unassigned_col.controls = [_unassigned_row(e) for e in uns]
            unassigned_count.value = f'{fa_num(len(uns))} مورد'
            unassigned_card.visible = True
        else:
            unassigned_card.visible = False

    def _apply(doc):
        last["doc"] = doc
        if doc is None:
            mode_dot.bgcolor = OFFLINE
            mode_txt.value = "پل محلی در دسترس نیست"
            mode_txt.color = TEXT_MUTED
            mode_chip.bgcolor = "#ECECEC"
            demo_banner.visible = True
            add_btn.visible = False
        else:
            mode_dot.bgcolor = OK
            mode_txt.value = "دریافت زنده از پل محلی"
            mode_txt.color = OK
            mode_chip.bgcolor = "#E6F4EB"
            demo_banner.visible = False
            add_btn.visible = True
        _render()

    search = ft.TextField(
        hint_text="جستجوی نام یا مک…", prefix_icon=ft.Icons.SEARCH,
        width=250, height=44, text_size=13, value=state.get("emp_search", ""),
        on_change=lambda e: (state.update({"emp_search": e.control.value}),
                             _render(), app.page.update()),
    )

    _apply(live_employees())

    header = ft.Row([
        txt("کارکنان", size=20, font=FONT_B, color=INK),
        count_text,
        ft.Container(expand=True),
        add_btn,
        search,
        mode_chip,
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    table_card = ft.Container(
        content=list_holder,
        padding=ft.Padding.symmetric(vertical=4),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        expand=True,
    )

    async def _loop():
        while state.get("view") == "employees" and state.get("emp_gen") == gen:
            try:
                _apply(live_employees())
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(2)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    return ft.Column([header, demo_banner, unassigned_card, table_card],
                     spacing=14, expand=True)
