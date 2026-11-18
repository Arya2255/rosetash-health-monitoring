# -*- coding: utf-8 -*-
"""نوار کناری ناوبری — در چیدمان راست‌به‌چپ، ابتدای صفحه.

روی موبایل نوار کناری داخل «منوی کشویی» (drawer) نمایش داده می‌شود؛
همان آیتم‌ها، همان ظاهر تیره — فقط بدون عرض ثابت.
"""

import flet as ft
from data import can_view_settings

from theme import (
    BRAND_RED, FONT, FONT_B, FONT_MED, SIDE_ACTIVE, SIDE_BG, SIDE_MUTED,
    SIDE_TEXT, WHITE, fa_num, txt,
)

NAV_ITEMS = [
    ("map", "نقشه کارخانه", ft.Icons.MAP),
    ("gateways", "گیت‌وی‌ها", ft.Icons.ROUTER),
    ("provisioning", "آماده‌سازی گیتوی", ft.Icons.SYSTEM_UPDATE_ALT),
    ("dashboard", "داشبورد", ft.Icons.DASHBOARD),
    ("live", "پایش زنده", ft.Icons.SENSORS),
    ("bands", "مچ‌بندها", ft.Icons.WATCH),
    ("employees", "کارکنان", ft.Icons.GROUPS),

    ("definitions", "تعاریف پایه", ft.Icons.CATEGORY),
    ("alerts", "هشدارها", ft.Icons.NOTIFICATIONS_ACTIVE),
    ("settings", "تنظیمات", ft.Icons.SETTINGS),
]

NAV_KEYS = frozenset(key for key, _label, _icon in NAV_ITEMS)


def active_navigation_view(view, back_to=None):
    """Resolve the highlighted section while an employee profile is open."""
    if view == "employee":
        return back_to if back_to in NAV_KEYS else "employees"
    return view


def ensure_profile_origin(state):
    """Keep profiles attached to a section; legacy state defaults to staff."""
    if state.get("view") == "employee" and state.get("back_to") not in NAV_KEYS:
        state["back_to"] = "employees"
    return state.get("back_to", "employees")


def _nav_column(active, on_nav, alert_count=0, *, role=""):
    """ستون آیتم‌های ناوبری — مشترک بین نوار کناری و منوی کشویی موبایل."""
    items = []
    for key, label, icon in NAV_ITEMS:
        if key == "settings" and not can_view_settings(role):
            continue
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
        txt("کارخانه رزتاش", size=10, font=FONT, color=SIDE_MUTED),
    ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    return ft.Column(
        [
            brand,
            ft.Container(height=10),
            ft.Divider(height=1, thickness=1, color="#2A2D30"),
            ft.Container(height=4),
            *items,
            ft.Container(expand=True),
            ft.Container(
                content=txt("نسخهٔ ۰٫۱ — نمونهٔ اولیه", size=10, font=FONT, color="#5A5E62"),
                alignment=ft.alignment.Alignment(0, 0),
                padding=ft.Padding.only(top=6),
            ),
        ],
        spacing=6,
        expand=True,
    )


def build_sidebar(active, on_nav, alert_count=0, *, role=""):
    """نوار کناری دسکتاپ — عرض ثابت تیره."""
    return ft.Container(
        width=236,
        bgcolor=SIDE_BG,
        padding=ft.Padding.symmetric(vertical=18, horizontal=12),
        content=_nav_column(active, on_nav, alert_count, role=role),
    )


def build_drawer(active, on_nav, alert_count=0, *, role=""):
    """منوی کشویی موبایل — همان آیتم‌های نوار کناری روی پنل تیره.

    انتخاب هر آیتم، هم منو را می‌بندد و هم صفحه را عوض می‌کند
    (بستن در لایهٔ اصلی برنامه انجام می‌شود).
    """
    return ft.NavigationDrawer(
        bgcolor=SIDE_BG,
        width=272,
        controls=[
            ft.Container(
                content=_nav_column(active, on_nav, alert_count, role=role),
                padding=ft.Padding.symmetric(vertical=18, horizontal=12),
            ),
        ],
    )