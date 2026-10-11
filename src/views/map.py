# -*- coding: utf-8 -*-
"""نقشهٔ کارخانه — موقعیت گیت‌وی‌ها و کارکنان روی پلان واقعی.

تصویر پایه، پلان برچسب‌دار کارخانه است (src/assets/factory-map.jpg).
نشانگرها از لایهٔ داده می‌آیند (data.MAP_GATEWAYS) و موقعیت‌ها نسبی‌اند
تا با هر اندازه‌ای از نمایش درست بنشینند.

چهار نقطهٔ پیشنهادی نصب از برگهٔ پوشش می‌آید و صریحاً غیرقطعی است؛
پس از تست میدانی، موقعیت قطعی هر گیت‌وی (kind="installed" همراه gw)
این‌جا تثبیت می‌شود و همان لحظه مچ‌بندهای در دید پل زنده هم زیر همان
گیت‌وی روی نقشه نقطه می‌گیرند — بدون هیچ تغییر دیگری در این فایل.
"""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, OK, TEXT_MAIN, TEXT_MUTED, WARN,
    WHITE, fa_num, txt,
)
from data import (
    MAP_ENTRANCE, MAP_GATEWAYS, MAP_IMAGE, MAP_IMAGE_H, MAP_IMAGE_W,
    live_available, live_status,
)
from components.common import card, section_header

_RATIO = MAP_IMAGE_W / MAP_IMAGE_H
_COLOR = {"proposed": WARN, "installed": OK}
_ENTRY_COLOR = "#5B6B7B"
_BAND_COLOR = "#1A5FB4"
_PIN = 30          # قطر پین نشانگر
_CHIP_W = 98       # عرض برچسب زیر پین


def _display_size(app):
    """اندازهٔ نمایش نقشه — از ارتفاع پنجره، با کف و سقف معقول."""
    h = 520
    try:
        wh = int(getattr(app.page, "height", None) or 0)
        if wh >= 560:
            h = max(430, min(800, wh - 200))
    except Exception:
        pass
    return int(round(h * _RATIO)), h


def _label_chip(text, width, size=11, color=INK, font=None):
    return ft.Container(
        width=width,
        content=txt(text, size=size, font=font or FONT_MED, color=color,
                    text_align=ft.TextAlign.CENTER),
        bgcolor=WHITE, border_radius=7,
        border=ft.Border.all(1, BORDER),
        padding=ft.Padding.symmetric(horizontal=4, vertical=3),
    )


