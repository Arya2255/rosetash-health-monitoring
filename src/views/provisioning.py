# -*- coding: utf-8 -*-
"""بخش «آماده‌سازی گیتوی» — برنامه‌نویسی کامل برد از داخل خود برنامه.

موتور این صفحه ``src/provisioner.py`` است: بستهٔ همراه
``distribution/gateway-provisioner/`` شامل فریمور آماده و ابزارهای
esptool/mklittlefs برای ویندوز و لینوکس. اینجا فقط رابط کاربری سه‌گامی است:

  ۱) برد — اسکن پورت سریال، خواندن مشخصات (چیپ/فلش/MAC) و هشدار برد اشتباه
  ۲) مشخصات — شناسه/نام/منطقه (پیشنهاد از دفتر پل) + وای‌فای و بروکر
     (پیش‌فرض از /api/netinfo همان سیستمی که برنامه رویش اجراست)
  ۳) فلش — با تنظیمات همین حالا (پیشنهادی) یا بدون تنظیمات برای ست‌کردن
     از گوشی در محل نصب (AP راه‌اندازی خود برد)

بعد از فلش موفق، گیت‌وی خودکار در دفتر پل ثبت می‌شود. فلش در نخ جداگانه
اجرا می‌شود تا پنجره قفل نشود؛ یک تیکر هر ثانیه صفحه را تازه می‌کند.
"""

import threading
import time as _time_

import flet as ft

from theme import (BORDER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN,
                   R_CARD, TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt)
from data import live_gateways, netinfo, save_gateway
import provisioner as pv

from components.common import SHADOW, card, section_header
from layout import flow

_BG_OK = "#E6F4EB"
_BG_WARN = "#FCF0DC"
_BG_GRAY = "#F1F2F4"
_BG_ERR = "#FBEAEA"


def _chip(text, fg, bg):
    return ft.Container(
        content=txt(text, size=10.5, font=FONT_MED, color=fg),
        bgcolor=bg, border_radius=999,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )


def _prov_state(app) -> dict:
    """وضعیت پایدار صفحه بین رندرها — زیر app.state[\"prov\"] می‌ماند."""
    st = app.state.setdefault("prov", {})
    if not st.get("inited"):
        st["inited"] = True
        st.update({
            "ports": None, "sel_port": None, "ident": None, "ident_err": "",
            "gw_id": "", "label": "", "zone": "", "ssid": "", "pass": "",
            "host": "", "port": "", "cfg_mode": "config",
            "flashing": False, "percent": None, "log": [], "done": None,
            "reg": None, "_tick": False,
        })
        info = netinfo(include_pass=True) or {}
        st["net"] = info
        st["gw_rows"] = live_gateways() or []
        if info:
            st["ssid"] = info.get("ssid") or ""
            st["pass"] = info.get("pass") or ""
            st["host"] = info.get("mqtt_host") or ""
            st["port"] = str(info.get("mqtt_port") or "")
    return st


def _identity_warnings(ident, rows, gw_id) -> list[str]:
    """هشدارهای هویت برد — مک تکراری برای گیت‌وی دیگر، یا مک ناهماهنگ."""
    warns = []
    if not ident or not ident.get("mac"):
        return warns
    mac = ident["mac"].lower()
    gw_id = (gw_id or "").strip().lower()
    for r in rows or []:
        rmac = str(r.get("mac") or "").lower()
        rgw = str(r.get("gw") or "")
        if not rmac:
            continue
        if rmac == mac and rgw != gw_id:
            warns.append(
                f"این برد قبلاً با شناسهٔ «{rgw}» ثبت شده — اگر عوض شده، "
                "ردیف قدیمی را از دفتر «گیت‌وی‌ها» اصلاح کن.")
        elif rgw == gw_id and rmac != mac:
            warns.append(
                f"مک این برد با مک ثبت‌شدهٔ «{gw_id}» نمی‌خواند "
                f"({rmac}) — برد اشتباه وصل نشده؟")
    return warns


# ─────────────────────── اقدام‌ها (هندلرها) ───────────────────────


