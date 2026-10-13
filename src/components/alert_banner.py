# -*- coding: utf-8 -*-
"""نوار هشدار اضطراری — بالای داشبورد، فقط وقتی رویداد باز وجود دارد.

روی موبایل، دکمه‌ها زیر متن می‌آیند تا نوار در عرض کم نشکند.
"""

import flet as ft

from theme import (
    DANGER, FONT, FONT_B, FONT_MED, R_BTN, R_CARD, WHITE, fa_num, txt,
)


def emergency_banner(emp, on_view, on_siren, phone=False):
    head = ft.Row([
        ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=WHITE, size=30),
        ft.Column([
            txt("وضعیت اضطراری — سقوط شناسایی شد", size=16, font=FONT_B, color=WHITE),
            txt(
                f'{emp["name"]} • {emp["location"]} • ساعت {fa_num(emp["incident_time"])} • آژیر روشن است',
                size=12, font=FONT, color="#FFDADB",
            ),
        ], spacing=2, expand=True),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    btn_view = ft.Button(
        "اقدام فوری",
        icon=ft.Icons.EMERGENCY,
        style=ft.ButtonStyle(
            bgcolor=WHITE, color=DANGER,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
        ),
        on_click=on_view,
    )
    btn_siren = ft.OutlinedButton(
        "خاموش‌کردن آژیر",
        style=ft.ButtonStyle(
            color=WHITE,
            side=ft.BorderSide(1.5, "#FFFFFF88"),
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
        ),
        on_click=on_siren,
    )

    if phone:
        body = ft.Column([
            head,
            ft.Row([btn_view, btn_siren], spacing=10, wrap=True, run_spacing=8),
        ], spacing=10)
    else:
        body = ft.Row([
            ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=WHITE, size=30),
            ft.Column([
                txt("وضعیت اضطراری — سقوط شناسایی شد", size=16, font=FONT_B, color=WHITE),
                txt(
                    f'{emp["name"]} • {emp["location"]} • ساعت {fa_num(emp["incident_time"])} • آژیر روشن است',
                    size=12, font=FONT, color="#FFDADB",
                ),
            ], spacing=2),
            ft.Container(expand=True),
            btn_view,
            btn_siren,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    return ft.Container(
        bgcolor=DANGER,
        border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=18, vertical=13),
        content=body,
    )