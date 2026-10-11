# -*- coding: utf-8 -*-
"""نقشهٔ کارخانه — موقعیت گیت‌وی‌ها و کارکنان روی پلان واقعی.

تصویر پایه، پلان برچسب‌دار کارخانه است (src/assets/factory-map.jpg).
نشانگرها از لایهٔ داده می‌آیند (data.MAP_GATEWAYS) و موقعیت‌ها نسبی‌اند
تا با هر اندازه‌ای از نمایش درست بنشینند.

گیت‌وی نصب‌شده (kind="installed" همراه gw) به وضعیت زندهٔ پل وصل است:
هر مچ‌بند در دیدش زیر همان گیت‌وی نقطه می‌گیرد و برچسب «≈ فاصلهٔ تخمینی»
زیر نقطه می‌آید — برای تست میدانی برد. صفحه هر ۲ ثانیه خودش تازه می‌شود
تا هنگام راه‌رفتن هم به‌روز بماند.
"""

import asyncio
import time
from datetime import datetime

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, OK, TEXT_MAIN, TEXT_MUTED, WARN,
    WHITE, fa_clock, fa_num, txt,
)
from data import (
    MAP_ENTRANCE, MAP_GATEWAYS, MAP_IMAGE, MAP_IMAGE_H, MAP_IMAGE_W,
    live_status,
)
from components.common import card, section_header

_RATIO = MAP_IMAGE_W / MAP_IMAGE_H
_COLOR = {"proposed": WARN, "installed": OK}
_ENTRY_COLOR = "#5B6B7B"
_BAND_COLOR = "#1A5FB4"
_PIN = 30          # قطر پین نشانگر
_CHIP_W = 98       # عرض برچسب زیر پین
_M_CHIP_W = 58     # عرض برچسب «≈ فاصله» زیر نقطهٔ مچ‌بند

# تخمین فاصله از قدرت سیگنال — مدل تضعیف مسیر:
#     فاصله ≈ ۱۰ به‌توان ((A − RSSI) / ۱۰×n)
# A سیگنال مرجع روی ۱ متر و n ضریب محیط است. عدد فقط تخمین است؛ دیوار،
# بدن و شلوغی رادیویی آن را کم و زیاد می‌کند — برای تست میدانی برد.
_PATH_A = -59.0
_PATH_N = 2.5
_STALE_AGE = 30.0  # از این سن، دیدن کهنه است و نقطه کم‌رنگ می‌شود (TTL پل: ۶۰ ثانیه)


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


def _rssi_color(rssi):
    """رنگ نشانگر بر پایهٔ قدرت سیگنال — هم‌خوان با نماهای دیگر."""
    if rssi is None:
        return "#9AA0A6"
    return OK if rssi >= -75 else WARN


def _approx_m(rssi):
    """فاصلهٔ تخمینی به متر از قدرت سیگنال — تقریبی، فقط برای تست برد."""
    try:
        r = float(rssi)
    except (TypeError, ValueError):
        return None
    return 10 ** ((_PATH_A - r) / (10 * _PATH_N))


def _m_text(rssi):
    m = _approx_m(rssi)
    if m is None:
        return "در دید"
    return f"≈ {fa_num(max(1, round(m)))} متر"


def _rel(seconds):
    if seconds is None:
        return "—"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{fa_num(seconds)} ثانیه پیش"
    if seconds < 3600:
        return f"{fa_num(seconds // 60)} دقیقه پیش"
    return f"{fa_num(seconds // 3600)} ساعت پیش"


def _gw_name(gw):
    """نام خوانا برای شناسهٔ گیت‌وی — از همان فهرست نقشه."""
    for g in MAP_GATEWAYS:
        if g.get("gw") == gw:
            return g.get("label") or str(gw)
    return str(gw or "—")


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