def _scan_ports(app, st):
    st["ports"] = pv.list_serial_ports()
    if not st["ports"]:
        app.snack("پورتی پیدا نشد — کابل دیتادار را چک کن (بند «کابل فقط-شارژ»)")
    st["ident"] = None
    st["ident_err"] = ""


def _read_ident(app, st):
    port = st.get("sel_port") or ""
    if not port:
        app.snack("اول یک پورت سریال از فهرست انتخاب کن")
        return
    tools = pv.find_tools()
    if not tools.get("esptool"):
        st["ident_err"] = "ابزار esptool پیدا نشد — بستهٔ همراه را بساز"
        return
    st["ident_err"] = ""
    st["ident"] = None

    def worker():
        ok, doc = pv.read_chip_info(port, tools["esptool"])
        if ok:
            st["ident"] = doc
            st["ident_err"] = ""
        else:
            st["ident"] = None
            st["ident_err"] = doc.get("error") or "برد پاسخ نداد"

    threading.Thread(target=worker, daemon=True).start()
    app.render()


def _start_flash(app, st):
    if st.get("flashing"):
        return
    port = st.get("sel_port") or ""
    if not port:
        app.snack("اول پورت سریال را انتخاب کن")
        return
    cfg = None
    if st.get("cfg_mode") != "blank":
        gw_ok, gw_msg = pv.validate_gw_id(st.get("gw_id") or "")
        if not gw_ok:
            app.snack(gw_msg)
            return
        if not (st.get("ssid") or "").strip():
            app.snack("نام وای‌فای خالی است — بخش «وای‌فای و بروکر» را پر کن")
            return
        if not (st.get("host") or "").strip():
            app.snack("آدرس بروکر خالی است — بخش «وای‌فای و بروکر» را پر کن")
            return
        cfg = pv.build_config(
            st.get("gw_id") or "", st.get("zone") or "", st.get("ssid") or "",
            st.get("pass") or "", st.get("host") or "",
            st.get("port") or 1883, 600)
    st["flashing"] = True
    st["percent"] = None
    st["log"] = []
    st["done"] = None
    st["reg"] = None

    def note(line):
        pct = pv.progress_percent(line)
        if pct is not None:
            st["percent"] = pct
            return
        st["log"].append(line)
        if len(st["log"]) > 160:
            del st["log"][0]

    def worker():
        ok, info = pv.flash_gateway(port, cfg=cfg, progress=note)
        st["log"] = info.get("log") or st["log"]
        st["done"] = {"ok": ok, "error": info.get("error") or "",
                      "verified": info.get("verified")}
        if ok:
            gid = (st.get("gw_id") or "").strip().lower()
            if cfg is None:
                st["reg"] = (False, "بدون تنظیمات فلش شد — ثبت در دفتر "
                                    "وقتی برد از گوشی ست شد انجام می‌شود")
            else:
                ident = st.get("ident") or {}
                st["reg"] = save_gateway({
                    "gw": gid, "label": st.get("label") or gid,
                    "zone": st.get("zone") or "", "kind": "installed",
                    "mac": ident.get("mac") or "",
                })
        st["flashing"] = False
        _time_.sleep(0.2)

    threading.Thread(target=worker, daemon=True).start()
    app.render()


# ─────────────────────── قطعه‌های رابط ───────────────────────


