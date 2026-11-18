# -*- coding: utf-8 -*-
"""هشدارها — فقط رویدادهای ماندگار دریافت‌شده از پل."""

import asyncio

import flet as ft

from theme import (
    BORDER, DANGER, DANGER_BG, FONT, FONT_B, FONT_MED, INK, R_BTN, R_CARD,
    TEXT_MUTED, WARN, WHITE, fa_num, txt,
)
from data import live_status, live_employees, send_vibrate
from layout import flow, is_phone
from components.common import card, status_chip
from components.battery_alerts import battery_alert_panel
from components.common import ISSUE_LABELS
from alert_contacts import resolve_alert_contact


def _action_btn(label, icon, bg, on_click, *, data=None):
    return ft.Button(
        label, icon=icon, height=36, data=data,
        style=ft.ButtonStyle(bgcolor=bg, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=on_click,
    )


def _contact_responsible(app, alert):
    try:
        contact = resolve_alert_contact(alert, live_employees(force=True))
    except Exception:
        contact = None
    if contact is None:
        app.snack("برای این واحد مچ‌بند سرشیفت، سرپرست یا HSE پیدا نشد")
        return
    ok, message = send_vibrate(contact["mac"])
    if ok:
        app.snack(f"ویبره برای {contact['contact_label']} واحد ارسال شد")
    else:
        app.snack(f"ارسال ویبره به {contact['contact_label']} ناموفق بود: {message}")


def _alert_title(alert):
    raw = alert.get("title") or alert.get("type") or "هشدار"
    return {"gateway_offline": "گیت‌وی آفلاین"}.get(raw, ISSUE_LABELS.get(raw, raw))


def _alert_time(alert):
    return alert.get("time") or alert.get("created_at") or "—"


def _alert_location(alert):
    location = alert.get("location") or alert.get("zone") or "—"
    if isinstance(location, dict):
        location = location.get("zone") or location.get("gw") or "—"
    return str(location)


def _alert_card(app, alert):
    danger = alert.get("severity") == "danger"
    acknowledged = alert.get("status") == "acknowledged"
    status = "danger" if danger else "warn"
    action = ft.Button(
        "تأیید شد" if acknowledged else "تأیید هشدار", icon=ft.Icons.CHECK,
        height=36, disabled=acknowledged, data=f"alerts:ack:{alert.get('id')}",
        style=ft.ButtonStyle(bgcolor=TEXT_MUTED if acknowledged else INK, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=lambda e, aid=alert.get("id"): app.acknowledge_alert(aid),
    )
    contact = ft.OutlinedButton(
        "ویبرهٔ مسئول واحد", icon=ft.Icons.VIBRATION, height=36,
        data="alerts:contact-responsible",
        style=ft.ButtonStyle(color=INK,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=lambda e, aa=alert: _contact_responsible(app, aa),
    )
    state_text = "تأییدشده" if acknowledged else (
        "فرمان ویبره تأیید شده" if alert.get("delivery_status") == "confirmed"
        or alert.get("vibration_status") == "confirmed" else "باز")
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.SOS if danger else ft.Icons.ERROR_OUTLINE,
                                    size=20, color=WHITE if danger else WARN),
                    bgcolor=DANGER if danger else "#FCF0DC",
                    border_radius=10, padding=ft.Padding.all(9),
                ),
                ft.Column([
                    txt(f"{_alert_title(alert)} — {alert.get('emp') or alert.get('name') or '—'}",
                        size=15, font=FONT_B, color=INK),
                    txt(f"{alert.get('dept') or '—'} • {_alert_location(alert)} • "
                        f"ساعت {_alert_time(alert)}", size=12, font=FONT, color=TEXT_MUTED),
                ], spacing=2, expand=True),
                status_chip(status),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([action, contact], spacing=8, wrap=True, run_spacing=8),
            txt(state_text, size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=10),
        padding=16, bgcolor=DANGER_BG if danger else WHITE,
        border=ft.Border.all(1.5 if danger else 1, DANGER if danger else BORDER),
        border_radius=R_CARD,
    )


