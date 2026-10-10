# -*- coding: utf-8 -*-
"""نوار هشدار اضطراری — بالای داشبورد، فقط وقتی رویداد باز وجود دارد."""

import flet as ft

from theme import (
    DANGER, FONT, FONT_B, FONT_MED, R_BTN, R_CARD, WHITE, fa_num, txt,
)


def emergency_banner(emp, on_view, on_siren):
    return ft.Container(
        bgcolor=DANGER,
        border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=18, vertical=13),
        content=ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=WHITE, size=30),
            ft.Column([
                txt("وضعیت اضطراری — سقوط شناسایی شد", size=16, font=FONT_B, color=WHITE),
                txt(
                    f'{emp["name"]} • {emp["location"]} • ساعت {fa_num(emp["incident_time"])} • آژیر روشن است',
                    size=12, font=FONT, color="#FFDADB",
                ),
            ], spacing=2),
            ft.Container(expand=True),
            ft.Button(
                "اقدام فوری",
                icon=ft.Icons.EMERGENCY,
                style=ft.ButtonStyle(
                    bgcolor=WHITE, color=DANGER,
                    shape=ft.RoundedRectangleBorder(radius=R_BTN),
                ),
                on_click=on_view,
            ),
            ft.OutlinedButton(
                "خاموش‌کردن آژیر",
                style=ft.ButtonStyle(
                    color=WHITE,
                    side=ft.BorderSide(1.5, "#FFFFFF88"),
                    shape=ft.RoundedRectangleBorder(radius=R_BTN),
                ),
                on_click=on_siren,
            ),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )
