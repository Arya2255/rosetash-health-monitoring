# -*- coding: utf-8 -*-
"""هشدارها — آژیر مرکزی، هشدارهای فعال و تاریخچهٔ امروز."""

import flet as ft

from theme import (
    BORDER, DANGER, DANGER_BG, FONT, FONT_B, FONT_MED, INK, R_BTN, R_CARD,
    TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
from data import ALERTS_HISTORY
from components.common import card, status_chip


def _action_btn(label, icon, bg, on_click):
    return ft.Button(
        label, icon=icon, height=36,
        style=ft.ButtonStyle(bgcolor=bg, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=on_click,
    )


def alerts_view(app):
    # ── کارت آژیر مرکزی ──
    siren_on = app.siren_on
    siren_color = DANGER if siren_on else TEXT_MUTED
    siren_card = card(ft.Column([
        ft.Row([
            ft.Container(
                content=ft.Icon(ft.Icons.CAMPAIGN, size=30, color=siren_color),
                bgcolor="#FCE7E8" if siren_on else "#ECECEC",
                border_radius=12, padding=ft.Padding.all(10),
            ),
            ft.Container(expand=True),
            txt("آژیر مرکزی کارخانه", size=14, font=FONT_B, color=INK),
        ]),
        txt("در حال پخش" if siren_on else "خاموش", size=26, font=FONT_B, color=siren_color),
        txt(
            "پخش از طریق گیت‌وی — همهٔ سالن‌ها" if siren_on
            else "آخرین پخش: ۱۴:۰۲ — بابت حادثهٔ سقوط",
            size=12, font=FONT, color=TEXT_MUTED,
        ),
        ft.Container(height=4),
        ft.Row([
            ft.Button(
                "فعال‌سازی آژیر", icon=ft.Icons.VOLUME_UP, height=40, disabled=siren_on,
                style=ft.ButtonStyle(bgcolor=DANGER, color=WHITE,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.set_siren(True),
            ),
            ft.OutlinedButton(
                "توقف آژیر", icon=ft.Icons.VOLUME_OFF, height=40,
                style=ft.ButtonStyle(color=INK,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.set_siren(False),
            ),
        ], spacing=10),
    ], spacing=8), pad=18)

    # ── هشدارهای فعال ──
    active_cards = []
    for a in app.alerts_active:
        danger = a["severity"] == "danger"
        active_cards.append(ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Container(
                        content=ft.Icon(ft.Icons.SOS if danger else ft.Icons.ERROR_OUTLINE,
                                        size=20, color=WHITE if danger else WARN),
                        bgcolor=DANGER if danger else "#FCF0DC",
                        border_radius=10, padding=ft.Padding.all(9),
                    ),
                    ft.Column([
                        txt(f'{a["type"]} — {a["emp"]}', size=15, font=FONT_B, color=INK),
                        txt(f'{a["dept"]} • {a["location"]} • ساعت {fa_num(a["time"])}',
                            size=12, font=FONT, color=TEXT_MUTED),
                    ], spacing=2, expand=True),
                    status_chip("danger" if danger else "warn"),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    _action_btn(
                        "اعزام تیم امداد" if danger else "بررسی و تأیید",
                        ft.Icons.MEDICAL_SERVICES if danger else ft.Icons.CHECK,
                        DANGER if danger else INK,
                        lambda e, aa=a: app.snack(
                            "تیم امداد به محل حادثه اعزام شد" if aa["severity"] == "danger"
                            else "هشدار بررسی و تأیید شد"),
                    ),
                    ft.OutlinedButton(
                        "تماس با سرشیفت", icon=ft.Icons.PHONE, height=36,
                        style=ft.ButtonStyle(color=INK,
                                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                        on_click=lambda e: app.snack("تماس بی‌سیم با سرشیفت برقرار شد"),
                    ),
                    ft.TextButton(
                        "بستن رویداد", height=36,
                        style=ft.ButtonStyle(color=TEXT_MUTED),
                        on_click=lambda e, aid=a["id"]: app.close_alert(aid),
                    ),
                ], spacing=8),
            ], spacing=12),
            padding=16,
            bgcolor=DANGER_BG if danger else WHITE,
            border=ft.Border.all(1.5 if danger else 1, DANGER if danger else BORDER),
            border_radius=R_CARD,
        ))

    if not active_cards:
        active_cards = [ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=38, color="#1E8E4E"),
                txt("هیچ هشدار فعالی وجود ندارد", size=14, font=FONT_MED, color=TEXT_MUTED),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=36, bgcolor=WHITE, border_radius=R_CARD,
            border=ft.Border.all(1, BORDER),
            alignment=ft.Alignment.CENTER,
        )]

    active_col = ft.Column([
        ft.Row([
            txt("هشدارهای فعال", size=15, font=FONT_B, color=INK),
            txt(fa_num(len(app.alerts_active)), size=13, font=FONT_MED, color=TEXT_MUTED),
        ], spacing=8),
        *active_cards,
    ], spacing=12, expand=True)

    # ── تاریخچهٔ امروز ──
    history_rows = []
    for i, h in enumerate(ALERTS_HISTORY):
        history_rows.append(ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=17, color="#1E8E4E"),
                ft.Column([
                    txt(h["title"], size=13, font=FONT_MED, color=INK),
                    txt(h["result"], size=11, font=FONT, color=TEXT_MUTED),
                ], spacing=1, expand=True),
                txt(fa_num(h["time"]), size=12, font=FONT, color=TEXT_MUTED),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(vertical=9),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)) if i < len(ALERTS_HISTORY) - 1 else None,
        ))
    history_card = card(ft.Column([
        txt("تاریخچهٔ امروز", size=15, font=FONT_B, color=INK),
        *history_rows,
    ], spacing=6), pad=18)

    return ft.Column([
        ft.Row([
            ft.Container(width=340, content=siren_card),
            active_col,
        ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.START),
        history_card,
    ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)
