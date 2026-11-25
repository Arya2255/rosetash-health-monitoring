# -*- coding: utf-8 -*-
"""آماده‌سازی گیتوی از داخل برنامه.

بستهٔ همراه شامل فریمور و esptool/mklittlefs است؛ فرم تنظیمات فقط هویت، منطقه
و نشانی بروکر را می‌گیرد. گیتوی ESP32-S3/W5500 IP را از DHCP دریافت می‌کند؛
SSID و رمز Wi-Fi در این معماری لازم نیست.
"""

import threading
import time as _time_

import flet as ft

from theme import (BORDER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN,
                   R_CARD, TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt)
from data import live_gateways, save_gateway
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
            "gw_id": "", "label": "", "zone": "",
            "host": "192.168.50.1", "port": "1884",
            "flashing": False, "percent": None, "log": [], "done": None,
            "reg": None, "_tick": False,
        })
    if not st.get("flashing"):
        rows = live_gateways()
        st["registry_available"] = rows is not None
        st["gw_rows"] = _registered_gateways(rows)
    return st


def _registered_gateways(rows):
    unique = {}
    for row in rows or []:
        if (isinstance(row, dict) and row.get("registered") is True
                and isinstance(row.get("gw"), str) and pv.validate_gw_id(row["gw"])[0]):
            unique.setdefault(row["gw"], dict(row))
    return list(unique.values())


def _selected_gateway(st):
    return next((r for r in _registered_gateways(st.get("gw_rows"))
                 if r["gw"] == st.get("gw_id")), None)


def _identity_compatible(ident) -> bool:
    return bool(ident and ident.get("mac")
                and ident.get("chip_id") == pv.TARGET_CHIP
                and ident.get("flash_bytes") == 16 * 1024 * 1024)


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
            app.snack("مشخصات برد تأیید شد")
        else:
            st["ident"] = None
            st["ident_err"] = doc.get("error") or "برد پاسخ نداد"
            app.snack(st["ident_err"])

    threading.Thread(target=worker, daemon=True).start()
    app.render()


def _start_flash(app, st):
    if st.get("flashing"):
        return
    port = st.get("sel_port") or ""
    if not port:
        app.snack("اول پورت سریال را انتخاب کن")
        return
    ident = st.get("ident") or {}
    if not _identity_compatible(ident):
        app.snack("ابتدا ESP32-S3 شانزده‌مگابایتی را شناسایی و تأیید کن")
        return
    rows = live_gateways(force=True)
    st["gw_rows"] = _registered_gateways(rows)
    if rows is None:
        app.snack("دفتر گیت‌وی‌ها در دسترس نیست؛ اتصال پل را بررسی کنید")
        return
    if _selected_gateway(st) is None:
        app.snack("ابتدا یک گیت‌وی تعریف‌شده را از فهرست انتخاب کن")
        return
    gw_ok, gw_msg = pv.validate_gw_id(st.get("gw_id") or "")
    if not gw_ok:
        app.snack(gw_msg)
        return
    if not (st.get("host") or "").strip():
        app.snack("آدرس بروکر خالی است")
        return
    if len(st["gw_id"]) > 23:
        app.snack("شناسهٔ ثبت‌شده باید حداکثر ۲۳ نویسه باشد؛ آن را در دفتر گیت‌وی‌ها اصلاح کنید")
        return
    try:
        mqtt_port = int(st.get("port") or 1884)
        if not 1 <= mqtt_port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        app.snack("پورت بروکر باید عددی بین ۱ تا ۶۵۵۳۵ باشد")
        return
    cfg = pv.build_config(st["gw_id"], st.get("zone") or "",
                          st.get("host") or "", mqtt_port,
                          int(st.get("health_interval_s") or 600))
    ident = dict(ident)
    registration = {"gw": st["gw_id"], "label": st.get("label") or st["gw_id"],
                    "zone": st.get("zone") or "", "kind": "installed", "mac": ident["mac"]}
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
        ok, info = pv.flash_gateway(
            port, cfg=cfg, expected_chip=ident["chip_id"],
            expected_flash_bytes=ident["flash_bytes"],
            expected_mac=ident["mac"], progress=note)
        st["log"] = info.get("log") or st["log"]
        st["done"] = {"ok": ok, "error": info.get("error") or "",
                      "verified": info.get("verified")}
        if ok:
            st["reg"] = save_gateway(registration)
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
                ft.Icon(ft.Icons.WARNING_AMBER, size=18, color=WARN),
                txt(bundle.get("error") or "بستهٔ فلش گیتوی آماده نیست — آن را بازسازی کن",
                    size=12, font=FONT_MED, color=WARN, expand=True),
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