def _bundle_card(st) -> ft.Control:
    bundle = pv.bundle_status()
    if not bundle.get("present"):
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.INVENTORY_2, size=18, color=WARN),
                txt("بستهٔ همراه برنامه ساخته نشده — برای ساخت: "
                    "tools/build_provisioner_bundle.py", size=12.5,
                    font=FONT_MED, color=WARN, expand=True),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=_BG_WARN, border_radius=R_CARD,
            padding=ft.Padding.symmetric(horizontal=14, vertical=10))
    tools = bundle.get("tools") or {}
    src_fa = {"bundled": "همراه برنامه", "arduino": "نصب آردوینو",
              "path": "PATH", "env": "تنظیم دستی", "": "پیدا نشد"}
    chips = [
        _chip(f"فریمور {bundle.get('fw_version') or '?'}", OK, _BG_OK),
        _chip(f"{fa_num(bundle.get('files') or 0)} فایل", INK, _BG_GRAY),
        _chip(f"esptool: {src_fa.get(tools.get('esptool'), '?')}",
              OK if tools.get("esptool") else OFFLINE,
              _BG_OK if tools.get("esptool") else _BG_ERR),
        _chip(f"mklittlefs: {src_fa.get(tools.get('mklittlefs'), '?')}",
              OK if tools.get("mklittlefs") else OFFLINE,
              _BG_OK if tools.get("mklittlefs") else _BG_ERR),
    ]
    return card(ft.Row([
        ft.Container(width=34, height=34, border_radius=10, bgcolor=_BG_GRAY,
                     alignment=ft.alignment.Alignment(0, 0),
                     content=ft.Icon(ft.Icons.INVENTORY_2, size=18, color=OK)),
        ft.Column([
            txt("بستهٔ همراه برنامه", size=13.5, font=FONT_MED, color=INK),
            ft.Row(chips, spacing=6, wrap=True),
        ], spacing=4, expand=True),
    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=12)


def _net_card(app, st) -> ft.Control:
    info = st.get("net") or {}

    def refresh(e):
        st["net"] = netinfo(include_pass=True) or {}
        st["gw_rows"] = live_gateways() or []
        app.render()

    if info:
        sub = (f"وای‌فای: {info.get('ssid') or '—'} — بروکر: "
               f"{info.get('mqtt_host') or '—'}:{info.get('mqtt_port') or '—'}")
        icon, fg, bg = ft.Icons.WIFI_TETHERING, OK, _BG_OK
    else:
        sub = ("پل بالا نیست — مقادیر وای‌فای/بروکر را دستی وارد کن "
               "(پل: python3 backend/bridge.py)")
        icon, fg, bg = ft.Icons.WIFI_TETHERING, WARN, _BG_WARN
    return ft.Container(
        content=ft.Row([
            ft.Icon(icon, size=18, color=fg),
            txt(sub, size=12, font=FONT, color=fg, expand=True),
            ft.IconButton(ft.Icons.REFRESH, tooltip="تازه‌سازی از پل",
                          icon_size=18, on_click=refresh),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=bg, border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=8))


def _step1_card(app, st) -> ft.Control:
    """گام ۱ — پیدا کردن برد و تأیید هویت."""
    blocks = [
        txt("۱) برد را با کابل دیتادار به همین سیستم وصل کن", size=14,
            font=FONT_B, color=INK),
        txt("پیش از هر چیز «اسکن پورت‌ها»؛ بعد پورت برد را انتخاب و "
            "«خواندن مشخصات برد» را بزن. هر خواندن، یک‌بار برد را کوتاه "
            "ری‌استارت می‌کند — طبیعی است.", size=11.5, font=FONT,
            color=TEXT_MUTED),
    ]

    ports = st.get("ports")
    if ports is None:
        blocks.append(ft.Button(
            "اسکن پورت‌های سریال", icon=ft.Icons.USB,
            style=ft.ButtonStyle(
                bgcolor=WHITE, color=INK,
                shape=ft.RoundedRectangleBorder(radius=R_BTN),
                side=ft.BorderSide(1, BORDER)),
            on_click=lambda e: (_scan_ports(app, st), app.render())))
    elif not ports:
        blocks.append(ft.Container(
            content=txt("پورتی پیدا نشد — کابل دیتادار را عوض کن؛ کابل "
                        "فقط-شارژ هیچ پورتی نمی‌سازد (پایین را ببین)",
                        size=12, font=FONT, color=WARN),
            bgcolor=_BG_WARN, border_radius=R_CARD,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8)))
        blocks.append(ft.TextButton("اسکن دوباره", icon=ft.Icons.REFRESH,
                                    on_click=lambda e: (_scan_ports(app, st),
                                                        app.render())))
    else:
        rows = []
        for p in ports:
            sel = st.get("sel_port") == p["port"]
            rows.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.USB, size=16,
                            color=INK if sel else TEXT_MUTED),
                    txt(p["port"], size=12.5, font=FONT_MED, color=INK),
                    txt(p.get("label") or "", size=11, font=FONT,
                        color=TEXT_MUTED, expand=True),
                    _chip("انتخاب‌شده", OK, _BG_OK) if sel else
                    txt("انتخاب", size=11, font=FONT_MED, color=TEXT_MUTED),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=_BG_OK if sel else WHITE,
                border=ft.Border.all(1, OK if sel else BORDER),
                border_radius=R_BTN, padding=ft.Padding.symmetric(
                    horizontal=12, vertical=8),
                on_click=lambda e, port=p["port"]: (
                    st.__setitem__("sel_port", port), app.render()),
                ink=True))
        blocks.append(ft.Column(rows, spacing=6))
        blocks.append(ft.TextButton("اسکن دوباره", icon=ft.Icons.REFRESH,
                                    on_click=lambda e: (_scan_ports(app, st),
                                                        app.render())))

    # نتیجهٔ خواندن مشخصات + هشدارها
    if st.get("ident"):
        d = st["ident"]
        blocks.append(ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=16, color=OK),
                    txt("مشخصات برد خوانده شد", size=12.5, font=FONT_MED,
                        color=OK),
                ], spacing=6),
                ft.Row([
                    _chip(d.get("chip") or "ESP32", INK, _BG_GRAY),
                    _chip(f"فلش {d.get('flash') or '?'}", INK, _BG_GRAY),
                    _chip(d.get("mac") or "—", INK, _BG_GRAY),
                ], spacing=6, wrap=True),
            ], spacing=6),
            bgcolor=_BG_OK, border_radius=R_CARD,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10)))
        for w in _identity_warnings(d, st.get("gw_rows"), st.get("gw_id")):
            blocks.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.WARNING_AMBER, size=16, color=WARN),
                    txt(w, size=11.5, font=FONT, color=WARN, expand=True),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=_BG_WARN, border_radius=R_CARD,
                padding=ft.Padding.symmetric(horizontal=12, vertical=8)))
    elif st.get("ident_err"):
        blocks.append(ft.Container(
            content=txt(st["ident_err"], size=12, font=FONT, color=OFFLINE),
            bgcolor=_BG_ERR, border_radius=R_CARD,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8)))

    return card(ft.Column(blocks, spacing=10), pad=14)