def _history_card(rows):
    children = [txt("تاریخچهٔ هشدارهای دریافت‌شده", size=15, font=FONT_B, color=INK)]
    for index, alert in enumerate(rows):
        children.append(ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE if alert.get("status") != "open"
                        else ft.Icons.ERROR_OUTLINE, size=17,
                        color="#1E8E4E" if alert.get("status") != "open" else WARN),
                ft.Column([
                    txt(f"{_alert_title(alert)} — {alert.get('emp') or alert.get('name') or '—'}",
                        size=13, font=FONT_MED, color=INK),
                    txt({"acknowledged": "تأییدشده", "closed": "بسته‌شده"}.get(
                        alert.get("status"), "باز"), size=11, font=FONT, color=TEXT_MUTED),
                ], spacing=1, expand=True),
                txt(str(_alert_time(alert)), size=12, font=FONT, color=TEXT_MUTED),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(vertical=9),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER))
            if index < len(rows) - 1 else None,
        ))
    return card(ft.Column(children, spacing=6), pad=18)


def alerts_view(app):
    generation = app.state.get("alerts_gen", 0) + 1
    app.state["alerts_gen"] = generation
    holder = ft.Column([], spacing=14)
    battery_holder = ft.Container()

    def snapshot():
        doc = live_status()
        if not doc or not doc.get("ok"):
            return None, None, None
        active = doc.get("alerts_active", getattr(app, "alerts_active", []))
        history = doc.get("alerts_history", getattr(app, "alerts_history", []))
        return ([a for a in active if a.get("source", "live") == "live"],
                [a for a in history if a.get("source", "live") == "live"],
                doc.get("battery_alerts") or [])

    def render_snapshot(active, history, batteries):
        if active is None:
            active = []
        if history is None:
            history = []
        battery_holder.content = battery_alert_panel(batteries or [])
        cards = [_alert_card(app, a) for a in active
                 if a.get("status", "open") in ("open", "acknowledged")]
        if not cards:
            cards = [ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, size=38, color="#1E8E4E"),
                    txt("هیچ هشدار فعالی از پل دریافت نشده است", size=14,
                        font=FONT_MED, color=TEXT_MUTED),
                ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=36, bgcolor=WHITE, border_radius=R_CARD,
                border=ft.Border.all(1, BORDER),
                alignment=ft.alignment.Alignment(0, 0),
            )]
        active_col = ft.Column([
            ft.Row([txt("هشدارهای فعال", size=15, font=FONT_B, color=INK),
                    txt(fa_num(len(active)), size=13, font=FONT_MED, color=TEXT_MUTED)], spacing=8),
            *cards,
        ], spacing=12, expand=True)
        holder.controls = [battery_holder, flow(app, [active_col], spacing=14),
                           _history_card(history)]

    active, history, batteries = snapshot()
    unavailable = active is None
    if unavailable:
        active, history, batteries = [], [], []
    render_snapshot(active, history, batteries)
    if unavailable:
        holder.controls.insert(0, txt("پل محلی در دسترس نیست — هشدارها به‌روز نیستند",
                                     size=12, font=FONT_MED, color=TEXT_MUTED,
                                     data="alerts:connection"))

    async def loop():
        while app.state.get("view") == "alerts" and app.state.get("alerts_gen") == generation:
            await asyncio.sleep(2)
            if app.state.get("view") != "alerts" or app.state.get("alerts_gen") != generation:
                return
            try:
                active, history, batteries = await asyncio.to_thread(snapshot)
                unavailable = active is None
                if unavailable:
                    active, history, batteries = [], [], []
                render_snapshot(active or [], history or [], batteries or [])
                if unavailable:
                    holder.controls.insert(0, txt(
                        "پل محلی در دسترس نیست — هشدارها به‌روز نیستند",
                        size=12, font=FONT_MED, color=TEXT_MUTED,
                        data="alerts:connection"))
                app.page.update()
            except RuntimeError:
                return

    if hasattr(app.page, "run_task"):
        app.page.run_task(loop)
    return ft.Column([holder], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)
