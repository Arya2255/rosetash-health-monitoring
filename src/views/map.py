# -*- coding: utf-8 -*-
"""نقشهٔ کارخانه — موقعیت گیت‌وی‌ها و کارکنان روی پلان واقعی.

تصویر پایه، پلان برچسب‌دار کارخانه است (src/assets/factory-map.jpg).
گیت‌وی‌ها از دفتر پل می‌آیند (بخش «گیتوی‌ها» — ردیف‌های snapshot با
موقعیت نسبی x/y)؛ اگر پل نبود، همان نقاط نمایشی MAP_GATEWAYS با برچسب
«غیرقابل ویرایش» نشان داده می‌شود.

حالت «چیدن روی نقشه»: پین‌ها با کشیدن ماوس جابه‌جا می‌شوند و موقعیت در
دفتر پل ذخیره می‌شود؛ پین چیده‌نشده فقط در همین حالت دیده می‌شود.

گیت‌وی نصب‌شده به وضعیت زندهٔ پل وصل است: هر مچ‌بند در دیدش زیر همان
گیت‌وی نقطه می‌گیرد و برچسب «≈ فاصلهٔ تخمینی» زیر نقطه می‌آید — برای
تست میدانی برد. صفحه هر ۲ ثانیه خودش تازه می‌شود تا هنگام راه‌رفتن هم
به‌روز بماند.
"""

import asyncio
import os
import time
from datetime import datetime

import flet as ft

from theme import (
    BORDER, BRAND_RED, FONT, FONT_B, FONT_MED, INK, OK, TEXT_MAIN, TEXT_MUTED,
    WARN, WHITE, fa_clock, fa_num, txt,
)
from data import (
    MAP_ENTRANCE, MAP_GATEWAYS, MAP_IMAGE, MAP_IMAGE_H, MAP_IMAGE_W,
    live_status, save_gateway, can_edit_map,
)
from layout import is_phone, page_w
from components.common import card, section_header
from components.gateway_form import open_gateway_form

_RATIO = MAP_IMAGE_W / MAP_IMAGE_H
_COLOR = {"proposed": WARN, "installed": OK}
_DISCOVERED = "#9AA0A6"   # گیت‌وی کشف‌شده از شبکه که هنوز تعریف نشده
_ENTRY_COLOR = "#5B6B7B"
_BAND_COLOR = "#1A5FB4"
_PIN = 30          # قطر پین نشانگر
_CHIP_W = 98       # عرض برچسب زیر پین
_M_CHIP_W = 58     # عرض برچسب «≈ فاصله» زیر نقطهٔ مچ‌بند

# تخمین فاصله از قدرت سیگنال — مدل تضعیف مسیر:
#     فاصله ≈ ۱۰ به‌توان ((A − RSSI) / ۱۰×n)
# A سیگنال مرجع روی ۱ متر و n ضریب محیط است. عدد فقط تخمین است؛ دیوار،
# بدن و شلوغی رادیویی آن را کم و زیاد می‌کند — برای تست میدانی برد.
_PATH_A = -82.0  # Calibrated: RSSI at 1 meter
_PATH_N = 2.5     # Indoor path loss exponent
_STALE_AGE = 30.0  # از این سن، دیدن کهنه است و نقطه کم‌رنگ می‌شود (TTL پل: ۶۰ ثانیه)


def _display_size(app):
    """اندازهٔ نمایش نقشه — دسکتاپ: از ارتفاع پنجره؛ موبایل: از عرض صفحه."""
    if is_phone(app):
        w = max(250, min(460, page_w(app) - 36))
        return int(round(w)), int(round(w / _RATIO))
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


def _gw_name(gw, gw_rows=None):
    """نام خوانا برای شناسهٔ گیت‌وی — اول دفتر گیت‌وی‌های پل، بعد فهرست نقشه."""
    for g in (gw_rows or []):
        if g.get("gw") == gw:
            return g.get("label") or str(gw)
    for g in MAP_GATEWAYS:
        if g.get("gw") == gw:
            return g.get("label") or str(gw)
    return str(gw or "—")


