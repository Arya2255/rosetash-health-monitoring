# -*- coding: utf-8 -*-
"""پایش زندهٔ گیت‌وی — نمای لحظه‌ای از دادهٔ واقعی پل محلی.

برخلاف بقیهٔ صفحه‌ها، این نما دادهٔ mock نمی‌آید؛ از پل زندهٔ بک‌اند
(backend/bridge.py → MQTT → SQLite → HTTP) تغذیه می‌شود. طبق قاعدهٔ پروژه
همهٔ داده فقط از لایهٔ data می‌آید، نه مستقیم از سخت‌افزار.

هر ثانیه به‌روزرسانی می‌شود و تاریخچهٔ سیگنال مچ‌بند را همین‌جا می‌سازد.
"""

import asyncio
import time
from datetime import datetime

import flet as ft

from theme import (
    FONT, FONT_B, FONT_MED, FONT_SB, INK, OFFLINE, OK, TEXT_MAIN,
    TEXT_MUTED, WARN, fa_clock, fa_num, txt,
)
from data import live_status
from components.common import card, section_header

CHART_LEN = 60          # ستون‌های نمودار
FEED_LEN = 6            # ردیف‌های خوراک رویداد
NOISE_KINDS = {"presence", "status", "health", "measure_fail"}

_FAIL_FA = {
    "connect": "اتصال برقرار نشد",
    "timeout": "پاسخی از مچ‌بند نیامد",
    "subscribe": "اشتراک نوتیفای ناموفق",
    "write": "ارسال فرمان ناموفق",
}


def _rssi_color(rssi):
    if rssi is None:
        return OFFLINE
    if rssi >= -75:
        return OK
    return WARN


def _rel(seconds):
    if seconds is None:
        return "—"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{fa_num(seconds)} ثانیه پیش"
    if seconds < 3600:
        return f"{fa_num(seconds // 60)} دقیقه پیش"
    return f"{fa_num(seconds // 3600)} ساعت پیش"


def _dur(seconds):
    seconds = int(max(0, seconds or 0))
    if seconds < 60:
        return f"{fa_num(seconds)} ثانیه"
    if seconds < 3600:
        return f"{fa_num(seconds // 60)} دقیقه"
    return f"{fa_num(seconds // 3600)} ساعت و {fa_num((seconds % 3600) // 60)} دقیقه"


