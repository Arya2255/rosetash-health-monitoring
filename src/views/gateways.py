# -*- coding: utf-8 -*-
"""بخش «گیت‌وی‌ها» — تعریف گیت‌وی، منطقه و چیدمان روی نقشهٔ کارخانه.

دفتر گیت‌وی‌ها روی پل است (backend/bridge.py — /api/gateways)؛ این صفحه
فهرست ادغام‌شده با وضعیت زندهٔ شبکه را نشان می‌دهد:

  - تعریف‌شده‌ها: نام، شناسه، منطقه، نصب‌شده/پیشنهادی، آنلاین/آفلاین و
    چیده‌شدن روی نقشه — با ویرایش، حذف و میان‌بر «روی نقشه».
  - کشف‌شده‌ها: گیت‌وی‌هایی که در شبکه دیده شده‌اند ولی هنوز تعریف نشده‌اند
    — با دکمهٔ «تعریف» با همان شناسهٔ موجود در شبکه.
  - نبود پل: نقاط نمونهٔ نقشه با برچسب «دادهٔ نمایشی» — بدون ویرایش.

جابه‌جایی پین‌ها روی نقشه در صفحهٔ «نقشه کارخانه» و حالت «چیدن» انجام
می‌شود؛ دکمهٔ «روی نقشه» همان‌جا می‌برد.
"""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN, R_CARD,
    TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
from data import MAP_GATEWAYS, live_gateways
from components.common import SHADOW, card, rel_age, section_header
from components.gateway_form import (
    open_gateway_delete, open_gateway_form, suggest_gw_id,
)

_KIND_FA = {"installed": "نصب‌شده", "proposed": "پیشنهادی"}
_DISCOVERED = "#9AA0A6"
_BG_OK = "#E6F4EB"
_BG_WARN = "#FCF0DC"
_BG_GRAY = "#F1F2F4"


def _chip(text, fg, bg):
    """چیپ کوچک وضعیت — هم‌خانوادهٔ چیپ‌های بقیهٔ صفحه‌ها."""
    return ft.Container(
        content=txt(text, size=10.5, font=FONT_MED, color=fg),
        bgcolor=bg, border_radius=999,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )


def _kind_chip(item):
    if item.get("registered") is False:
        return _chip("کشف‌شده", TEXT_MUTED, _BG_GRAY)
    if item.get("kind") == "installed":
        return _chip("نصب‌شده", OK, _BG_OK)
    return _chip("پیشنهادی", WARN, _BG_WARN)


def _status_chip(item):
    if item.get("online"):
        return _chip("آنلاین", OK, _BG_OK)
    if item.get("live"):
        return _chip("آفلاین", TEXT_MUTED, _BG_GRAY)
    if item.get("registered") is False:
        return _chip("در شبکه دیده شد", TEXT_MUTED, _BG_GRAY)
    return _chip("هنوز دیده نشده", TEXT_MUTED, _BG_GRAY)


def _placed_chip(item):
    if item.get("x") is not None and item.get("y") is not None:
        return _chip("روی نقشه", OK, _BG_OK)
    return _chip("چیده‌نشده", TEXT_MUTED, _BG_GRAY)