def _gw_marker(n, item, W, H):
    """نشانگر شماره‌دار گیت‌وی — پین رنگی با برچسب زیر آن."""
    cx, cy = item["x"] * W, item["y"] * H
    color = _COLOR.get(item.get("kind"), WARN)
    pin = ft.Container(
        width=_PIN, height=_PIN, border_radius=_PIN // 2, bgcolor=color,
        border=ft.Border.all(2.5, WHITE),
        shadow=ft.BoxShadow(blur_radius=7, color="#40000000"),
        alignment=ft.Alignment.CENTER,
        content=txt(fa_num(n), size=13, font=FONT_B, color=WHITE),
    )
    col = ft.Column(
        [pin, _label_chip(item.get("short") or item["label"], _CHIP_W, size=10.5)],
        spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    left = min(max(cx - _CHIP_W / 2, 3), W - _CHIP_W - 3)
    return ft.Container(content=col, left=left, top=cy - _PIN / 2)


def _entry_marker(W, H):
    """نشانگر ورودی کارخانه — کوچک و کم‌رنگ، فقط برای جهت‌یابی."""
    cx, cy = MAP_ENTRANCE["x"] * W, MAP_ENTRANCE["y"] * H
    dot = ft.Container(
        width=11, height=11, border_radius=6, bgcolor=_ENTRY_COLOR,
        border=ft.Border.all(2, WHITE),
        shadow=ft.BoxShadow(blur_radius=4, color="#40000000"),
    )
    col = ft.Column(
        [dot, _label_chip(MAP_ENTRANCE["label"], 100, size=9.5,
                          color=TEXT_MUTED, font=FONT)],
        spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    left = min(max(cx - 50, 3), W - 103)
    return ft.Container(content=col, left=left, top=cy - 5)


def _worker_dots(W, H):
    """مچ‌بندهای در دید — فقط برای گیت‌وی‌هایی که موقعیت قطعی دارند.

    تا وقتی موقعیت هیچ گیت‌وی قطعی نشده، خالی برمی‌گردد؛ پس از نصب
    واقعی، هر مچ‌بند همان لحظه کنار گیت‌وی خودش نقطه می‌گیرد.
    """
    dots = []
    try:
        pos = {g.get("gw"): g for g in MAP_GATEWAYS
               if g.get("kind") == "installed" and g.get("gw")}
        if not pos:
            return dots
        d = live_status() or {}
        for i, b in enumerate(d.get("bands") or []):
            g = pos.get(b.get("gw"))
            if not g:
                continue
            cx = g["x"] * W + (i % 4 - 1.5) * 18
            cy = g["y"] * H + _PIN / 2 + 46 + (i // 4) * 18
            dots.append(ft.Container(
                width=14, height=14, border_radius=7, bgcolor=_BAND_COLOR,
                border=ft.Border.all(2, WHITE),
                shadow=ft.BoxShadow(blur_radius=4, color="#40000000"),
                left=min(max(cx - 7, 2), W - 16), top=cy,
                tooltip=f"{b.get('mac') or 'مچ‌بند'} — {g['label']}",
            ))
    except Exception:
        return []
    return dots


def _gw_row(n, item):
    """ردیف فهرست گیت‌وی — هم‌شماره با نشانگر روی نقشه."""
    color = _COLOR.get(item.get("kind"), WARN)
    if item.get("kind") == "installed":
        sub = f"نصب‌شده — {item.get('gw') or '—'}"
    else:
        sub = "پیشنهادی — در انتظار تست میدانی"
    return ft.Row([
        ft.Container(
            width=22, height=22, border_radius=11, bgcolor=color,
            alignment=ft.Alignment.CENTER,
            content=txt(fa_num(n), size=11, font=FONT_B, color=WHITE),
        ),
        ft.Column([
            txt(item["label"], size=13, font=FONT_MED, color=INK),
            txt(sub, size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=1, expand=True),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _legend_card():
    def item(color, label, size=10):
        return ft.Row([
            ft.Container(
                width=size, height=size, border_radius=size // 2, bgcolor=color,
                border=ft.Border.all(1.5, WHITE),
                shadow=ft.BoxShadow(blur_radius=3, color="#33000000"),
            ),
            txt(label, size=12, font=FONT, color=TEXT_MAIN),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    return card(ft.Column([
        txt("راهنمای نقشه", size=14, font=FONT_B, color=INK),
        item(WARN, "نقطهٔ پیشنهادی نصب گیت‌وی — غیرقطعی"),
        item(OK, "گیت‌وی نصب‌شده با موقعیت قطعی"),
        item(_ENTRY_COLOR, "ورودی کارخانه"),
    ], spacing=8), pad=14)


def _live_card():
    """وضعیت زندهٔ گیت‌وی‌ها — از پل محلی؛ بدون موقعیت روی نقشه."""
    rows = []
    if live_available():
        d = live_status() or {}
        for g in d.get("gateways") or []:
            on = bool(g.get("online"))
            rows.append(ft.Row([
                ft.Container(width=8, height=8, border_radius=4,
                             bgcolor=OK if on else "#9AA0A6"),
                txt(g.get("gw") or "—", size=12, font=FONT_MED, color=INK),
                ft.Container(expand=True),
                txt("آنلاین" if on else "آفلاین", size=11, font=FONT,
                    color=OK if on else TEXT_MUTED),
            ], spacing=7, vertical_alignment=ft.CrossAxisAlignment.CENTER))
    if rows:
        rows.append(txt("موقعیت روی نقشه پس از نصب در کارخانه ثبت می‌شود.",
                        size=11, font=FONT, color=TEXT_MUTED))
    else:
        rows.append(txt("پل زنده در دسترس نیست — فقط نقاط پیشنهادی نمایش داده می‌شود.",
                        size=12, font=FONT, color=TEXT_MUTED))
    return card(ft.Column([
        txt("وضعیت زنده", size=14, font=FONT_B, color=INK),
        *rows,
    ], spacing=7), pad=14)


def map_view(app):
    """صفحهٔ «نقشهٔ کارخانه» — پلان واقعی + نشانگرهای گیت‌وی."""
    W, H = _display_size(app)

    markers = [_gw_marker(i, item, W, H)
               for i, item in enumerate(MAP_GATEWAYS, start=1)]
    markers.append(_entry_marker(W, H))
    markers.extend(_worker_dots(W, H))

    plan = ft.Stack([
        ft.Image(src=MAP_IMAGE, width=W, height=H, fit=ft.BoxFit.FILL),
        *markers,
    ], width=W, height=H)

    plan_card = card(plan, pad=10)

    panel = ft.Column([
        card(ft.Column([
            txt("نقاط نصب گیت‌وی", size=14, font=FONT_B, color=INK),
            *[_gw_row(i, item) for i, item in enumerate(MAP_GATEWAYS, start=1)],
            ft.Divider(height=1, thickness=1, color=BORDER),
            txt("موقعیت‌ها بعد از تست میدانی تثبیت می‌شود.",
                size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=10), pad=14),
        _legend_card(),
        _live_card(),
    ], width=296, spacing=12, scroll=ft.ScrollMode.AUTO)

    header = section_header(
        "نقشهٔ کارخانه",
        "پلان کارخانه روزتاش — نقاط نصب گیت‌وی؛ پس از تست میدانی، "
        "موقعیت زندهٔ کارکنان روی همین نقشه می‌آید.",
    )

    return ft.Column([
        header,
        ft.Row([
            ft.Container(content=plan_card, expand=True,
                         alignment=ft.Alignment.CENTER),
            panel,
        ], spacing=14, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
    ], spacing=14, expand=True)