def _field(label, key, st, **kw):
    return ft.TextField(
        label=label, value=st.get(key) or "",
        on_change=lambda e, k=key: st.__setitem__(k, e.control.value),
        **kw)


def _step2_card(app, st) -> ft.Control:
    """گام ۲ — شناسه/منطقه + وای‌فای و آدرس بروکر."""
    rows = [r for r in (st.get("gw_rows") or [])
            if r.get("registered") is not False]

    def pick(gw_id, r):
        st["gw_id"] = gw_id
        st["label"] = r.get("label") or gw_id
        st["zone"] = r.get("zone") or ""
        app.render()

    blocks = [
        txt("۲) شناسه و مشخصات گیت‌وی", size=14, font=FONT_B, color=INK),
        txt("شناسه همان است که در برد نوشته می‌شود و در دفتر پل ثبت "
            "می‌گردد. برای گیت‌وی موجود، از تراشه‌های زیر انتخاب کن تا "
            "نام و منطقه از دفتر بیاید.", size=11.5, font=FONT,
            color=TEXT_MUTED),
    ]
    if rows:
        chips = []
        for r in rows:
            r_gw = str(r.get("gw") or "")
            chips.append(ft.Container(
                content=txt(r.get("label") or r_gw, size=11, font=FONT_MED,
                            color=WHITE if st.get("gw_id") == r_gw else INK),
                bgcolor=INK if st.get("gw_id") == r_gw else _BG_GRAY,
                border_radius=999,
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                on_click=lambda e, g=r_gw, rr=r: pick(g, rr), ink=True))
        blocks.append(ft.Row(chips, spacing=6, wrap=True))
    # نکته: Row(wrap=True) فرزند expand=True را نمیپذیرد (خطای WrapParentData
    # سمت Flutter)؛ ردیفهای فیلد با کمک flow ساخته میشوند — دسکتاپ Row،
    # موبایل ستون تمامعرض (مثل صفحهٔ «لاگ برنامه»).
    blocks += [
        flow(app, [
            _field("شناسهٔ گیت‌وی (gw-…)", "gw_id", st, expand=1),
            _field("نام نمایشی", "label", st, expand=1),
            _field("منطقه / محل نصب", "zone", st, expand=1),
        ], spacing=8),
        flow(app, [
            _field("نام وای‌فای (SSID)", "ssid", st, expand=2),
            _field("رمز وای‌فای", "pass", st, expand=2, password=True),
            _field("آدرس بروکر MQTT", "host", st, expand=2),
            _field("پورت", "port", st, expand=1),
        ], spacing=8),
    ]
    return card(ft.Column(blocks, spacing=10), pad=14)