def _gw_card_row(item, on_edit=None, on_delete=None, on_map=None, actions=True):
    """کارت یک گیت‌وی — چیپ‌های وضعیت، زیرنویس و دکمه‌های اقدام."""
    gid = str(item.get("gw") or "—")
    label = item.get("label") or gid
    subs = [gid]
    if item.get("zone"):
        subs.append(str(item["zone"]))
    if item.get("age_s") is not None:
        subs.append(f"آخرین تماس {rel_age(item['age_s'])}")
    buttons = []
    if actions:
        buttons = [
            ft.IconButton(ft.Icons.MAP, tooltip="نمایش روی نقشهٔ کارخانه",
                          icon_size=18, on_click=on_map),
            ft.IconButton(ft.Icons.EDIT, tooltip="ویرایش", icon_size=18,
                          on_click=on_edit),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="حذف از دفتر",
                          icon_size=18, icon_color=OFFLINE, on_click=on_delete),
        ]
    return card(ft.Row([
        ft.Container(
            width=34, height=34, border_radius=10, bgcolor=_BG_GRAY,
            alignment=ft.alignment.Alignment(0, 0),
            content=ft.Icon(ft.Icons.ROUTER, size=18,
                            color=OK if item.get("online") else TEXT_MUTED),
        ),
        ft.Column([
            ft.Row([
                txt(label, size=13.5, font=FONT_MED, color=INK),
                _kind_chip(item),
                _status_chip(item),
                _placed_chip(item),
            ], spacing=6, wrap=True),
            txt(" — ".join(subs), size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=3, expand=True),
        *buttons,
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=12)


def _demo_banner():
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.CLOUD_OFF, size=18, color=WARN),
            txt("پل محلی در دسترس نیست — فهرست نمایشی؛ تعریف و ذخیره "
                "نیاز به بالا بودن پل دارد", size=13, font=FONT_MED,
                color=WARN, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=_BG_WARN, border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )


def gateways_view(app):
    """صفحهٔ «گیت‌وی‌ها» — دفتر گیت‌وی پل + کشف‌شده‌های شبکه."""
    rows = live_gateways()
    bridge_up = rows is not None
    rows = rows or []
    registered = [r for r in rows if r.get("registered") is not False]
    discovered = [r for r in rows if r.get("registered") is False]

    def _refresh():
        app.render()

    def _new(e):
        open_gateway_form(app, rows=rows, on_saved=_refresh)

    new_btn = ft.Button(
        "گیت‌وی جدید",
        icon=ft.Icons.ADD_LOCATION_ALT,
        disabled=not bridge_up,
        tooltip=None if bridge_up else "برای تعریف، پل باید بالا باشد",
        style=ft.ButtonStyle(
            bgcolor=INK, color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        ),
        on_click=_new,
    )
    header = section_header(
        "گیت‌وی‌ها",
        "تعریف گیت‌وی، منطقه و چیدمان روی نقشه — شناسهٔ هر گیت‌وی همان است "
        "که در config.json برد می‌آید؛ پس از نصب، دادهٔ زنده خودکار به "
        "همین ردیف می‌چسبد.",
        trailing=new_btn,
    )

    # ── شمارنده‌ها ──
    def _counter(value, label, color=INK):
        return ft.Column([
            txt(fa_num(value), size=24, font=FONT_B, color=color),
            txt(label, size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    placed_count = sum(1 for r in registered
                       if r.get("x") is not None and r.get("y") is not None)
    online_count = sum(1 for r in rows if r.get("online"))
    counters = card(ft.Row([
        _counter(len(registered), "تعریف‌شده"),
        ft.Container(width=1, height=34, bgcolor=BORDER),
        _counter(sum(1 for r in registered if r.get("kind") == "installed"),
                 "نصب‌شده"),
        ft.Container(width=1, height=34, bgcolor=BORDER),
        _counter(sum(1 for r in registered if r.get("kind") != "installed"),
                 "پیشنهادی"),
        ft.Container(width=1, height=34, bgcolor=BORDER),
        _counter(online_count, "آنلاین", OK),
        ft.Container(width=1, height=34, bgcolor=BORDER),
        _counter(placed_count, "روی نقشه", OK),
    ], spacing=10, run_spacing=10, wrap=True,
        alignment=ft.MainAxisAlignment.SPACE_EVENLY), pad=12)

    # ── فهرست تعریف‌شده‌ها ──
    list_col = ft.Column([], spacing=8)
    if bridge_up and registered:
        for item in registered:
            def on_map(e):
                app.go("map")

            def on_edit(e, item=item):
                open_gateway_form(app, row=item, rows=rows, on_saved=_refresh)

            def on_delete(e, item=item):
                open_gateway_delete(app, item, on_done=_refresh)

            list_col.controls.append(
                _gw_card_row(item, on_edit, on_delete, on_map))
    elif bridge_up:
        list_col.controls.append(txt(
            "هنوز گیت‌ویی تعریف نشده — با «گیت‌وی جدید» شروع کن. برای هر "
            "برد، همان شناسه‌ای را بگذار که در config.json می‌آید.",
            size=12, font=FONT, color=TEXT_MUTED))
    else:
        for g in MAP_GATEWAYS:
            list_col.controls.append(
                _gw_card_row(dict(g, registered=None), actions=False))

    count_lbl = txt(f"{fa_num(len(registered))} مورد" if registered else "",
                    size=11, font=FONT, color=TEXT_MUTED)
    registered_card = card(ft.Column([
        ft.Row([
            txt("گیت‌وی‌های تعریف‌شده", size=14, font=FONT_B, color=INK),
            ft.Container(expand=True),
            count_lbl,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        list_col,
    ], spacing=10), pad=14)

    # ── کشف‌شده‌های شبکه ──
    blocks = [header]
    if not bridge_up:
        blocks.append(_demo_banner())
    blocks.append(counters)
    blocks.append(registered_card)
    if discovered:
        disc_col = ft.Column([], spacing=8)
        for item in discovered:
            gid = str(item.get("gw") or "")

            def _define(e, gid=gid, item=item):
                open_gateway_form(
                    app, gw=gid,
                    row={"gw": gid, "kind": "installed",
                         "zone": item.get("zone") or ""},
                    rows=rows, on_saved=_refresh)

            sub = "این گیت‌وی داده می‌فرستد ولی هنوز تعریف نشده"
            if item.get("zone"):
                sub += f" — منطقهٔ {item['zone']}"
            disc_col.controls.append(ft.Container(
                content=ft.Row([
                    ft.Container(
                        width=34, height=34, border_radius=10, bgcolor=_BG_GRAY,
                        alignment=ft.alignment.Alignment(0, 0),
                        content=ft.Icon(ft.Icons.WIFI_TETHERING, size=18,
                                        color=_DISCOVERED),
                    ),
                    ft.Column([
                        txt(gid, size=13.5, font=FONT_MED, color=INK),
                        txt(sub + " — تعریفش کن تا روی نقشه جا بگیرد.",
                            size=11, font=FONT, color=TEXT_MUTED),
                    ], spacing=2, expand=True),
                    ft.Button(
                        "تعریف", icon=ft.Icons.ADD,
                        style=ft.ButtonStyle(
                            bgcolor=WHITE, color=INK,
                            shape=ft.RoundedRectangleBorder(radius=R_BTN),
                            side=ft.BorderSide(1, BORDER),
                        ),
                        on_click=_define),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=WHITE, border_radius=R_CARD,
                border=ft.Border.all(1, BORDER), shadow=SHADOW, padding=12))
        blocks.append(card(ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.WIFI_TETHERING, size=16, color=WARN),
                txt("کشف‌شده از شبکه — هنوز تعریف نشده", size=14,
                    font=FONT_B, color=INK),
            ], spacing=6),
            disc_col,
        ], spacing=10), pad=14))

    # ── میان‌بر نقشه ──
    blocks.append(card(ft.Row([
        ft.Icon(ft.Icons.MAP, size=18, color=INK),
        txt("جابه‌جایی گیت‌وی‌ها روی نقشه: صفحهٔ «نقشه کارخانه» → دکمهٔ "
            "«چیدن روی نقشه» — پین را بکش و رها کن؛ موقعیت خودکار ذخیره "
            "می‌شود.", size=12, font=FONT, color=TEXT_MAIN, expand=True),
        ft.TextButton("نقشهٔ کارخانه", icon=ft.Icons.OPEN_IN_NEW,
                      on_click=lambda e: app.go("map")),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=12))

    return ft.Column(blocks, spacing=14, scroll=ft.ScrollMode.AUTO)