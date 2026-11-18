# -*- coding: utf-8 -*-
"""بخش «گیت‌وی‌ها» — تعریف گیت‌وی، منطقه و چیدمان روی نقشهٔ کارخانه.

دفتر گیت‌وی‌ها روی پل است (backend/bridge.py — /api/gateways)؛ این صفحه
فهرست ادغام‌شده با وضعیت زندهٔ شبکه را نشان می‌دهد:

  - تعریف‌شده‌ها: نام، شناسه، منطقه، نصب‌شده/پیشنهادی، آنلاین/آفلاین و
    چیده‌شدن روی نقشه — با ویرایش، حذف و میان‌بر «روی نقشه».
  - کشف‌شده‌ها: گیت‌وی‌هایی که در شبکه دیده شده‌اند ولی هنوز تعریف نشده‌اند
    — با دکمهٔ «تعریف» با همان شناسهٔ موجود در شبکه.
  - نبود پل: پیام نبود اطلاعات واقعی — بدون گیت‌وی نمونه.

جابه‌جایی پین‌ها روی نقشه در صفحهٔ «نقشه کارخانه» و حالت «چیدن» انجام
می‌شود؛ دکمهٔ «روی نقشه» همان‌جا می‌برد.
"""

import asyncio

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN, R_CARD,
    TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
import data as gateway_data
from data import live_gateways, can_manage_gateways
from components.common import SHADOW, card, rel_age, section_header
from components.gateway_form import (
    open_gateway_delete, open_gateway_form,
)

_KIND_FA = {"installed": "نصب‌شده", "proposed": "پیشنهادی"}
_DISCOVERED = "#9AA0A6"
_BG_OK = "#E6F4EB"
_BG_WARN = "#FCF0DC"
_BG_GRAY = "#F1F2F4"


class _GatewaysColumn(ft.Column):
    def did_mount(self):
        self._gateway_mounted = True

    def will_unmount(self):
        self._gateway_disposed = True