def _worker_dots(W, H, doc=None):
    """مچ‌بندهای در دید — زیر گیت‌وی نصب‌شده‌ای که دیده‌شان.

    به‌ازای هر مچ‌بند یک نقطه و برچسب «≈ فاصلهٔ تخمینی» می‌آید. فاصله از
    قدرت سیگنال حساب می‌شود و فقط برای تست میدانی برد است — نه موقعیت
    واقعی روی پلان. دیدن کهنه‌تر از _STALE_AGE کم‌رنگ نشان داده می‌شود.
    """
    dots = []
    try:
        pos = {g.get("gw"): g for g in MAP_GATEWAYS
               if g.get("kind") == "installed" and g.get("gw")}
        if not pos:
            return dots
        d = doc if doc is not None else (live_status() or {})
        for i, b in enumerate(d.get("bands") or []):
            g = pos.get(b.get("gw"))
            if not g:
                continue
            rssi = b.get("rssi")
            age = b.get("age_s")
            stale = age is not None and age > _STALE_AGE
            cx = g["x"] * W + (i % 4 - 1.5) * 18
            cy = g["y"] * H + _PIN / 2 + 46 + (i // 4) * 18
            dot = ft.Container(
                width=14, height=14, border_radius=7,
                bgcolor="#9AA0A6" if stale else _rssi_color(rssi),
                border=ft.Border.all(2, WHITE),
                shadow=ft.BoxShadow(blur_radius=4, color="#40000000"),
            )
            chip = ft.Container(
                width=_M_CHIP_W,
                content=txt(_m_text(rssi), size=9.5, font=FONT_MED,
                            color=TEXT_MUTED if stale else INK,
                            text_align=ft.TextAlign.CENTER),
                bgcolor=WHITE, border_radius=7,
                border=ft.Border.all(1, BORDER),
                padding=ft.Padding.symmetric(horizontal=3, vertical=1),
            )
            col = ft.Column([dot, chip], spacing=2,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            left = min(max(cx - _M_CHIP_W / 2, 2), W - _M_CHIP_W - 2)
            rssi_dbm = f"{fa_num(round(rssi))} dBm" if rssi is not None else "—"
            dots.append(ft.Container(
                content=col, left=left, top=cy,
                tooltip=f"{b.get('mac') or 'مچ‌بند'} — {g.get('label')} — "
                        f"آنتن {rssi_dbm} — {_rel(age)}",
            ))
    except Exception:
        return []
    return dots


def _gw_row(n, item):
    """ردیف فهرست گیت‌وی — هم‌شماره با نشانگر روی نقشه."""
    color = _COLOR.get(item.get("kind"), WARN)
    if item.get("kind") == "installed":
        sub = f"نصب‌شده — {item.get('gw') or '—'}"
        if item.get("testing"):
            sub += " — در حال تست فاصله"
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
        item(OK, "گیت‌وی نصب‌شده — دادهٔ زنده"),
        item(_BAND_COLOR, "مچ‌بند در دید — برچسب ≈ فاصلهٔ تخمینی"),
        item(_ENTRY_COLOR, "ورودی کارخانه"),
    ], spacing=8), pad=14)


