"""Owner-only gateway BLE diagnostics; no employee or monitoring mutation."""
from __future__ import annotations

import asyncio

import flet as ft

import data as gateway_data
from components.common import card
from theme import (BORDER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN,
                   TEXT_MUTED, WARN, WHITE, fa_num, txt)


def _allowed(app, is_current) -> bool:
    return bool(is_current() and app.state.get("logged_in")
                and gateway_data.can_manage_gateways(app.state.get("role", "viewer"))
                and app.state.get("admin_email"))


def gateway_diagnostics_card(app, rows, is_current):
    """Build one bounded scan/probe workflow for the gateways page."""
    if not gateway_data.can_manage_gateways(app.state.get("role", "viewer")):
        return ft.Container(visible=False, data="gateway:diagnostics-owner-only")

    gateways = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        gw = str(row.get("gw") or "").strip().lower()
        if gw:
            gateways.setdefault(gw, row)
    choices = sorted(gateways.values(), key=lambda row: (
        not bool(row.get("online")), str(row.get("label") or row.get("gw") or "")))

    busy = False
    actor = str(app.state.get("admin_email") or "").strip().lower()
    origin_role = app.state.get("role", "viewer")

    def current():
        return bool(_allowed(app, is_current) and app.state.get("role") == origin_role
                    and str(app.state.get("admin_email") or "").strip().lower() == actor)

    status = txt("این آزمون جدا از پایش کارکنان است و هیچ برنامهٔ کاری یا دادهٔ سلامت را تغییر نمی‌دهد.",
                 size=11.5, font=FONT, color=TEXT_MUTED,
                 data="gateway:diagnostic-status")
    results = ft.Column([], spacing=6, data="gateway:diagnostic-results")
    selector = ft.Dropdown(
        label="گیت‌وی برای آزمون بلوتوث",
        data="gateway:diagnostic-gateway",
        value=str(choices[0]["gw"]) if choices else None,
        options=[ft.DropdownOption(
            key=str(row["gw"]),
            text=f"{row.get('label') or row['gw']} — {row['gw']}",
        ) for row in choices],
        disabled=not choices,
    )

    def set_busy(value):
        scan_btn.disabled = value or not choices
        selector.disabled = value or not choices
        for control in results.controls:
            for child in getattr(control, "controls", []) or []:
                if isinstance(child, ft.Button):
                    child.disabled = value

    def show(message, error=False):
        status.value = message
        status.color = OFFLINE if error else TEXT_MUTED

    def show_devices(devices):
        results.controls = []
        for device in devices:
            mac = str(device.get("mac") or "")
            rssi = device.get("rssi")

            async def probe(_event, selected=mac):
                await run("probe", selected)

            results.controls.append(ft.Row([
                ft.Icon(ft.Icons.BLUETOOTH, size=18, color=INK),
                ft.Column([
                    txt(mac, size=12.5, font=FONT_MED, color=INK),
                    txt(f"قدرت سیگنال {fa_num(rssi)} dBm", size=11, font=FONT, color=TEXT_MUTED),
                ], spacing=2, expand=True),
                ft.Button("آزمون اتصال", icon=ft.Icons.LINK,
                          data="gateway:diagnostic-probe:" + mac,
                          style=ft.ButtonStyle(
                              bgcolor=WHITE, color=INK,
                              shape=ft.RoundedRectangleBorder(radius=R_BTN),
                              side=ft.BorderSide(1, BORDER)),
                          on_click=probe),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

    def show_probe(info):
        mac = str(info.get("mac") or selector.value or "")
        if info.get("status") == "done" and info.get("connected") is True:
            battery = info.get("battery")
            suffix = f"؛ باتری {fa_num(battery)}٪" if isinstance(battery, int) else "؛ باتری گزارش نشد"
            show(f"اتصال موفق به {mac} برقرار و قطع شد{suffix}")
        elif info.get("status") == "timeout":
            show("پاسخ آزمون اتصال در مهلت مقرر نرسید؛ گیت‌وی و مچ‌بند را بررسی کنید", True)
        elif info.get("status") == "rejected":
            show("گیت‌وی آزمون اتصال را رد کرد؛ ابتدا جستجوی تازه انجام دهید", True)
        else:
            show(f"اتصال به {mac} برقرار نشد؛ مچ‌بند را نزدیک و آزاد نگه دارید", True)

    async def run(action, mac=""):
        nonlocal busy
        if busy or not current() or not selector.value:
            return
        if action == "probe" and not mac:
            return
        busy = True
        set_busy(True)
        if action == "scan":
            results.controls = []
        show("در حال ارسال درخواست آزمون…")
        app.page.update()
        try:
            ok, info = await asyncio.to_thread(
                gateway_data.gateway_diagnostic, actor=actor, action=action,
                gw=str(selector.value), mac=mac)
            if not current():
                return
            if not ok:
                show(str(info), True)
                return
            if not isinstance(info, dict):
                show("پاسخ پل برای آزمون معتبر نیست", True)
                return
            request_id = str(info.get("request_id") or "")
            if not request_id:
                show("پل شناسهٔ آزمون برنگرداند", True)
                return
            for _ in range(28):
                if info.get("status") != "pending":
                    break
                show("در حال جستجوی مچ‌بندهای اطراف…" if action == "scan"
                     else "در حال آزمون اتصال؛ مچ‌بند را نزدیک و آزاد نگه دارید…")
                app.page.update()
                await asyncio.sleep(0.75)
                ok, info = await asyncio.to_thread(
                    gateway_data.gateway_diagnostic, actor=actor, action="status",
                    request_id=request_id)
                if not current():
                    return
                if not ok:
                    show(str(info), True)
                    return
                if not isinstance(info, dict):
                    show("پاسخ پل برای وضعیت آزمون معتبر نیست", True)
                    return
            if action == "scan":
                if info.get("status") == "done":
                    devices = info.get("devices") or []
                    show_devices(devices)
                    show(f"{fa_num(len(devices))} دستگاه بلوتوث دیده شد؛ مچ‌بند موردنظر را برای آزمون اتصال انتخاب کنید"
                         if devices else "در این جستجو مچ‌بندی دیده نشد؛ مچ‌بند را روشن و نزدیک گیت‌وی نگه دارید")
                elif info.get("status") == "timeout":
                    show("پاسخ جستجو در مهلت مقرر نرسید؛ فریم‌ور گیت‌وی و اتصال پیام‌رسان را بررسی کنید", True)
                elif info.get("status") == "rejected":
                    show("گیت‌وی جستجو را رد کرد؛ صبر کنید کار قبلی تمام شود و دوباره تلاش کنید", True)
                else:
                    show("جستجوی مچ‌بندها کامل نشد", True)
            else:
                show_probe(info)
        except Exception:
            if current():
                show("آزمون انجام نشد؛ اتصال برنامه به پل را بررسی کنید", True)
        finally:
            if current():
                busy = False
                set_busy(False)
                app.page.update()

    async def scan(_event):
        await run("scan")

    scan_btn = ft.Button(
        "جستجوی مچ‌بندهای اطراف", icon=ft.Icons.BLUETOOTH_SEARCHING,
        data="gateway:diagnostic-scan", disabled=not choices,
        style=ft.ButtonStyle(
            bgcolor=INK, color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=scan,
    )
    return card(ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.BLUETOOTH_SEARCHING, size=18, color=INK),
            txt("آزمون مستقیم مچ‌بند با گیت‌وی", size=14, font=FONT_B, color=INK),
        ], spacing=8),
        txt("اگر گیت‌وی هنوز آنلاین نیست هم می‌توانید درخواست بدهید؛ فقط پاسخ واقعی همان برد نتیجه محسوب می‌شود.",
            size=11.5, font=FONT, color=WARN),
        selector,
        scan_btn,
        status,
        results,
    ], spacing=9), pad=14)
