# -*- coding: utf-8 -*-
"""کارت کارکن — بلوک اصلی داشبورد لحظه‌ای."""

import flet as ft

from theme import (
    BORDER, DANGER, DANGER_BG, FONT, FONT_B, FONT_MED, FONT_SB, INFO, INK,
    R_CARD, TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
from components.common import SHADOW, avatar_circle, status_chip

STATUS_ORDER = {"danger": 0, "warn": 1, "ok": 2, "off": 3}


def _vital(icon, color, value, label):
    return ft.Column([
        ft.Row([ft.Icon(icon, size=14, color=color),
                txt(value, size=15, font=FONT_B, color=INK)], spacing=5, tight=True),
        txt(label, size=11, font=FONT, color=TEXT_MUTED),
    ], spacing=2)


def employee_card(emp, on_click):
    danger = emp["status"] == "danger"
    off = emp["status"] == "off"
    hr = emp["hr"] or 0
    hr_txt = fa_num(emp["hr"]) if emp["hr"] else "—"
    spo2_txt = (fa_num(emp["spo2"]) + "٪") if emp["spo2"] else "—"

    kids = [
        ft.Row([
            avatar_circle(emp["name"], r=19,
                          bg="#F9D2D4" if danger else "#E9EBEE",
                          fg=DANGER if danger else TEXT_MAIN),
            ft.Column([
                txt(emp["name"], size=15, font=FONT_SB, color=INK),
                txt(emp["dept"], size=11, font=FONT,
                    color=TEXT_MUTED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=1, expand=True),
            status_chip(emp["status"]),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(height=2),
        ft.Row([
            _vital(ft.Icons.MONITOR_HEART, DANGER if hr >= 110 else TEXT_MAIN, hr_txt, "ضربان"),
            _vital(ft.Icons.AIR, INFO if not off else TEXT_MUTED, spo2_txt, "اکسیژن"),
            _vital(ft.Icons.BATTERY_FULL, TEXT_MUTED, fa_num(emp["battery"]) + "٪", "باتری"),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, spacing=0),
        ft.Row([
            ft.Icon(ft.Icons.LOCATION_ON, size=14, color=TEXT_MUTED),
            txt(emp["location"], size=12, font=FONT, color=TEXT_MUTED,
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            txt(f'{fa_num(emp["last_seen"])} ثانیه پیش', size=11, font=FONT, color="#9B9FA3"),
        ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    ]

    if danger:
        kids.append(ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.SOS, size=16, color=WHITE),
                txt(emp["note"].split("—")[0].strip(), size=12, font=FONT_MED, color=WHITE,
                    expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=6),
            bgcolor=DANGER, border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        ))
    elif emp["status"] == "warn":
        kids.append(ft.Row([
            ft.Icon(ft.Icons.ERROR_OUTLINE, size=15, color=WARN),
            txt(emp["note"], size=12, font=FONT, color=WARN,
                expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=6))

    return ft.Container(
        content=ft.Column(kids, spacing=8),
        padding=14,
        bgcolor=DANGER_BG if danger else WHITE,
        border=ft.Border.all(1.5 if danger else 1, DANGER if danger else BORDER),
        border_radius=R_CARD,
        shadow=SHADOW,
        on_click=lambda e: on_click(emp["id"]),
    )
