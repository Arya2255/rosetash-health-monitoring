# -*- coding: utf-8 -*-
"""نوار کناری ناوبری — در چیدمان راست‌به‌چپ، ابتدای صفحه."""

import flet as ft

from theme import (
    BRAND_RED, FONT, FONT_B, FONT_MED, SIDE_ACTIVE, SIDE_BG, SIDE_MUTED,
    SIDE_TEXT, WHITE, fa_num, txt,
)

NAV_ITEMS = [
    ("dashboard", "داشبورد", ft.Icons.DASHBOARD),
    ("employees", "کارکنان", ft.Icons.GROUPS),
    ("attendance", "حضور و غیاب", ft.Icons.FACT_CHECK),
    ("alerts", "هشدارها", ft.Icons.NOTIFICATIONS_ACTIVE),
    ("reports", "گزارش‌ها", ft.Icons.BAR_CHART),
    ("management", "مدیریت", ft.Icons.ADMIN_PANEL_SETTINGS),
    ("settings", "تنظیمات", ft.Icons.SETTINGS),
]


def build_sidebar(active, on_nav, alert_count=0):
    items = []
    for key, label, icon in NAV_ITEMS:
        is_active = key == active
        kids = [
            ft.Container(
                width=3, height=20, border_radius=2,
                bgcolor=BRAND_RED if is_active else "transparent",
            ),
            ft.Icon(icon, size=20, color=SIDE_TEXT if is_active else SIDE_MUTED),
            txt(label, size=14, font=FONT_MED if is_active else FONT,
                color=SIDE_TEXT if is_active else SIDE_MUTED),
        ]
        if key == "alerts" and alert_count:
            kids += [
                ft.Container(expand=True),
                ft.Container(
                    content=txt(fa_num(alert_count), size=11, font=FONT_B, color=WHITE),
                    bgcolor=BRAND_RED, border_radius=999,
                    padding=ft.Padding.symmetric(horizontal=7, vertical=1),
                ),
            ]
        items.append(
            ft.Container(
                content=ft.Row(kids, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding.symmetric(horizontal=10, vertical=9),
                border_radius=10,
                bgcolor=SIDE_ACTIVE if is_active else "transparent",
                on_click=lambda e, k=key: on_nav(k),
            )
        )

    brand = ft.Column([
        ft.Image(src="logo-white.png", height=30, fit=ft.BoxFit.CONTAIN),
        txt("پایش سلامت کارکنان", size=13, font=FONT_B, color=WHITE),
        txt("کارخانه روزتاش", size=10, font=FONT, color=SIDE_MUTED),
    ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    user = ft.Row([
        ft.CircleAvatar(radius=17, bgcolor="#3A3F44",
                        content=ft.Icon(ft.Icons.PERSON, size=16, color=WHITE)),
        ft.Column([
            txt("مهندس رستگاری", size=13, font=FONT_MED, color=SIDE_TEXT),
            txt("مسئول HSE", size=11, font=FONT, color=SIDE_MUTED),
        ], spacing=1),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    return ft.Container(
        width=236,
        bgcolor=SIDE_BG,
        padding=ft.Padding.symmetric(vertical=18, horizontal=12),
        content=ft.Column(
            [
                brand,
                ft.Container(height=10),
                ft.Divider(height=1, thickness=1, color="#2A2D30"),
                ft.Container(height=4),
                *items,
                ft.Container(expand=True),
                ft.Divider(height=1, thickness=1, color="#2A2D30"),
                user,
                ft.Container(
                    content=txt("نسخهٔ ۰٫۱ — نمونهٔ اولیه", size=10, font=FONT, color="#5A5E62"),
                    alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.only(top=6),
                ),
            ],
            spacing=6,
            expand=True,
        ),
    )