def _confirm_network_define(app, item, rows, on_saved, is_current):
    """Require an explicit click before turning a LAN observation into a row."""
    gid = str(item.get("gw") or "")
    ip = str(item.get("network_ip") or item.get("ip") or "—")
    fw = str(item.get("fw") or "—")
    body = ft.Column([
        txt(f"شناسه: {gid}", size=13, font=FONT_MED, color=INK),
        txt(f"IP شبکه: {ip}", size=12, font=FONT, color=TEXT_MUTED),
        txt(f"فریم‌ور: {fw}", size=12, font=FONT, color=TEXT_MUTED),
        txt("این مشاهدهٔ شبکه ثبت گیت‌وی را تغییر نمی‌دهد مگر این‌که ثبت را تأیید کنی.",
            size=12, font=FONT, color=TEXT_MUTED),
    ], spacing=6)

    def _cancel(e):
        try:
            app.page.pop_dialog()
        except Exception:
            pass

    def _confirm(e):
        if not is_current():
            return
        try:
            app.page.pop_dialog()
        except Exception:
            pass
        open_gateway_form(
            app, gw=gid,
            row={"gw": gid, "kind": "installed", "zone": item.get("zone") or ""},
            rows=rows, on_saved=on_saved)

    dialog = ft.AlertDialog(
        modal=True,
        title=txt("تأیید تعریف گیت‌وی", size=16, font=FONT_B, color=INK),
        content=ft.Container(width=380, content=body),
        actions=[
            ft.TextButton("انصراف", on_click=_cancel),
            ft.Button("تعریف گیت‌وی", on_click=_confirm,
                      style=ft.ButtonStyle(
                          bgcolor=INK, color=WHITE,
                          shape=ft.RoundedRectangleBorder(radius=R_BTN))),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    app.page.show_dialog(dialog)


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
        return _chip("آنلاین — ضربان MQTT", OK, _BG_OK)
    if item.get("live"):
        return _chip("آفلاین — ضربان MQTT قطع شده", TEXT_MUTED, _BG_GRAY)
    if item.get("registered") is False:
        return _chip("ضربان MQTT دریافت نشده", TEXT_MUTED, _BG_GRAY)
    return _chip("هنوز دیده نشده", TEXT_MUTED, _BG_GRAY)


def _network_chip(item):
    if not item.get("network_seen"):
        return None
    if item.get("network_mqtt_connected") is True:
        return _chip("LAN دیده شد · گزارش گیت‌وی: بروکر MQTT متصل",
                     OK, _BG_OK)
    if item.get("network_mqtt_connected") is False:
        return _chip("LAN دیده شد · گزارش گیت‌وی: بروکر MQTT جدا",
                     TEXT_MUTED, _BG_GRAY)
    return _chip("LAN دیده شد · وضعیت بروکر MQTT گزارش نشده",
                 TEXT_MUTED, _BG_GRAY)


def _placed_chip(item):
    if item.get("x") is not None and item.get("y") is not None:
        return _chip("روی نقشه", OK, _BG_OK)
    return _chip("چیده‌نشده", TEXT_MUTED, _BG_GRAY)


def _gw_card_row(item, on_edit=None, on_delete=None, on_map=None, actions=True,
                 can_edit=True, on_define=None):
    """کارت یک گیت‌وی — چیپ‌های وضعیت، زیرنویس و دکمه‌های اقدام."""
    gid = str(item.get("gw") or "—")
    label = item.get("label") or gid
    subs = [gid]
    if item.get("network_ip") or item.get("ip"):
        subs.append(f"IP شبکه {item.get('network_ip') or item['ip']}")
    if item.get("network_mac") or item.get("mac"):
        subs.append(f"مک {item.get('network_mac') or item['mac']}")
    if item.get("network_fw") or item.get("fw"):
        subs.append(f"فریم‌ور {item.get('network_fw') or item['fw']}")
    if item.get("zone"):
        subs.append(str(item["zone"]))
    if item.get("age_s") is not None:
        subs.append(f"آخرین تماس {rel_age(item['age_s'])}")
    buttons = []
    if actions:
        buttons = [
            ft.IconButton(ft.Icons.MAP, tooltip="نمایش روی نقشهٔ کارخانه",
                          icon_size=18, on_click=on_map),
            ft.IconButton(ft.Icons.EDIT, tooltip="ویرایش" if can_edit else "فقط ادمین اصلی می‌تواند ویرایش کند",
                          icon_size=18, icon_color=INK if can_edit else TEXT_MUTED,
                          on_click=on_edit if can_edit else None, disabled=not can_edit),
            ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="حذف از دفتر" if can_edit else "فقط ادمین اصلی می‌تواند حذف کند",
                          icon_size=18, icon_color=OFFLINE if can_edit else TEXT_MUTED,
                          on_click=on_delete if can_edit else None, disabled=not can_edit),
        ]
    elif on_define is not None and can_edit:
        buttons.append(ft.Button(
            "تعریف", icon=ft.Icons.ADD, data="gateway:define:" + gid,
            style=ft.ButtonStyle(
                bgcolor=WHITE, color=INK,
                shape=ft.RoundedRectangleBorder(radius=R_BTN),
                side=ft.BorderSide(1, BORDER),
            ), on_click=on_define,
        ))
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
                *([_network_chip(item)] if item.get("network_seen") else []),
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
            txt("پل محلی در دسترس نیست — اطلاعات گیت‌وی‌ها تازه نمی‌شود؛ تعریف و ذخیره "
                "نیاز به بالا بودن پل دارد", size=13, font=FONT_MED,
                color=WARN, expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=_BG_WARN, border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )


def gateways_view(app):
    """صفحهٔ «گیت‌وی‌ها» — دفتر گیت‌وی پل + کشف‌شده‌های شبکه."""
    # نقش کاربر
    my_role = app.state.get("role", "viewer")
    can_edit = bool(app.state.get("logged_in") and can_manage_gateways(my_role))
    
    rows = live_gateways()
    bridge_up = rows is not None
    rows = rows or []
    registered = [r for r in rows if r.get("registered") is not False]
    discovered = [r for r in rows if r.get("registered") is False
                  and not r.get("network_seen")]

    def _refresh():
        app.render()

    def _new(e):
        open_gateway_form(app, rows=rows, on_saved=_refresh)

    # The bridge remains the only boundary for discovery, persistence and auth.
    # A view token prevents a result arriving after navigation updating stale UI.
    view_token = object()
    app.state["gateway_discovery_view_token"] = view_token
    discovery_status = txt("", size=12, font=FONT, color=TEXT_MUTED, visible=False,
                           data="gateway:discovery-status")
    discovered_rows = [r for r in rows if r.get("network_seen")
                       and r.get("registered") is False]
    discovery_error = txt("", size=12, font=FONT, color=OFFLINE, visible=False,
                          data="gateway:discovery-error")
    discovery_list = ft.Column([], spacing=8, data="gateway:discovery-results")
    discovery_busy = {"value": False}
    origin_view = app.state.get("view")
    origin_actor = app.state.get("admin_email")

    def _discovery_is_current():
        if getattr(root, "_gateway_disposed", False):
            return False
        if getattr(root, "_gateway_mounted", False):
            try:
                if root.page is not app.page or app.page.session.connection is None:
                    return False
            except RuntimeError:
                return False
        return (app.state.get("gateway_discovery_view_token") is view_token
                and app.state.get("view") == origin_view
                and bool(origin_actor)
                and app.state.get("admin_email") == origin_actor
                and app.state.get("role", "viewer") == my_role
                and bool(app.state.get("logged_in")
                         and can_manage_gateways(app.state.get("role", ""))))

    def _draw_discovered(items):
        discovery_list.controls = []
        for item in items:
            # Overlay discovery metadata without changing this gateway's actual
            # registry state or MQTT-heartbeat status.
            network_item = dict(item)
            network_item["network_seen"] = True
            network_item["network_mqtt_connected"] = item.get(
                "network_mqtt_connected", item.get("mqtt_connected"))
            network_item["network_ip"] = item.get("network_ip", item.get("ip"))
            network_item["network_mac"] = item.get("network_mac", item.get("mac"))
            define = None
            if can_edit and item.get("registered") is not True:
                def define_from_network(e, item=item):
                    if _discovery_is_current() and not discovery_busy["value"]:
                        _confirm_network_define(app, item, rows, _refresh,
                                                _discovery_is_current)

                define = define_from_network
            discovery_list.controls.append(_gw_card_row(
                network_item, actions=False, can_edit=can_edit, on_define=define))

    _draw_discovered(discovered_rows)

    async def _discover_gateways(e):
        nonlocal rows
        if not _discovery_is_current() or discovery_busy["value"]:
            return
        if not bridge_up:
            return
        discovery_busy["value"] = True
        discover_btn.disabled = True
        discovery_status.value = "در حال جستجوی گیت‌وی‌های شبکه…"
        discovery_status.visible = True
        discovery_error.visible = False
        discovery_error.value = ""
        discovery_list.controls = []
        app.page.update()
        try:
            discover = getattr(gateway_data, "discover_gateways", None)
            if not callable(discover):
                discovery_error.value = "جستجوی شبکه هنوز از لایهٔ داده در دسترس نیست."
                discovery_error.visible = True
                discovery_status.value = "جستجوی شبکه کامل نشد."
                return
            result = await asyncio.to_thread(discover, actor=origin_actor)
            if not _discovery_is_current():
                return
            if not isinstance(result, tuple) or len(result) != 2:
                discovery_error.value = "پاسخ پل برای جستجوی گیت‌وی معتبر نیست"
                discovery_error.visible = True
                discovery_status.value = "جستجوی شبکه کامل نشد."
                return
            ok, devices = result
            if not ok or not isinstance(devices, list):
                discovery_error.value = str(devices or "جستجوی شبکه ناموفق بود")
                discovery_error.visible = True
                discovery_status.value = "جستجوی شبکه کامل نشد."
                return
            # Read the persisted network observation back through the data facade.
            fresh = await asyncio.to_thread(live_gateways, force=True)
            if not _discovery_is_current():
                return
            if fresh is None:
                discovery_error.value = "مشاهدهٔ جستجو ذخیره شد، اما تازه‌سازی پل شکست خورد."
                discovery_error.visible = True
                discovery_status.value = "نتیجهٔ تازه از پل در دسترس نیست."
                return
            current_rows = list(fresh)
            rows = current_rows
            current_by_gw = {str(row.get("gw")): row for row in current_rows}
            displayed = []
            seen_gws = set()
            for device in devices or []:
                if not isinstance(device, dict) or not device.get("gw"):
                    continue
                gid = str(device["gw"])
                if gid in seen_gws:
                    continue
                seen_gws.add(gid)
                merged = dict(current_by_gw.get(gid) or {})
                if gid not in current_by_gw:
                    merged.update({"registered": False, "kind": "installed"})
                merged.update({
                    "gw": gid,
                    "network_seen": True,
                    "network_ip": device.get("ip"),
                    "network_mac": device.get("mac"),
                    "network_mqtt_connected": device.get("mqtt_connected"),
                })
                if device.get("fw"):
                    merged["network_fw"] = device["fw"]
                displayed.append(merged)
            _draw_discovered(displayed)
            discovery_status.value = (
                f"{fa_num(len(displayed))} گیت‌وی در شبکه دیده شد."
                if displayed else "در این جستجو گیت‌وی‌ای پاسخ نداد.")
        except Exception:
            if _discovery_is_current():
                discovery_error.value = "جستجوی گیت‌وی انجام نشد؛ اتصال پل را بررسی کنید."
                discovery_error.visible = True
                discovery_status.value = "جستجوی شبکه کامل نشد."
        finally:
            if _discovery_is_current():
                discovery_busy["value"] = False
                discover_btn.disabled = False
                app.page.update()

    discover_btn = ft.Button(
        "جستجوی گیت‌وی در شبکه", icon=ft.Icons.SEARCH, data="gateway:discover",
        disabled=not (bridge_up and can_edit), visible=bridge_up and can_edit,
        tooltip=(None if bridge_up and can_edit else
                 "فقط مدیر گیت‌وی‌ها می‌تواند جستجو کند" if not can_edit else
                 "برای جستجو، پل محلی باید در دسترس باشد"),
        style=ft.ButtonStyle(
            bgcolor=WHITE, color=INK,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
            side=ft.BorderSide(1, BORDER),
        ),
        on_click=_discover_gateways if can_edit else None,
    )
    discovery_card = card(ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.WIFI_TETHERING, size=16, color=INK),
            txt("کشف شبکهٔ محلی", size=14, font=FONT_B, color=INK),
            ft.Container(expand=True),
            discover_btn,
        ], spacing=8),
        discovery_status, discovery_error, discovery_list,
    ], spacing=8), pad=12)

    new_btn = ft.Button(
        "گیت‌وی جدید",
        icon=ft.Icons.ADD_LOCATION_ALT,
        disabled=not bridge_up or not can_edit,
        tooltip=None if (bridge_up and can_edit) else "فقط ادمین اصلی می‌تواند گیت‌وی اضافه کند" if not can_edit else "برای تعریف، پل باید بالا باشد",
        style=ft.ButtonStyle(
            bgcolor=INK, color=WHITE,
            shape=ft.RoundedRectangleBorder(radius=R_BTN),
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
        ),
        on_click=_new if can_edit else None,
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
                _gw_card_row(item, on_edit, on_delete, on_map, can_edit=can_edit))
    elif bridge_up:
        list_col.controls.append(txt(
            "هنوز گیت‌ویی تعریف نشده — با «گیت‌وی جدید» شروع کن. برای هر "
            "برد، همان شناسه‌ای را بگذار که در config.json می‌آید.",
            size=12, font=FONT, color=TEXT_MUTED))
    else:
        list_col.controls.append(txt(
            "گیت‌وی ثبت‌شده یا دادهٔ تازه‌ای از پل در دسترس نیست.",
            size=12, font=FONT, color=TEXT_MUTED))

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
    blocks = [header, discovery_card]
    if not bridge_up:
        blocks.append(_demo_banner())
    blocks.append(counters)
    blocks.append(registered_card)
    if discovered:
        disc_col = ft.Column([], spacing=8)
        for item in discovered:
            gid = str(item.get("gw") or "")

            def _define(e, gid=gid, item=item):
                if not _discovery_is_current():
                    return
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
                        disabled=not can_edit,
                        on_click=_define if can_edit else None),
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

    root = _GatewaysColumn(blocks, spacing=14, scroll=ft.ScrollMode.AUTO)
    return root