def _short_label(item):
    """برچسب کوتاه زیر پین — بلندها با «…» کوتاه می‌شوند تا پین‌ها نپوشانند."""
    label = str(item.get("short") or item.get("label") or item.get("gw") or "—")
    return label if len(label) <= 16 else label[:15].rstrip() + "…"


def _gw_marker(n, item, W, H, spot=None):
    """نشانگر شماره‌دار گیت‌وی — پین رنگی با برچسب زیر آن.

    موقعیت از x/y ردیف است؛ ردیف چیده‌نشده (x/y ندار) در نقطهٔ spot
    نمایش داده می‌شود — فقط در حالت چیدن.
    """
    placed = item.get("x") is not None and item.get("y") is not None
    px, py = (item["x"], item["y"]) if placed else (spot or (0.5, 0.5))
    cx, cy = px * W, py * H
    color = (_DISCOVERED if item.get("registered") is False
             else _COLOR.get(item.get("kind"), WARN))
    pin = ft.Container(
        width=_PIN, height=_PIN, border_radius=_PIN // 2, bgcolor=color,
        border=ft.Border.all(2.5, WHITE),
        shadow=ft.BoxShadow(blur_radius=7, color="#40000000"),
        alignment=ft.alignment.Alignment(0, 0),
        content=txt(fa_num(n), size=13, font=FONT_B, color=WHITE),
    )
    col = ft.Column(
        [pin, _label_chip(_short_label(item), _CHIP_W, size=10.5)],
        spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    left = min(max(cx - _CHIP_W / 2, 3), W - _CHIP_W - 3)
    holder = ft.Container(content=col, left=left, top=cy - _PIN / 2)
    tip = str(item.get("label") or item.get("gw") or "گیت‌وی")
    if item.get("registered") is False:
        tip += " — کشف‌شده از شبکه، هنوز تعریف نشده"
    if not placed:
        tip += " — هنوز روی نقشه چیده نشده"
    holder.tooltip = tip
    return holder


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


def _worker_dots(W, H, doc=None, rows=None):
    """مچ‌بندهای در دید — زیر گیت‌وی جایگیری‌شده‌ای که دیده‌شان.

    به‌ازای هر مچ‌بند یک نقطه و برچسب «≈ فاصلهٔ تخمینی» می‌آید. فاصله از
    قدرت سیگنال حساب می‌شود و فقط برای تست میدانی برد است — نه موقعیت
    واقعی روی پلان. دیدن کهنه‌تر از _STALE_AGE کم‌رنگ نشان داده می‌شود.
    rows ردیف‌های دفتر گیت‌وی‌های پل است؛ نبودش یعنی همان MAP_GATEWAYS.
    """
    dots = []
    try:
        reg = rows if rows else MAP_GATEWAYS
        pos = {g.get("gw"): g for g in reg
               if g.get("gw") and g.get("x") is not None
               and g.get("y") is not None}
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
    """ردیف فهرست گیت‌وی — هم‌شماره با نشانگر روی نقشه.

    ردیف دفتر پل: وضعیت زنده، جنس (نصب‌شده/پیشنهادی) و چیده‌شدن روی نقشه.
    """
    kind = item.get("kind")
    registered = item.get("registered")
    color = _COLOR.get(kind, WARN)
    if registered is False:
        color = _DISCOVERED
        sub = f"کشف‌شده از شبکه — {item.get('gw') or '—'} — هنوز تعریف نشده"
    elif kind == "installed":
        sub = f"نصب‌شده — {item.get('gw') or '—'}"
        if item.get("testing"):
            sub += " — در حال تست فاصله"
    else:
        sub = "پیشنهادی — در انتظار تست میدانی"
    if item.get("gw") and registered is not False:
        if item.get("online"):
            sub += " — آنلاین"
            if item.get("fw"):
                sub += f" — نسخهٔ {item['fw']}"
        elif item.get("live"):
            sub += " — آفلاین"
    if registered is True and item.get("x") is None and item.get("y") is None:
        sub += " — روی نقشه چیده نشده"
    return ft.Row([
        ft.Container(
            width=22, height=22, border_radius=11, bgcolor=color,
            alignment=ft.alignment.Alignment(0, 0),
            content=txt(fa_num(n), size=11, font=FONT_B, color=WHITE),
        ),
        ft.Column([
            txt(item.get("label") or item.get("gw") or "گیت‌وی",
                size=13, font=FONT_MED, color=INK),
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
        item(_DISCOVERED, "گیت‌وی کشف‌شده — هنوز تعریف نشده"),
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


def _live_rows(d, watch, gw_rows=None):
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
        rows.append(_device_row(OK if on else "#9AA0A6",
                                _gw_name(gw_id, gw_rows), sub))
    unknown_count = sum(1 for r in (gw_rows or [])
                        if r.get("registered") is False)
    if unknown_count:
        rows.append(txt(
            f"{fa_num(unknown_count)} گیت‌وی کشف‌شده هنوز تعریف نشده — "
            "از بخش «گیت‌وی‌ها» تعریفش کن.", size=10.5, font=FONT,
            color=TEXT_MUTED))
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


def _delta_xy(e):
    """جابه‌جایی ماوس/انگشت در رویداد کشیدن — (dx, dy) پیکسلی؛ صفر اگر نبود."""
    d = getattr(e, "local_delta", None) or getattr(e, "global_delta", None)
    if d is None:
        return 0.0, 0.0
    try:
        return float(getattr(d, "x", 0.0) or 0.0), float(getattr(d, "y", 0.0) or 0.0)
    except Exception:
        return 0.0, 0.0


def _moved(x, y, W, H, dx, dy, margin=0.02):
    """موقعیت نسبی تازه پس از جابه‌جایی — با نگه‌داشتن در حاشیهٔ ۲٪."""
    nx = min(1 - margin, max(margin, x + dx / max(W, 1)))
    ny = min(1 - margin, max(margin, y + dy / max(H, 1)))
    return nx, ny


def map_view(app):
    """صفحهٔ «نقشهٔ کارخانه» — گیت‌وی‌ها و مچ‌بندهای زنده روی پلان واقعی.

    گیت‌وی‌ها از دفتر پل می‌آیند (بخش «گیت‌وی‌ها»)؛ اگر پل نبود، همان نقاط
    نمایشی MAP_GATEWAYS با برچسب «غیرقابل ویرایش» نشان داده می‌شود. با دکمهٔ
    «چیدن روی نقشه»، پین‌ها با کشیدن جابه‌جا و موقعیت خودکار در دفتر پل
    ذخیره می‌شود (x/y نسبی ۰..۱).
    """
    W, H = _display_size(app)
    state = app.state
    gen = state.get("map_gen", 0) + 1
    state["map_gen"] = gen
    watch = state.setdefault("map_watch", {"weakest": None, "weakest_at": None,
                                           "samples": 0, "last_seen": None})
    edit = bool(state.get("map_edit"))
    if not edit and os.environ.get("ROSETASH_MAP_EDIT") == "1":
        # قلاب تست بصری — شروع در حالت چیدن (تور اسکرین‌شات)
        state["map_edit"] = True
        edit = True
    src = state.setdefault("map_src", {"rows": None})  # دفتر گیت‌وی‌های پل؛ None = پل نیست

    stack = ft.Stack(width=W, height=H)
    dragging = {"on": False, "x": 0.0, "y": 0.0}

    def _default_spot(n):
        """نقطهٔ پیش‌فرض پین چیده‌نشده — پله‌های کوچک تا روی هم نیفتند."""
        return (0.40 + ((n - 1) % 5) * 0.05, 0.48 + ((n - 1) // 5) * 0.07)

    # ── کشیدن پین در حالت چیدن — موقعیت نسبی، ذخیره در رهاکردن ──
    def _pan_start(item, n):
        def handler(e):
            sx, sy = _default_spot(n)
            dragging.update(
                on=True,
                x=float(item["x"]) if item.get("x") is not None else sx,
                y=float(item["y"]) if item.get("y") is not None else sy)
        return handler

    def _pan_update(holder):
        def handler(e):
            dx, dy = _delta_xy(e)
            dragging["x"], dragging["y"] = _moved(dragging["x"], dragging["y"],
                                                  W, H, dx, dy)
            holder.left = min(max(dragging["x"] * W - _CHIP_W / 2, 3),
                              W - _CHIP_W - 3)
            holder.top = dragging["y"] * H - _PIN / 2
            try:
                holder.update()
            except Exception:
                pass
        return handler

    def _pan_end(item):
        def handler(e):
            dragging["on"] = False
            gw = item.get("gw")
            x, y = round(dragging["x"], 4), round(dragging["y"], 4)
            ok, msg = save_gateway({"gw": gw, "x": x, "y": y})
            if ok:
                item["x"], item["y"] = x, y  # به‌روزرسانی خوش‌بینانهٔ ردیف محلی
                app.snack(f"موقعیت «{item.get('label') or gw}» ذخیره شد")
            else:
                app.snack(f"ذخیرهٔ موقعیت نشد — {msg}")
            _apply(live_status(force=True))
            try:
                app.page.update()
            except Exception:
                pass
        return handler

    def _wrap_drag(marker, item, n):
        """پین را در حالت چیدن قابل کشیدن می‌کند."""
        gd = ft.GestureDetector(content=marker.content, drag_interval=16)
        marker.content = gd
        gd.on_pan_start = _pan_start(item, n)
        gd.on_pan_update = _pan_update(marker)
        gd.on_pan_end = _pan_end(item)
        return marker

    def _draw_plan(doc=None):
        gw_rows = src["rows"]
        listing = (gw_rows if gw_rows else
                   [dict(g, registered=None, online=False) for g in MAP_GATEWAYS])
        editable = bool(edit and gw_rows)
        markers = []
        for i, item in enumerate(listing, start=1):
            placed = item.get("x") is not None and item.get("y") is not None
            if not placed and not editable:
                continue  # چیده‌نشده فقط در حالت چیدن دیده می‌شود
            marker = _gw_marker(i, item, W, H, spot=_default_spot(i))
            if editable and item.get("gw"):
                marker = _wrap_drag(marker, item, i)
            markers.append(marker)
        markers.append(_entry_marker(W, H))
        if not edit:
            # در حالت چیدن فقط پین‌ها — نقطه‌های مچ‌بند شلوغی می‌کنند
            markers.extend(_worker_dots(W, H, doc=doc, rows=gw_rows or None))
        stack.controls = [
            ft.Image(src=MAP_IMAGE, width=W, height=H, fit=ft.BoxFit.FILL),
            *markers,
        ]

    live_col = ft.Column([], spacing=7)
    list_col = ft.Column([], spacing=10)

    def _gateway_rows():
        gw_rows = src["rows"]
        out = []
        if gw_rows is None:
            out.append(txt("پل در دسترس نیست — چیدمان نمایشی و غیرقابل ویرایش.",
                           size=11, font=FONT, color=TEXT_MUTED))
            listing = MAP_GATEWAYS
        elif not gw_rows:
            out.append(txt("هنوز گیت‌ویی تعریف نشده — از بخش «گیت‌وی‌ها» "
                           "یا «گیت‌وی جدید» شروع کن.",
                           size=11, font=FONT, color=TEXT_MUTED))
            listing = MAP_GATEWAYS
        else:
            listing = gw_rows
        out += [_gw_row(i, item) for i, item in enumerate(listing, start=1)]
        return out

    def _hint_text():
        if src["rows"] is None:
            return "برای تعریف و چیدمان، پل باید بالا باشد."
        if not src["rows"]:
            return "گیت‌وی تازه تعریف کن؛ بعد در حالت چیدن روی نقشه بگذارش."
        if edit:
            return "پین را بکش و رها کن — موقعیت خودکار ذخیره می‌شود."
        return "برای جابه‌جایی پین‌ها، «چیدن روی نقشه» را بزن."

    hint = txt(_hint_text(), size=11, font=FONT, color=TEXT_MUTED)

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
        d = d or {}
        if d.get("ok") and d.get("map_gateways") is not None:
            src["rows"] = d.get("map_gateways") or []
        _draw_plan(d)
        live_col.controls = _live_rows(d, watch, src["rows"])
        list_col.controls = _gateway_rows()

    doc = live_status()
    _apply(doc)

    async def _loop():
        while state.get("view") == "map" and state.get("map_gen") == gen:
            try:
                # در حالت چیدن رفرش خودکار خاموش است تا زیر دست کاربر عوض نشود
                if not edit and not dragging["on"]:
                    _apply(live_status())
                    app.page.update()
            except Exception:
                return
            await asyncio.sleep(2)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    def _toggle_edit(e):
        state["map_edit"] = not bool(state.get("map_edit"))
        app.render()

    # نقش کاربر
    my_role = app.state.get("role", "viewer")
    can_edit_map_role = can_edit_map(my_role)
    
    can_edit = bool(src["rows"]) and can_edit_map_role
    edit_btn = ft.Button(
        "پایان چیدن" if edit else "چیدن روی نقشه",
        icon=ft.Icons.DRAG_INDICATOR,
        disabled=not can_edit,
        tooltip=None if can_edit else ("فقط ادمین اصلی می‌تواند چیدن کند" if not can_edit_map_role else "از بخش «گیت‌وی‌ها» گیت‌وی تعریف کن"),
        style=ft.ButtonStyle(
            bgcolor=BRAND_RED if edit else INK, color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        ),
        on_click=_toggle_edit if can_edit else None,
    )

    def _new_gateway(e):
        open_gateway_form(app, on_saved=lambda: app.render())

    def _open_gateways(e):
        app.go("gateways")

    plan_card = card(stack, pad=10)

    panel_controls = [
        # کارت تست زنده اول — هنگام راه‌رفتن بدون اسکرول دیده شود
        card(ft.Column([
            txt("وضعیت زنده و تست فاصله", size=14, font=FONT_B, color=INK),
            live_col,
        ], spacing=7), pad=14),
        card(ft.Column([
            ft.Row([
                txt("گیت‌وی‌ها و چیدمان", size=14, font=FONT_B, color=INK),
                ft.Container(expand=True),
                edit_btn,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            hint,
            list_col,
            ft.Row([
                ft.TextButton("گیت‌وی جدید", icon=ft.Icons.ADD_LOCATION_ALT,
                              on_click=_new_gateway),
                ft.TextButton("بخش گیت‌وی‌ها", icon=ft.Icons.ROUTER,
                              on_click=_open_gateways),
            ], spacing=2),
        ], spacing=8), pad=14),
        _legend_card(),
    ]

    header = section_header(
        "نقشهٔ کارخانه",
        "پلان کارخانه رزتاش — گیت‌وی‌ها از دفتر پل می‌آیند و مچ‌بندهای در دید "
        "هر ۲ ثانیه زیر گیت‌وی مربوطه نقطه می‌گیرند؛ با «چیدن روی نقشه» "
        "پین‌ها را جابه‌جا کن.",
    )

    if is_phone(app):
        # موبایل: نقشهٔ تمام‌عرض بالا، کارت‌ها زیر آن — یک ستون اسکرول‌دار
        return ft.Column([
            header,
            ft.Container(content=plan_card, alignment=ft.alignment.Alignment(0, 0)),
            *panel_controls,
        ], spacing=14, expand=True, scroll=ft.ScrollMode.AUTO)

    panel = ft.Column(panel_controls, width=296, spacing=12,
                      scroll=ft.ScrollMode.AUTO)
    return ft.Column([
        header,
        ft.Row([
            ft.Container(content=plan_card, expand=True,
                         alignment=ft.alignment.Alignment(0, 0)),
            panel,
        ], spacing=14, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
    ], spacing=14, expand=True)
