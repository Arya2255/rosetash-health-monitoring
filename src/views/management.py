# -*- coding: utf-8 -*-
"""مدیریت سامانه — کارکنان، مچ‌بندها، گیت‌وی‌ها و واحدها."""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE,
    fa_num, txt,
)
from data import EMPLOYEES
from layout import is_phone, list_card, page_scroll
from components.common import SHADOW, avatar_circle, card, status_chip

TABS = [
    ("staff", "کارکنان", ft.Icons.GROUPS),
    ("bands", "مچ‌بندها", ft.Icons.WATCH),
    ("gateways", "گیت‌وی‌ها", ft.Icons.ROUTER),
    ("depts", "واحدها", ft.Icons.PRECISION_MANUFACTURING),
]


def _placeholder(icon, title, desc, items):
    return card(ft.Column([
        ft.Container(
            content=ft.Icon(icon, size=34, color=TEXT_MUTED),
            bgcolor="#EFF1F3", border_radius=999, padding=ft.Padding.all(16),
        ),
        txt(title, size=17, font=FONT_B, color=INK),
        txt(desc, size=13, font=FONT, color=TEXT_MUTED, text_align=ft.TextAlign.CENTER),
        ft.Container(height=4),
        ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.CIRCLE, size=7, color="#C4C9CE"),
                txt(it, size=12, font=FONT, color=TEXT_MUTED),
            ], spacing=8)
            for it in items
        ], spacing=7),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12), pad=40)


def _staff_panel(app):
    phone = is_phone(app)
    list_holder = ft.ListView(expand=True, spacing=0)
    if phone:
        # موبایل: ستون‌های کلیدی — جزئیات در پروفایل
        head = ft.Container(
            content=ft.Row([
                ft.Container(expand=True, content=txt("کارکن", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=95, content=txt("وضعیت", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=40, content=txt("", size=12)),
            ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        )
    else:
        head = ft.Container(
            content=ft.Row([
                ft.Container(expand=True, content=txt("کارکن", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=120, content=txt("واحد", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=70, content=txt("شیفت", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=105, content=txt("مچ‌بند", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=65, content=txt("باتری", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=95, content=txt("وضعیت", size=12, font=FONT_MED, color=TEXT_MUTED)),
                ft.Container(width=40, content=txt("", size=12)),
            ], spacing=12),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        )

    for i, emp in enumerate(EMPLOYEES):
        cells = [
            ft.Row([
                avatar_circle(emp["name"], r=15),
                txt(emp["name"], size=13, font=FONT_MED, color=INK),
            ], spacing=8, expand=True),
        ]
        if not phone:
            cells += [
                ft.Container(width=120, content=txt(emp["dept"], size=12, font=FONT,
                                                    color=TEXT_MUTED, max_lines=1,
                                                    overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Container(width=70, content=txt(f'شیفت {emp["shift"]}', size=12,
                                                   font=FONT, color=TEXT_MUTED)),
                ft.Container(width=105, content=txt(emp["band"], size=12, font=FONT,
                                                    color=TEXT_MUTED)),
                ft.Container(width=65, content=txt(f'{fa_num(emp["battery"])}٪', size=12,
                                                   font=FONT, color=TEXT_MUTED)),
            ]
        cells += [
            ft.Container(width=95, content=status_chip(emp["status"])),
            ft.Container(width=40, content=ft.IconButton(
                ft.Icons.EDIT_OUTLINED, icon_size=17, icon_color=TEXT_MUTED,
                tooltip="ویرایش — فاز ۲",
                on_click=lambda e: app.snack("ویرایش پروفایل — در فاز ۲ فعال می‌شود"))),
        ]
        list_holder.controls.append(ft.Container(
            content=ft.Row(cells, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=7),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)) if i < len(EMPLOYEES) - 1 else None,
        ))

    return ft.Container(
        content=ft.Column([head, list_holder], spacing=0),
        bgcolor=WHITE, border_radius=12, border=ft.Border.all(1, BORDER),
        shadow=SHADOW, expand=True,
    )


def management_view(app):
    active = {"tab": "staff"}
    holder = ft.Container(expand=True)
    pills_map = {}

    def render_tab():
        tab = active["tab"]
        if tab == "staff":
            holder.content = _staff_panel(app)
        elif tab == "bands":
            holder.content = _placeholder(
                ft.Icons.WATCH, "مدیریت مچ‌بندها",
                "ثبت مچ‌بند جدید، اتصال به کارکن و پایش باتری و سیگنال",
                ["فهرست مچ‌بندها با شناسه و وضعیت اتصال",
                 "اتصال مچ‌بند به پروفایل کارکن",
                 "هشدار باتری ضعیف و قطعی ارتباط",
                 "پشتیبانی از برندهای دیگر مچ‌بند"],
            )
        elif tab == "gateways":
            holder.content = _placeholder(
                ft.Icons.ROUTER, "گیت‌وی‌های BLE",
                "پایش بردهای ESP32، کیفیت پوشش و محدوده‌های مجاز",
                ["نقشهٔ پوشش سالن‌ها و محوطه",
                 "وضعیت اتصال و به‌روزرسانی هر گیت‌وی",
                 "تخصیص محدودهٔ مجاز برای هر کارکن",
                 "افزودن گیت‌وی جدید به شبکه"],
            )
        else:
            holder.content = _placeholder(
                ft.Icons.PRECISION_MANUFACTURING, "واحدها و شیفت‌ها",
                "تعریف واحد، خطوط تولید و شیفت‌های کاری کارخانه",
                ["واحدها و خطوط تولید",
                 "تعریف شیفت‌های صبح، عصر و شب",
                 "سرشیفت هر واحد و مسیر هشدار",
                 "گزارش حضور به تفکیک واحد"],
            )
        app.page.update()

    def on_tab(key):
        if key == active["tab"]:
            return
        active["tab"] = key
        for kk, (c, t_) in pills_map.items():
            a = kk == key
            c.bgcolor = INK if a else WHITE
            c.border = ft.Border.all(1, INK if a else BORDER)
            t_.color = WHITE if a else INK
        render_tab()

    tabs_row = []
    for key, label, icon in TABS:
        a = key == active["tab"]
        t_ = txt(label, size=13, font=FONT_MED, color=WHITE if a else INK)
        c = ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=16, color=WHITE if a else TEXT_MUTED), t_,
            ], spacing=6, tight=True),
            padding=ft.Padding.symmetric(horizontal=14, vertical=7),
            border_radius=999, bgcolor=INK if a else WHITE,
            border=ft.Border.all(1, INK if a else BORDER),
            on_click=lambda e, kk=key: on_tab(kk),
        )
        pills_map[key] = (c, t_)
        tabs_row.append(c)

    header = ft.Row([
        ft.Column([
            txt("مدیریت سامانه", size=20, font=FONT_B, color=INK),
            txt("کارکنان، دستگاه‌ها و ساختار کارخانه", size=12, font=FONT, color=TEXT_MUTED),
        ], spacing=2),
        ft.Container(expand=True),
        ft.Button(
            "افزودن کارمند", icon=ft.Icons.PERSON_ADD, height=42,
            style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                                 shape=ft.RoundedRectangleBorder(radius=R_BTN)),
            on_click=lambda e: app.snack("فرم افزودن کارمند — در فاز ۲ فعال می‌شود"),
        ),
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    render_tab()
    list_card(app, holder, h=430)
    return page_scroll(app, [header, ft.Row(tabs_row, spacing=8, wrap=True, run_spacing=8),
                             holder])