def _step3_card(app, st) -> ft.Control:
    """گام ۳ — حالت فلش + دکمه + پیشرفت زنده + نتیجه."""
    def mode(e):
        st["cfg_mode"] = "blank" if e.control.value else "config"
        app.render()

    blank = st.get("cfg_mode") == "blank"
    blocks = [
        txt("۳) فلش روی برد", size=14, font=FONT_B, color=INK),
        ft.Checkbox(
            label=("بدون تنظیمات فلش کن — برد بعد از نصب، خودش AP باز می‌کند "
                   "و از گوشیِ نصب‌کار ست می‌شود"),
            value=blank, on_change=mode),
    ]
    if not blank:
        blocks.append(txt("با کانفیگ همین حالا: وای‌فای و بروکر از گام ۲ در "
                          "تصویر تنظیمات برد نوشته می‌شود؛ بعد از فلش، برد "
                          "خودش به شبکه وصل می‌شود.", size=11.5, font=FONT,
                          color=TEXT_MUTED))

    if st.get("flashing"):
        pct = st.get("percent")
        log_tail = (st.get("log") or [])[-9:]
        blocks += [
            ft.ProgressBar(value=(pct or 0) / 100.0, color=INK,
                           bgcolor=_BG_GRAY),
            txt(f"در حال نوشتن… {fa_num(pct)}٪" if pct is not None
                else "در حال اتصال به برد…", size=12, font=FONT_MED,
                color=INK),
            ft.Container(
                content=ft.Column([
                    txt(l, size=10.5, font=FONT, color=TEXT_MUTED)
                    for l in log_tail],
                    spacing=1, scroll=ft.ScrollMode.AUTO),
                bgcolor="#0F1115", border_radius=R_BTN,
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                height=140),
        ]
    else:
        blocks.append(ft.Button(
            "شروع فلش کامل", icon=ft.Icons.DOWNLOAD,
            disabled=st.get("flashing") or not st.get("sel_port"),
            tooltip=None if st.get("sel_port") else "اول پورت را از گام ۱ انتخاب کن",
            style=ft.ButtonStyle(
                bgcolor=INK, color=WHITE,
                shape=ft.RoundedRectangleBorder(radius=R_BTN),
                padding=ft.Padding.symmetric(horizontal=16, vertical=10)),
            on_click=lambda e: _start_flash(app, st)))

    done = st.get("done")
    if done:
        if done.get("ok"):
            reg = st.get("reg")
            lines = [ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, size=18, color=OK),
                txt("فلش کامل شد" + (" — هش همهٔ فایل‌ها تأیید شد"
                                     if done.get("verified") else ""),
                    size=13, font=FONT_B, color=OK),
            ], spacing=6)]
            if reg is not None:
                ok_reg, msg = reg
                lines.append(txt(
                    "در دفتر گیت‌وی‌ها ثبت شد ✓" if ok_reg
                    else f"ثبت در دفتر نشد: {msg}", size=11.5, font=FONT,
                    color=OK if ok_reg else WARN))
            blocks.append(ft.Container(
                content=ft.Column(lines, spacing=4),
                bgcolor=_BG_OK, border_radius=R_CARD,
                padding=ft.Padding.symmetric(horizontal=12, vertical=10)))
        else:
            blocks.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(ft.Icons.ERROR_OUTLINE, size=18,
                                color=OFFLINE),
                        txt("فلش ناموفق بود", size=13, font=FONT_B,
                            color=OFFLINE),
                    ], spacing=6),
                    txt(done.get("error") or "—", size=11.5, font=FONT,
                        color=OFFLINE),
                    txt("پیش از تلاش دوباره، لاگ پایین را ببین؛ اغلب با "
                        "دکمهٔ BOOT و یک پورت دیگر حل می‌شود.", size=11,
                        font=FONT, color=TEXT_MUTED),
                ], spacing=4),
                bgcolor=_BG_ERR, border_radius=R_CARD,
                padding=ft.Padding.symmetric(horizontal=12, vertical=10)))
            log_tail = (st.get("log") or [])[-10:]
            if log_tail:
                blocks.append(ft.Container(
                    content=ft.Column([
                        txt(l, size=10.5, font=FONT, color=TEXT_MUTED)
                        for l in log_tail], spacing=1),
                    bgcolor="#0F1115", border_radius=R_BTN,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=8)))
    return card(ft.Column(blocks, spacing=10), pad=14)