def _net_card(st) -> ft.Control:
    """یادآوری شبکهٔ اترنت اختصاصی و مقادیر پیش‌فرض گیتوی."""
    host = st.get("host") or "192.168.50.1"
    port = st.get("port") or "1884"
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.LAN, size=18, color=OK),
            txt(("شبکهٔ گیتوی: W5500 + DHCP — بدون وای‌فای و بدون شبکهٔ شرکت. "
                 f"کشف خودکار بروکر؛ نشانی جایگزین {host}:{port}"),
                size=12, font=FONT, color=OK, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=_BG_OK, border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=8))


def _step1_card(app, st) -> ft.Control:
    """گام ۱ — پیدا کردن برد و تأیید هویت."""
    blocks = [
        txt("۱) برد را با کابل دیتادار به همین سیستم وصل کن", size=14,
            font=FONT_B, color=INK),
        txt("اسکن پورت‌ها، انتخاب برد و سپس «خواندن و تأیید مشخصات» را بزن. "
            "برنامه فقط ESP32-S3 با فلش ۱۶ مگابایت را برای این فریمور می‌پذیرد.",
            size=12, font=FONT, color=TEXT_MUTED),
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
        blocks.append(ft.Button(
            "خواندن و تأیید مشخصات برد", icon=ft.Icons.MEMORY,
            style=ft.ButtonStyle(
                bgcolor=WHITE, color=INK,
                shape=ft.RoundedRectangleBorder(radius=R_BTN),
                side=ft.BorderSide(1, BORDER)),
            on_click=lambda e: _read_ident(app, st)))
        blocks.append(ft.TextButton("اسکن دوباره", icon=ft.Icons.REFRESH,
                                    on_click=lambda e: (_scan_ports(app, st),
                                                        app.render())))

    # نتیجهٔ خواندن مشخصات + هشدارها
    if st.get("ident"):
        d = st["ident"]
        compatible = _identity_compatible(d)
        blocks.append(ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE if compatible else ft.Icons.ERROR_OUTLINE,
                            size=16, color=OK if compatible else OFFLINE),
                    txt("برد آمادهٔ فلش است" if compatible else
                        "مدل برد با فریمور گیتوی سازگار نیست",
                        size=12.5, font=FONT_MED, color=OK if compatible else OFFLINE),
                ], spacing=6),
                ft.Row([
                    _chip(d.get("chip") or "ESP32", INK, _BG_GRAY),
                    _chip(f"فلش {d.get('flash') or '?'}", INK, _BG_GRAY),
                    _chip(d.get("mac") or "—", INK, _BG_GRAY),
                ], spacing=6, wrap=True),
            ], spacing=6),
            bgcolor=_BG_OK if compatible else _BG_ERR, border_radius=R_CARD,
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
    """گام ۲ — هویت گیتوی و نشانی جایگزین بروکر."""
    rows = _registered_gateways(st.get("gw_rows"))

    def pick(event):
        if st.get("flashing"):
            return
        gw_id = str(event.control.value or "").strip()
        row = next((r for r in rows if str(r.get("gw") or "") == gw_id), None)
        if row is None:
            return
        st["gw_id"] = gw_id
        st["label"] = row.get("label") or gw_id
        st["zone"] = row.get("zone") or ""
        app.render()

    selected = str(st.get("gw_id") or "")
    selected_row = next((r for r in rows if str(r.get("gw") or "") == selected), None)
    if selected_row is None and rows:
        selected_row = rows[0]
        selected = str(selected_row["gw"])
        st["gw_id"] = selected
        st["label"] = selected_row.get("label") or selected
        st["zone"] = selected_row.get("zone") or ""
    elif not rows:
        selected = ""
        st.update(gw_id="", label="", zone="")
    blocks = [
        txt("۲) شناسه و مشخصات گیت‌وی", size=14, font=FONT_B, color=INK),
        txt("شناسه همان است که در برد نوشته می‌شود و در دفتر پل ثبت "
            "می‌گردد. کد منطقه/محل نصب را وارد کن؛ IP را W5500 از DHCP "
            "می‌گیرد و آدرس بروکر معمولاً با UDP پیدا می‌شود.",
            size=11.5, font=FONT, color=TEXT_MUTED),
    ]
    if rows:
        gateway_selector = ft.Dropdown(
            label="شناسهٔ گیت‌وی از دفتر",
            data="provisioning:gateway",
            value=selected,
            disabled=bool(st.get("flashing")),
            options=[ft.DropdownOption(
                key=str(row["gw"]),
                text=f"{row['gw']} — {row.get('label') or row['gw']} — {row.get('zone') or 'منطقه ثبت نشده'}",
            ) for row in rows],
            on_select=pick,
        )
        blocks.append(gateway_selector)
    else:
        blocks.append(ft.Container(
            data="provisioning:no-gateways",
            content=txt("گیت‌وی ثبت‌شده‌ای در دفتر نیست. ابتدا در بخش «گیت‌وی‌ها» "
                        "شناسهٔ گیت‌وی را تعریف کنید؛ ورود دستی شناسه در این صفحه مجاز نیست.",
                        size=12, font=FONT_MED, color=WARN),
            bgcolor=_BG_WARN, border_radius=R_CARD,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        ))
    blocks.append(ft.TextButton("تازه‌سازی فهرست گیت‌وی‌ها", icon=ft.Icons.REFRESH,
                               disabled=bool(st.get("flashing")),
                               on_click=lambda e: app.render(), data="provisioning:refresh-gateways"))
    # نکته: Row(wrap=True) فرزند expand=True را نمیپذیرد (خطای WrapParentData
    # سمت Flutter)؛ ردیفهای فیلد با کمک flow ساخته میشوند — دسکتاپ Row،
    # موبایل ستون تمامعرض (مثل صفحهٔ «لاگ برنامه»).
    blocks += [
        flow(app, [
            _field("نام نمایشی", "label", st, expand=1),
            _field("منطقه / محل نصب", "zone", st, expand=1),
        ], spacing=8),
        flow(app, [
            _field("آدرس جایگزین بروکر MQTT", "host", st, expand=3),
            _field("پورت MQTT", "port", st, expand=1),
            _field("بازه پایش (دقیقه)", "health_interval_s", st, expand=1),
        ], spacing=8),
        txt("شبکهٔ عادی با DHCP از W5500 می‌آید؛ آدرس بروکر با UDP کشف می‌شود. "
            "نشانی بالا فقط در صورت در دسترس نبودن سرویس کشف استفاده می‌شود.",
            size=11, font=FONT, color=TEXT_MUTED),
    ]
    return card(ft.Column(blocks, spacing=10), pad=14)