def _epoch(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except Exception:
        return 0.0


def _kpi(label, icon, color, icon_bg, value_ctrl, sub_ctrl):
    """کارت شاخص — هم‌خانوادهٔ کارت‌های داشبورد ولی با مقادیر زنده."""
    return card(ft.Column([
        ft.Row([
            ft.Container(content=ft.Icon(icon, size=18, color=color),
                         bgcolor=icon_bg, border_radius=10,
                         padding=ft.Padding.all(8)),
            ft.Container(expand=True),
            txt(label, size=13, font=FONT_MED, color=TEXT_MUTED),
        ]),
        value_ctrl,
        sub_ctrl,
    ], spacing=8), pad=16)


def _feed_row(at, kind, desc):
    color = {"ok": OK, "warn": WARN, "off": OFFLINE}[kind]
    stamp = fa_clock(datetime.fromtimestamp(at)) if at else "—"
    return ft.Row([
        ft.Container(width=8, height=8, border_radius=4, bgcolor=color),
        ft.Container(content=txt(desc, size=13, font=FONT, color=TEXT_MAIN),
                     expand=True),
        txt(stamp, size=11, font=FONT, color=TEXT_MUTED),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def live_view(app):
    state = app.state
    gen = state.get("live_gen", 0) + 1
    state["live_gen"] = gen

    doc = live_status()

    # ── چیپ اتصال ──
    conn_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor=OFFLINE)
    conn_txt = txt("در حال بررسی پل محلی…", size=12, font=FONT_MED,
                   color=TEXT_MUTED)
    conn_chip = ft.Container(
        content=ft.Row([conn_dot, conn_txt], spacing=6, tight=True),
        bgcolor="#F1F2F4", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
    )

    # ── کارت ۱: مچ‌بند ──
    band_value = txt("—", size=30, font=FONT, color=OFFLINE)
    band_sub = txt("در انتظار داده…", size=12, font=FONT, color=TEXT_MUTED)
    band_card = _kpi(
        "مچ‌بند — سیگنال", ft.Icons.WATCH, INK, "#E9EBEE",
        ft.Row([band_value, txt("dBm", size=12, font=FONT, color=TEXT_MUTED)],
               spacing=6, vertical_alignment=ft.CrossAxisAlignment.END),
        band_sub)

    # ── کارت ۲: ضربان ──
    hr_value = txt("—", size=30, font=FONT, color=INK)
    hr_sub = txt("در انتظار نخستین اندازه‌گیری…", size=12,
                 font=FONT, color=TEXT_MUTED)
    hr_card = _kpi(
        "آخرین ضربان", ft.Icons.MONITOR_HEART, INK, "#E9EBEE",
        ft.Row([hr_value, txt("ضربه/دقیقه", size=12, font=FONT, color=TEXT_MUTED)],
               spacing=6, vertical_alignment=ft.CrossAxisAlignment.END),
        hr_sub)

    # ── کارت ۳: گیت‌وی ──
    gw_value = txt("—", size=26, font=FONT, color=INK)
    gw_sub = txt("در انتظار وضعیت…", size=12, font=FONT, color=TEXT_MUTED)
    gw_card = _kpi("گیت‌وی", ft.Icons.ROUTER, INK, "#E9EBEE", gw_value, gw_sub)

    # ── کارت ۴: پنجرهٔ سلامت ──
    win_value = txt("—", size=26, font=FONT, color=INK)
    win_sub = txt("در انتظار نخستین اندازه‌گیری…", size=12,
                  font=FONT, color=TEXT_MUTED)
    win_card = _kpi("پنجرهٔ سلامت", ft.Icons.FACT_CHECK, INK, "#E9EBEE",
                    win_value, win_sub)

    kpi_row = ft.Row([
        ft.Container(expand=True, content=band_card),
        ft.Container(expand=True, content=hr_card),
        ft.Container(expand=True, content=gw_card),
        ft.Container(expand=True, content=win_card),
    ], spacing=14)

    # ── نمودار سیگنال ──
    bars_row = ft.Row([], spacing=2, height=64,
                      vertical_alignment=ft.CrossAxisAlignment.END)
    chart_card = card(ft.Column([
        ft.Row([
            txt("نمودار سیگنال مچ‌بند", size=15, font=FONT_SB, color=INK),
            ft.Container(expand=True),
            txt("از لحظهٔ باز شدن صفحه پر می‌شود — هر ستون یک بستهٔ حضور",
                size=11, font=FONT, color=TEXT_MUTED),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(content=bars_row, padding=ft.Padding.only(top=6)),
    ], spacing=8))

    # ── خوراک رویدادها ──
    feed_col = ft.Column([], spacing=8)
    feed_card = card(ft.Column([
        txt("آخرین رویدادها", size=15, font=FONT_SB, color=INK),
        feed_col,
    ], spacing=10))

    def _track(d):
        """تاریخچهٔ سیگنال — هر بستهٔ تازه یک ستون."""
        hist = state.setdefault("live_hist", [])
        bands = (d or {}).get("bands") or []
        now = time.time()
        if bands:
            seen_at = bands[0].get("seen_at")
            if seen_at != state.get("live_hist_seen"):
                hist.append((now, bands[0].get("rssi")))
                state["live_hist_seen"] = seen_at
        elif hist and hist[-1][1] is not None:
            hist.append((now, None))
            state["live_hist_seen"] = None
        if len(hist) > CHART_LEN * 2:
            del hist[:len(hist) - CHART_LEN * 2]

    def _apply(d):
        # چیپ اتصال
        if d and d.get("ok"):
            conn_dot.bgcolor = OK
            conn_txt.value = "دریافت زنده از پل محلی"
            conn_txt.color = OK
            conn_chip.bgcolor = "#E6F4EB"
        else:
            conn_dot.bgcolor = OFFLINE
            conn_txt.value = "پل محلی در دسترس نیست"
            conn_txt.color = OFFLINE
            conn_chip.bgcolor = "#ECECEC"

        # مچ‌بند
        bands = (d or {}).get("bands") or []
        if bands:
            b = bands[0]
            rssi = b.get("rssi")
            band_value.value = fa_num(round(rssi)) if rssi is not None else "—"
            band_value.color = _rssi_color(rssi)
            band_sub.value = f"دیده می‌شود — {_rel(b.get('age_s'))}"
            band_sub.color = OK
        else:
            band_value.value = "—"
            band_value.color = OFFLINE
            band_sub.value = "خارج از دید"
            band_sub.color = OFFLINE

        # ضربان و پنجرهٔ سلامت — از آخرین اندازه‌گیری
        health = (d or {}).get("health") or []
        h = health[0] if health else None
        if h and h.get("state") == "done" and h.get("n"):
            hr_value.value = fa_num(round(h.get("avg") or 0))
            hr_value.color = INK
            last = (h.get("bpm") or [0])[-1]
            hr_sub.value = (f"{fa_num(h.get('n', 0))} نمونه — "
                            f"آخرین {fa_num(last)} — {_rel(h.get('age_s'))}")
            win_value.value = "موفق"
            win_value.color = OK
            win_sub.value = (f"میانگین {fa_num(h.get('avg', 0))} — "
                             f"{fa_num(h.get('n', 0))} نمونه")
        elif h:
            hr_value.value = "—"
            hr_value.color = OFFLINE
            hr_sub.value = f"اندازه‌گیری ناموفق — {_rel(h.get('age_s'))}"
            win_value.value = "ناموفق"
            win_value.color = WARN
            win_sub.value = _FAIL_FA.get(h.get("fail", ""), "خطا")
        else:
            hr_value.value = "—"
            hr_value.color = OFFLINE
            win_value.value = "—"
            win_value.color = INK

        # گیت‌وی
        gws = (d or {}).get("gateways") or []
        if gws:
            g = gws[0]
            gw_value.value = str(g.get("fw", "—"))
            gw_value.color = INK if g.get("online") else OFFLINE
            wifi = g.get("rssi")
            wifi_txt = fa_num(round(wifi)) if wifi is not None else "—"
            gw_sub.value = (f"آپ‌تایم {_dur(g.get('uptime_s'))} — "
                            f"{fa_num(round(g.get('adv_seen') or 0))} بستهٔ دریافتی — "
                            f"وای‌فای {wifi_txt}")
        else:
            gw_value.value = "—"
            gw_value.color = OFFLINE

        # نمودار سیگنال
        bars = []
        for _, rssi in state.get("live_hist", [])[-CHART_LEN:]:
            if rssi is None:
                bars.append(ft.Container(width=5, height=5, border_radius=2,
                                         bgcolor="#D8DADD"))
            else:
                hpx = int(max(6, min(60, (rssi + 100) * 1.15)))
                bars.append(ft.Container(width=5, height=hpx, border_radius=2,
                                         bgcolor=_rssi_color(rssi)))
        bars_row.controls = bars

        # خوراک رویدادها
        entries = []
        for hh in ((d or {}).get("health") or []):
            ts = _epoch(hh.get("ts"))
            if hh.get("state") == "done" and hh.get("n"):
                entries.append((ts, "ok", "اندازه‌گیری موفق — میانگین "
                                f"{fa_num(hh.get('avg', 0))} ضربه"))
            else:
                entries.append((ts, "warn", "اندازه‌گیری ناموفق — "
                                + _FAIL_FA.get(hh.get("fail", ""), "خطا")))
        for e in ((d or {}).get("events") or []):
            kind = e.get("kind")
            if kind in NOISE_KINDS:
                continue
            entries.append((_epoch(e.get("ts")), "off", str(kind)))
        entries.sort(key=lambda x: x[0], reverse=True)
        if entries:
            feed_col.controls = [_feed_row(at, kind, desc)
                                 for at, kind, desc in entries[:FEED_LEN]]
        else:
            feed_col.controls = [txt("هنوز رویدادی ثبت نشده — پل زنده در حال جمع‌آوری است…",
                                     size=12, font=FONT, color=TEXT_MUTED)]

    _track(doc)
    _apply(doc)

    async def _loop():
        while state.get("view") == "live" and state.get("live_gen") == gen:
            try:
                d = live_status()
                _track(d)
                _apply(d)
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(1)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    return ft.Column([
        section_header("پایش زندهٔ گیت‌وی",
                       "دادهٔ واقعی از پل محلی — به‌روزرسانی هر ثانیه",
                       trailing=conn_chip),
        kpi_row,
        chart_card,
        feed_card,
    ], spacing=14, expand=True, scroll=ft.ScrollMode.AUTO)