def _device_row(dot_color, title, sub):
    """یک ردیف دستگاه — نقطهٔ وضعیت، عنوان و شرح."""
    return ft.Row([
        ft.Container(width=8, height=8, border_radius=4, bgcolor=dot_color),
        ft.Column([
            txt(title, size=12, font=FONT_MED, color=INK),
            txt(sub, size=10.5, font=FONT, color=TEXT_MUTED),
        ], spacing=1, expand=True),
    ], spacing=7, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _live_rows(d, watch):
    """ردیف‌های وضعیت زنده — گیت‌وی‌ها، مچ‌بندهای در دید و آمار تست فاصله."""
    rows = []
    d = d or {}
    if not d.get("ok"):
        rows.append(txt("پل زنده در دسترس نیست — فقط نقاط نقشه نمایش داده می‌شود.",
                        size=11, font=FONT, color=TEXT_MUTED))
        return rows
    gws = d.get("gateways") or []
    bands = d.get("bands") or []
    if not gws:
        rows.append(txt("هنوز گیت‌ویی در پل ثبت نشده…", size=11, font=FONT,
                        color=TEXT_MUTED))
    for g in gws:
        on = bool(g.get("online"))
        gw_id = str(g.get("gw") or "—")
        sub = f"{gw_id} — {'آنلاین' if on else 'آفلاین'}"
        if g.get("fw"):
            sub += f" — نسخهٔ {g.get('fw')}"
        rows.append(_device_row(OK if on else "#9AA0A6", _gw_name(gw_id), sub))
    if not bands:
        rows.append(txt("مچ‌بندی در دید نیست — از گیت‌وی دور شده یا مچ‌بند همراه نیست.",
                        size=11, font=FONT, color=TEXT_MUTED))
    for b in bands:
        rssi = b.get("rssi")
        rssi_txt = f"{fa_num(round(rssi))}" if rssi is not None else "—"
        sub = (f"آنتن {rssi_txt} dBm — {_m_text(rssi)}"
               f" — {_rel(b.get('age_s'))}")
        rows.append(_device_row(_rssi_color(rssi),
                                str(b.get("mac") or "مچ‌بند"), sub))
    if watch.get("weakest") is not None:
        mw = _approx_m(watch["weakest"])
        mw_txt = f"≈ {fa_num(max(1, round(mw)))} متر" if mw is not None else "—"
        stamp = (fa_clock(datetime.fromtimestamp(watch["weakest_at"]))
                 if watch.get("weakest_at") else "—")
        rows.append(txt(f"دورترین تخمین این نشست — ضعیف‌ترین "
                        f"{fa_num(round(watch['weakest']))} dBm — {mw_txt}"
                        f" — ساعت {stamp}", size=10.5, font=FONT,
                        color=TEXT_MUTED))
        rows.append(txt(f"{fa_num(watch.get('samples') or 0)} مشاهدهٔ مچ‌بند در این نشست",
                        size=10.5, font=FONT, color=TEXT_MUTED))
    rows.append(txt("فاصله تخمینی است — از قدرت سیگنال حساب می‌شود؛ دیوار و بدن "
                    "آن را کم و زیاد می‌کند.", size=10.5, font=FONT,
                    color=TEXT_MUTED))
    return rows


def map_view(app):
    """صفحهٔ «نقشهٔ کارخانه» — پلان واقعی + نشانگرهای زندهٔ گیت‌وی و مچ‌بند."""
    W, H = _display_size(app)
    state = app.state
    gen = state.get("map_gen", 0) + 1
    state["map_gen"] = gen
    watch = state.setdefault("map_watch", {"weakest": None, "weakest_at": None,
                                           "samples": 0, "last_seen": None})

    stack = ft.Stack(width=W, height=H)

    def _draw_plan(doc=None):
        markers = [_gw_marker(i, item, W, H)
                   for i, item in enumerate(MAP_GATEWAYS, start=1)]
        markers.append(_entry_marker(W, H))
        markers.extend(_worker_dots(W, H, doc=doc))
        stack.controls = [
            ft.Image(src=MAP_IMAGE, width=W, height=H, fit=ft.BoxFit.FILL),
            *markers,
        ]

    live_col = ft.Column([], spacing=7)

    def _apply(d):
        # آمار تست فاصله — ضعیف‌ترین سیگنال دیده‌شده در این نشست
        for b in (d or {}).get("bands") or []:
            rssi = b.get("rssi")
            if rssi is None:
                continue
            seen = b.get("seen_at")
            if seen and seen != watch.get("last_seen"):
                watch["last_seen"] = seen
                watch["samples"] = (watch.get("samples") or 0) + 1
                if watch["weakest"] is None or rssi < watch["weakest"]:
                    watch["weakest"] = rssi
                    watch["weakest_at"] = time.time()
        _draw_plan(d)
        live_col.controls = _live_rows(d, watch)

    doc = live_status()
    _apply(doc)

    async def _loop():
        while state.get("view") == "map" and state.get("map_gen") == gen:
            try:
                _apply(live_status())
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(2)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    plan_card = card(stack, pad=10)

    panel = ft.Column([
        # کارت تست زنده اول — هنگام راه‌رفتن بدون اسکرول دیده شود
        card(ft.Column([
            txt("وضعیت زنده و تست فاصله", size=14, font=FONT_B, color=INK),
            live_col,
        ], spacing=7), pad=14),
        _legend_card(),
        card(ft.Column([
            txt("نقاط نصب گیت‌وی", size=14, font=FONT_B, color=INK),
            *[_gw_row(i, item) for i, item in enumerate(MAP_GATEWAYS, start=1)],
            txt("موقعیت قطعی پس از تست میدانی تثبیت می‌شود.",
                size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=10), pad=14),
    ], width=296, spacing=12, scroll=ft.ScrollMode.AUTO)

    header = section_header(
        "نقشهٔ کارخانه",
        "پلان کارخانه روزتاش — گیت‌وی‌های نصب‌شده «سالن فیلتر ۱» و «انبار محصولات»؛ "
        "مچ‌بندهای در دید هر ۲ ثانیه زیر گیت‌وی مربوطه نقطه می‌گیرند.",
    )

    return ft.Column([
        header,
        ft.Row([
            ft.Container(content=plan_card, expand=True,
                         alignment=ft.Alignment.CENTER),
            panel,
        ], spacing=14, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
    ], spacing=14, expand=True)