def _step3_card(app, st) -> ft.Control:
    """گام ۳ — فلش فریمور و تنظیمات اجباری گیتوی."""
    blocks = [
        txt("۳) فلش فریمور و تنظیمات گیتوی", size=14, font=FONT_B, color=INK),
        txt("شناسه و منطقهٔ همین فرم همراه فریمور نوشته می‌شوند. هر برد باید "
            "شناسهٔ یکتا داشته باشد. تصویر فلش کامل شامل فریمور ESP32-S3 و "
            "LittleFS با همان تنظیمات است.", size=11.5, font=FONT, color=TEXT_MUTED),
    ]

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
        ident_ok = _identity_compatible(st.get("ident"))
        blocks.append(ft.Button(
            "شروع فلش کامل", icon=ft.Icons.DOWNLOAD,
            disabled=bool(st.get("flashing") or not st.get("sel_port") or not ident_ok
                          or _selected_gateway(st) is None),
            tooltip=(None if ident_ok else "ابتدا مشخصات ESP32-S3 و فلش ۱۶MB را تأیید کن"),
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
        txt("• برد را فقط از طریق کابل USB برنامه‌ریزی کن. برای شبکهٔ داده، "
            "پس از نصب کابل LAN ماژول W5500 را به سوئیچ همان بخش وصل کن.",
            size=11.5, font=FONT, color=TEXT_MAIN),
        txt("• شبکهٔ گیتوی جدا از شبکهٔ شرکت است. DHCP از کامپیوتر HSE می‌آید؛ "
            "این کارت شبکهٔ جدا را به شبکهٔ شرکت وصل نکن.",
            size=11.5, font=FONT, color=TEXT_MAIN),
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
        "برد را با کابل USB وصل کن و مشخصاتش را تأیید کن؛ برنامه شناسه و منطقهٔ "
        "همین فرم را داخل فریمور و LittleFS می‌نویسد. پس از نصب W5500 را به سوئیچ "
        "بخش وصل کن تا از DHCP شبکهٔ اختصاصی IP بگیرد.")

    return ft.Column([
        header,
        _bundle_card(st),
        _net_card(st),
        _step1_card(app, st),
        _step2_card(app, st),
        _step3_card(app, st),
        _help_card(),
    ], spacing=14, scroll=ft.ScrollMode.AUTO)