def _help_card() -> ft.Control:
    return card(ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.HELP_OUTLINE, size=16, color=INK),
            txt("راهنمای سریع — کابل، درایور، حرف‌های رایج", size=13.5,
                font=FONT_B, color=INK),
        ], spacing=6),
        txt("• کابل فقط-شارژ هیچ پورتی نمی‌سازد — اول کابل دیتادار را عوض "
            "کن؛ اگر در ویندوز پورت آمد ولی باز نشد، درایور CP210x لازم است",
            size=11.5, font=FONT, color=TEXT_MAIN),
        txt("• لینوکس: کاربر باید عضو dialout باشد؛ در سشن موجود "
            "sg dialout -c \"…\" کارساز است", size=11.5, font=FONT,
            color=TEXT_MAIN),
        txt("• اگر «خواندن مشخصات» جواب نداد: دکمهٔ BOOT را نگه دار، یک‌بار "
            "EN را بزن، رها کن و دوباره بخوان", size=11.5, font=FONT,
            color=TEXT_MAIN),
        txt("• ویندوز: اگر پورت پیدا نشد درایور CP210x را نصب کن؛ اگر فلش "
            "وسط کار قطع شد، کابل و پورت USB را عوض کن", size=11.5, font=FONT,
            color=TEXT_MAIN),
        txt("• بعد از نصب دیگر کابل لازم نیست: بردِ بدون تنظیمات، شبکهٔ "
            "RoztashGw-… (باز) را باز می‌کند و از مرورگر گوشی روی آدرس "
            "http://192.168.4.1 ست می‌شود", size=11.5, font=FONT,
            color=TEXT_MAIN),
    ], spacing=6), pad=14)


def _ticker(app, st):
    """تازه‌سازی لحظه‌ای صفحه تا پایان فلش — هر ثانیه یک رندر."""
    if st.get("_tick") or not hasattr(app.page, "run_task"):
        return
    st["_tick"] = True

    async def loop():
        import asyncio
        while st.get("flashing"):
            await asyncio.sleep(1.0)
            app.render()
        st["_tick"] = False

    app.page.run_task(loop)


def provisioning_view(app):
    """صفحهٔ «آماده‌سازی گیتوی» — سه گام فلش کامل برد."""
    st = _prov_state(app)
    _ticker(app, st)

    header = section_header(
        "آماده‌سازی گیتوی",
        "برد نو را با کابل به همین سیستم وصل کن، هویت و مشخصات را تأیید "
        "کن و فلش کامل (فریمور + تنظیمات) را همان‌جا بزن — بدون arduino-cli "
        "و بدون نصب ابزار اضافه. فلش با تنظیمات همین حالا یا بدون تنظیمات "
        "برای ست‌کردن از گوشی در محل نصب.")

    return ft.Column([
        header,
        _bundle_card(st),
        _net_card(app, st),
        _step1_card(app, st),
        _step2_card(app, st),
        _step3_card(app, st),
        _help_card(),
    ], spacing=14, scroll=ft.ScrollMode.AUTO)
