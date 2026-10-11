# -*- coding: utf-8 -*-
"""پروفایل کارکن — دو مسیر داده:

مسیر زنده (فاز ۲): کارکن واقعی دفتر پل — شناسه، مک مچ‌بند است؛ فقط دادهٔ
واقعی (وضعیت، حیاتی‌ها، حضور، نمودار آخرین پنجرهٔ سلامت) نمایش داده
می‌شود و بخش‌های هنوز بدون داده، کارت توضیح صادقانه می‌گیرند.

مسیر نمایشی: کارکن نمونهٔ فاز ۱ با شناسهٔ عددی — همهٔ قابلیت‌های طراحی.
"""

import asyncio

import flet as ft

from theme import (
    BORDER, DANGER, DANGER_BG, FONT, FONT_B, FONT_MED, FONT_SB, INK, OFFLINE,
    OK, R_BTN, R_CARD, TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_hours, fa_num, txt,
)
from data import EMPLOYEES, WEEK_HOURS, ZONE_COLORS, live_employees, live_status, send_vibrate
from components.common import (
    ISSUE_LABELS, att_chip, avatar_circle, back_button, card, kv_row,
    mini_caption, rel_age, rssi_quality, status_chip,
)
from components.employee_form import open_delete_confirm, open_employee_form

BAR_BLUE = "#8FB4DE"
BAR_EMPTY = "#E3E5E8"


def _find(emp_id):
    return next((e for e in EMPLOYEES if e["id"] == emp_id), EMPLOYEES[0])


def _hr_chart(series):
    if all(v is None for v in series):
        return ft.Container(
            height=140, alignment=ft.Alignment.CENTER,
            content=txt("دستگاهی متصل نیست — داده‌ای برای نمایش وجود ندارد",
                        size=13, font=FONT, color=TEXT_MUTED),
        )
    bars = []
    for v in series:
        if v is None:
            bars.append(ft.Container(width=9, height=6, bgcolor=BAR_EMPTY, border_radius=2))
            continue
        h = int(8 + (min(v, 150) / 150) * 125)
        color = DANGER if v >= 110 else BAR_BLUE
        bars.append(ft.Container(
            width=9, height=h, bgcolor=color,
            border_radius=ft.BorderRadius.only(top_left=3, top_right=3),
        ))
    return ft.Container(
        height=140, alignment=ft.Alignment.BOTTOM_LEFT,
        content=ft.Row(bars, spacing=4, vertical_alignment=ft.CrossAxisAlignment.END),
    )


def _vital_card(label, value, unit, sub, icon, color, icon_bg):
    return card(ft.Column([
        ft.Row([
            ft.Container(content=ft.Icon(icon, size=18, color=color),
                         bgcolor=icon_bg, border_radius=10,
                         padding=ft.Padding.all(8)),
            ft.Container(expand=True),
            txt(label, size=13, font=FONT_MED, color=TEXT_MUTED),
        ]),
        ft.Row([
            txt(value, size=28, font=FONT, color=INK),
            txt(unit, size=13, font=FONT, color=TEXT_MUTED),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.END),
        txt(sub, size=12, font=FONT, color=TEXT_MUTED),
    ], spacing=8), pad=16)


# ═══════════ مسیر زنده — کارکن واقعی دفتر پل (فاز ۲) ═══════════


def _live_detail(app, mac):
    """پروفایل کارکن متصل به پل — فقط دادهٔ واقعی.

    شناسه، مک مچ‌بند است. بخش‌هایی که هنوز دادهٔ واقعی ندارند (تاریخچهٔ
    حضور و ساعات کار) با کارت توضیح نشان داده می‌شوند، نه دادهٔ نمایشی.
    """
    state = app.state
    mac = str(mac).strip().lower()
    gen = state.get("empd_gen", 0) + 1
    state["empd_gen"] = gen

    def _find_emp(doc):
        for e in doc or []:
            if e.get("mac") == mac:
                return e
        return None

    doc = live_employees()
    emp0 = _find_emp(doc)

    # ── حالت‌های خاص: پل قطع است یا کارکن در دفتر نیست ──
    if emp0 is None:
        msg = ("پل محلی در دسترس نیست — اتصال را بررسی کن"
               if doc is None else "این کارکن در دفتر بخش «کارکنان» نیست")
        return ft.Column([
            card(ft.Row([
                back_button(lambda e: app.go(state.get("back_to", "employees"))),
                txt(msg, size=14, font=FONT_MED, color=TEXT_MUTED, expand=True),
                ft.TextButton("تلاش دوباره", on_click=lambda e: app.render()),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)),
        ], spacing=14, expand=True)

    # ── کنترل‌های مرجع — هر ۲ ثانیه از دادهٔ تازه به‌روز می‌شوند ──
    name_v = txt(emp0.get("name") or "مچ‌بند ثبت‌نشده", size=20,
                 font=FONT_B, color=INK)
    sub_v = txt("", size=12, font=FONT, color=TEXT_MUTED)
    avatar_holder = ft.Container(content=avatar_circle(emp0.get("name") or "؟", r=27))
    status_holder = ft.Container(content=status_chip(emp0.get("status") or "off"))

    bat_txt = txt("باتری —", size=12, font=FONT, color=TEXT_MUTED)
    sig_txt = txt("سیگنال —", size=12, font=FONT, color=TEXT_MUTED)

    def _cap(icon, ctrl):
        return ft.Row([ft.Icon(icon, size=15, color=TEXT_MUTED), ctrl],
                      spacing=5, tight=True,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    header = card(ft.Row([
        back_button(lambda e: app.go(state.get("back_to", "employees"))),
        avatar_holder,
        ft.Column([
            name_v,
            sub_v,
            ft.Row([mini_caption(ft.Icons.WATCH, f'مچ‌بند {mac}'),
                    _cap(ft.Icons.BATTERY_FULL, bat_txt),
                    _cap(ft.Icons.WIFI, sig_txt)], spacing=14),
        ], spacing=3, expand=True),
        status_holder,
    ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=18)

    # ── اقدام‌ها + چیپ اتصال ──
    conn_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor=OK)
    conn_txt = txt("دریافت زنده از پل", size=12, font=FONT_MED, color=OK)
    conn_chip = ft.Container(
        content=ft.Row([conn_dot, conn_txt], spacing=6, tight=True),
        bgcolor="#E6F4EB", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
    )

    def _on_vibrate(e):
        ok, msg = send_vibrate(mac)
        if ok:
            d = live_status() or {}
            gws = d.get("gateways") or []
            if gws and not any(g.get("online") for g in gws):
                msg = "فرمان رفت، ولی گیت‌وی آفلاین است — به مچ‌بند نمی‌رسد"
        app.snack(msg if ok else f"لرزاندن نرسید — {msg}")

    def _open_edit(e):
        cur = _find_emp(live_employees()) or emp0
        open_employee_form(app, emp=cur, on_saved=_refresh_now)

    def _open_delete(e):
        cur = _find_emp(live_employees()) or emp0
        open_delete_confirm(app, cur, on_done=lambda: app.go("employees"))

    edit_btn = ft.OutlinedButton("ویرایش", icon=ft.Icons.EDIT, height=40,
                                 on_click=_open_edit,
                                 style=ft.ButtonStyle(color=INK,
                                                      shape=ft.RoundedRectangleBorder(radius=R_BTN)))
    del_btn = ft.OutlinedButton("حذف کارکن", icon=ft.Icons.PERSON_REMOVE, height=40,
                                on_click=_open_delete,
                                visible=bool(emp0.get("registered")),
                                style=ft.ButtonStyle(color=DANGER,
                                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)))

    actions = card(ft.Row([
        ft.Button("لرزاندن مچ‌بند", icon=ft.Icons.VIBRATION, height=40,
                  on_click=_on_vibrate,
                  style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                                       shape=ft.RoundedRectangleBorder(radius=R_BTN))),
        edit_btn,
        del_btn,
        ft.Container(expand=True),
        conn_chip,
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=12)

    # ── بنر مشکلات (وضعیت هشدار/اضطرار) ──
    issues_icon = ft.Icon(ft.Icons.ERROR_OUTLINE, size=18, color=WARN)
    issues_text = txt("", size=13, font=FONT_MED, color=WARN, expand=True)
    issues_banner = ft.Container(
        visible=False,
        content=ft.Row([issues_icon, issues_text], spacing=8,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor="#FCF0DC", border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )

    # ── کارت‌های حیاتی ──
    def _live_vital(label, icon, icon_bg, unit="", value_size=28):
        value = txt("—", size=value_size, font=FONT, color=INK)
        sub = txt("در انتظار داده…", size=12, font=FONT, color=TEXT_MUTED)
        kids = [ft.Row([
            ft.Container(content=ft.Icon(icon, size=18, color=INK),
                         bgcolor=icon_bg, border_radius=10,
                         padding=ft.Padding.all(8)),
            ft.Container(expand=True),
            txt(label, size=13, font=FONT_MED, color=TEXT_MUTED),
        ])]
        row_kids = [value] + ([txt(unit, size=13, font=FONT, color=TEXT_MUTED)]
                              if unit else [])
        kids.append(ft.Row(row_kids, spacing=4,
                           vertical_alignment=ft.CrossAxisAlignment.END))
        kids.append(sub)
        return card(ft.Column(kids, spacing=8), pad=16), value, sub

    hr_card, hr_value, hr_sub = _live_vital(
        "ضربان آخرین پنجره", ft.Icons.MONITOR_HEART, "#E9EBEE", "ضربه/دقیقه")
    spo2_card, spo2_value, spo2_sub = _live_vital(
        "اکسیژن خون", ft.Icons.WATER_DROP, "#E8F0FB", "٪")
    bat_card, bat_value, bat_sub = _live_vital(
        "باتری مچ‌بند", ft.Icons.BATTERY_FULL, "#E9EBEE", "٪")
    seen_card, seen_value, seen_sub = _live_vital(
        "آخرین ارتباط", ft.Icons.SCHEDULE, "#E9EBEE", value_size=22)

    vitals_row = ft.Row([
        ft.Container(expand=True, content=hr_card),
        ft.Container(expand=True, content=spo2_card),
        ft.Container(expand=True, content=bat_card),
        ft.Container(expand=True, content=seen_card),
    ], spacing=14)

    # ── نمودار ضربان آخرین پنجره ──
    chart_holder = ft.Container(height=140, alignment=ft.Alignment.BOTTOM_LEFT)
    chart_card = card(ft.Column([
        ft.Row([
            txt("ضربان قلب — آخرین پنجرهٔ اندازه‌گیری", size=15,
                font=FONT_B, color=INK),
            ft.Container(expand=True),
            txt("نمونه‌های همان پنجره — نه تاریخچهٔ روز", size=11,
                font=FONT, color=TEXT_MUTED),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        chart_holder,
    ], spacing=12), pad=18)

    def _draw_chart(health):
        bpm = (health or {}).get("bpm") or []
        if not bpm:
            chart_holder.content = ft.Container(
                height=140, alignment=ft.Alignment.CENTER,
                content=txt("هنوز اندازه‌گیری موفقی ثبت نشده — در انتظار پنجرهٔ سلامت…",
                            size=13, font=FONT, color=TEXT_MUTED))
            return
        bars = []
        for v in bpm[-30:]:
            hpx = int(8 + (min(v, 150) / 150) * 125)
            color = DANGER if v >= 110 else BAR_BLUE
            bars.append(ft.Container(
                width=10, height=hpx, bgcolor=color,
                border_radius=ft.BorderRadius.only(top_left=3, top_right=3),
                tooltip=f"{fa_num(v)} ضربه"))
        chart_holder.content = ft.Container(
            height=140, alignment=ft.Alignment.BOTTOM_LEFT,
            content=ft.Row(bars, spacing=4,
                           vertical_alignment=ft.CrossAxisAlignment.END))

    # ── حضور ──
    presence_value = txt("—", size=15, font=FONT_MED, color=TEXT_MAIN)
    presence_sub = txt("", size=12, font=FONT, color=TEXT_MUTED)
    presence_card = card(ft.Column([
        txt("وضعیت حضور", size=15, font=FONT_B, color=INK),
        presence_value,
        presence_sub,
    ], spacing=8), pad=18)

    # ── کارت صادقانه برای بخش‌های بدون دادهٔ واقعی ──
    later_card = card(ft.Column([
        txt("تاریخچهٔ حضور، ساعات کار و مکان‌ها", size=15, font=FONT_B, color=INK),
        txt("این بخش با ثبت پیوستهٔ رویدادهای گیت‌وی‌ها و راه‌اندازی گیت‌وی "
            "مناطق تکمیل می‌شود؛ تا آن زمان فقط دادهٔ واقعی همین لحظه "
            "نمایش داده می‌شود.", size=12, font=FONT, color=TEXT_MUTED),
    ], spacing=6), pad=18)

    # ── به‌روزرسانی ──
    def _apply(doc):
        if doc is None:
            conn_dot.bgcolor = OFFLINE
            conn_txt.value = "پل قطع است — دادهٔ کهنه"
            conn_txt.color = OFFLINE
            conn_chip.bgcolor = "#ECECEC"
        else:
            conn_dot.bgcolor = OK
            conn_txt.value = "دریافت زنده از پل"
            conn_txt.color = OK
            conn_chip.bgcolor = "#E6F4EB"
        e = _find_emp(doc)
        if e is None:
            return
        name = e.get("name") or "مچ‌بند ثبت‌نشده"
        name_v.value = name
        avatar_holder.content = avatar_circle(e.get("name") or "؟", r=27)
        parts = [p for p in (e.get("dept"), e.get("role")) if p]
        if e.get("shift"):
            parts.append(f'شیفت {e["shift"]}')
        sub_v.value = (" • ".join(parts) if parts
                       else "مشخصات ثبت نشده — از دکمهٔ ویرایش تکمیل کن")
        status_holder.content = status_chip(e.get("status") or "off")
        edit_btn.content = "ویرایش" if e.get("registered") else "ثبت کارکن"
        del_btn.visible = bool(e.get("registered"))

        h = e.get("health") or {}
        v = e.get("vitals") or {}

        bat = v.get("battery")
        bat_txt.value = f"باتری {fa_num(bat)}٪" if bat is not None else "باتری —"
        if e.get("present"):
            lbl, col = rssi_quality(e.get("rssi"))
            sig_txt.value = f"سیگنال {lbl}"
            sig_txt.color = col
        else:
            sig_txt.value = "سیگنال —"
            sig_txt.color = TEXT_MUTED

        issues = [ISSUE_LABELS.get(i, i) for i in (e.get("issues") or [])]
        if issues and e.get("present"):
            danger = e.get("status") == "danger"
            issues_banner.visible = True
            issues_text.value = " — ".join(issues)
            issues_text.color = DANGER if danger else WARN
            issues_icon.color = DANGER if danger else WARN
            issues_banner.bgcolor = DANGER_BG if danger else "#FCF0DC"
        else:
            issues_banner.visible = False

        if h.get("state") == "done" and h.get("n"):
            hr_value.value = fa_num(round(h.get("avg") or 0))
            hr_value.color = DANGER if e.get("status") == "danger" else INK
            last = (h.get("bpm") or [0])[-1]
            hr_sub.value = (f'{fa_num(h.get("n", 0))} نمونه — آخرین '
                            f'{fa_num(last)} — {rel_age(h.get("age_s"))}')
        elif h:
            hr_value.value = "—"
            hr_value.color = OFFLINE
            hr_sub.value = f'اندازه‌گیری ناموفق — {rel_age(h.get("age_s"))}'
        else:
            hr_value.value = "—"
            hr_value.color = INK
            hr_sub.value = "در انتظار پنجرهٔ سلامت…"

        sp = v.get("spo2")
        if sp is not None:
            spo2_value.value = fa_num(sp)
            spo2_value.color = OK if sp >= 95 else WARN
            spo2_sub.value = f'خوانده‌شده {rel_age(v.get("readings_age_s"))}'
        elif v.get("spo2_ack"):
            spo2_value.value = "—"
            spo2_value.color = WARN
            spo2_sub.value = "اندازه‌گیری انجام شد ولی قرائت معتبری نیامد"
        else:
            spo2_value.value = "—"
            spo2_value.color = INK
            spo2_sub.value = "هر چند پنجره یک‌بار اندازه‌گیری می‌شود"

        if bat is not None:
            bat_value.value = fa_num(bat)
            bat_value.color = OK if bat >= 30 else (WARN if bat >= 15 else OFFLINE)
            bat_sub.value = (f'دستگاه {v.get("dev_fw") or "—"} — '
                             f'خوانده‌شده {rel_age(v.get("age_s"))}')
        else:
            bat_value.value = "—"
            bat_value.color = OFFLINE
            bat_sub.value = "در انتظار نخستین خواندن…"

        if e.get("present"):
            seen_value.value = "اکنون"
            seen_value.color = OK
            seen_sub.value = (f'در دید {e.get("gw") or "—"}'
                              + (f' — منطقهٔ {e.get("zone")}' if e.get("zone") else ""))
        elif e.get("last_seen_age_s") is not None:
            seen_value.value = rel_age(e.get("last_seen_age_s"))
            seen_value.color = OFFLINE
            seen_sub.value = "آخرین باری که گیت‌وی دید"
        else:
            seen_value.value = "—"
            seen_value.color = INK
            seen_sub.value = "هنوز هیچ گیت‌ویی این مچ‌بند را ندیده"

        if e.get("present"):
            presence_value.value = "اکنون در دید گیت‌وی است"
            presence_value.color = OK
            rssi_txt = (fa_num(round(e.get("rssi")))
                        if e.get("rssi") is not None else "—")
            presence_sub.value = (f'گیت‌وی {e.get("gw") or "—"}'
                                  + (f' — منطقهٔ {e.get("zone")}' if e.get("zone") else "")
                                  + f' — آنتن {rssi_txt} dBm')
        else:
            presence_value.value = "خارج از دید گیت‌وی‌ها"
            presence_value.color = TEXT_MUTED
            presence_sub.value = ("آخرین ارتباط: " + rel_age(e.get("last_seen_age_s"))
                                  if e.get("last_seen_age_s") is not None
                                  else "این مچ‌بند هنوز در دید هیچ گیت‌ویی نبوده است")

        _draw_chart(h)

    def _refresh_now():
        _apply(live_employees(force=True))
        try:
            app.page.update()
        except Exception:
            pass

    async def _loop():
        while (state.get("view") == "employee" and state.get("emp") == mac
               and state.get("empd_gen") == gen):
            try:
                _apply(live_employees())
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(2)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    _apply(doc)
    return ft.Column([
        header, actions, issues_banner, vitals_row, chart_card,
        presence_card, later_card,
    ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)


def employee_detail_view(app):
    emp_id = app.state.get("emp")
    if isinstance(emp_id, str):
        return _live_detail(app, emp_id)
    emp = _find(emp_id)
    danger = emp["status"] == "danger"
    hr = emp["hr"] or 0
    series = emp["hr_series"]

    # ── سربرگ ──
    header = card(ft.Row([
        back_button(lambda e: app.go(app.state.get("back_to", "dashboard"))),
        avatar_circle(emp["name"], r=27,
                      bg="#F9D2D4" if danger else "#E9EBEE",
                      fg=DANGER if danger else TEXT_MAIN),
        ft.Column([
            txt(emp["name"], size=20, font=FONT_B, color=INK),
            txt(f'{emp["dept"]} • {emp["line"]} • شیفت {emp["shift"]}',
                size=12, font=FONT, color=TEXT_MUTED),
            ft.Row([
                mini_caption(ft.Icons.WATCH, emp["band"]),
                mini_caption(ft.Icons.BATTERY_FULL, f'{fa_num(emp["battery"])}٪ باتری'),
                mini_caption(ft.Icons.WIFI, f'سیگنال {emp["signal"]}'),
            ], spacing=14),
        ], spacing=3, expand=True),
        status_chip(emp["status"]),
    ], spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=18)

    # ── کارت حادثه ──
    incident = None
    if emp["incident_time"]:
        incident = card(ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.SOS, size=20, color=DANGER),
                txt("حادثهٔ امروز — سقوط", size=15, font=FONT_B, color=DANGER),
                ft.Container(expand=True),
                status_chip("danger"),
            ]),
            kv_row("زمان", fa_num(emp["incident_time"])),
            kv_row("مکان", emp["location"]),
            kv_row("وضعیت", "باز — در انتظار اقدام", value_color=DANGER),
            ft.Row([
                ft.Button(
                    "اعزام تیم امداد", icon=ft.Icons.MEDICAL_SERVICES, height=38,
                    style=ft.ButtonStyle(bgcolor=DANGER, color=WHITE,
                                         shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                    on_click=lambda e: app.snack("تیم امداد به محل حادثه اعزام شد"),
                ),
                ft.OutlinedButton(
                    "ثبت اقدام و بستن رویداد", height=38,
                    style=ft.ButtonStyle(color=INK,
                                         shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                    on_click=lambda e: app.snack("اقدام ثبت و رویداد بسته شد"),
                ),
            ], spacing=10),
        ], spacing=10), bg=DANGER_BG, border_color=DANGER)

    # ── علائم حیاتی ──
    vitals = ft.Row([
        ft.Container(expand=True, content=_vital_card(
            "ضربان قلب", fa_num(emp["hr"]) if emp["hr"] else "—", "ضربه/دقیقه",
            "حد مجاز: ۵۰ تا ۱۲۰", ft.Icons.MONITOR_HEART,
            DANGER if hr >= 110 else INK, "#FCE7E8" if hr >= 110 else "#E9EBEE")),
        ft.Container(expand=True, content=_vital_card(
            "اکسیژن خون", (fa_num(emp["spo2"]) + "٪") if emp["spo2"] else "—", "",
            "حداقل مجاز: ۹۲٪", ft.Icons.AIR, "#1A5FB4", "#E8F0FB")),
        ft.Container(expand=True, content=_vital_card(
            "دمای بدن", fa_num(emp["temp"]) if emp["temp"] else "—", "درجه",
            "محدودهٔ نرمال: ۳۶٫۲ تا ۳۷٫۲", ft.Icons.THERMOSTAT, INK, "#E9EBEE")),
        ft.Container(expand=True, content=_vital_card(
            "مچ‌بند", fa_num(emp["battery"]) + "٪", "باتری",
            f'آخرین ارتباط: {fa_num(emp["last_seen"])} ثانیه پیش', ft.Icons.WATCH,
            INK, "#E9EBEE")),
    ], spacing=14)

    # ── نمودار ضربان ──
    avg = None
    vals = [v for v in series if v is not None]
    if vals:
        avg = round(sum(vals) / len(vals))
    chart_card = card(ft.Column([
        ft.Row([
            txt("ضربان قلب — امروز", size=15, font=FONT_B, color=INK),
            ft.Container(expand=True),
            ft.Row([
                mini_caption(ft.Icons.CIRCLE, "بالاتر از حد", color=DANGER, size=11),
                mini_caption(ft.Icons.CIRCLE, "محدودهٔ نرمال", color=BAR_BLUE, size=11),
                txt(f'میانگین: {fa_num(avg)}' if avg else "", size=11,
                    font=FONT, color=TEXT_MUTED),
            ], spacing=14),
        ]),
        _hr_chart(series),
    ], spacing=12), pad=18)

    # ── ساعات کار و تردد ──
    week_sum = sum(h for _, h in WEEK_HOURS)
    max_h = max(h for _, h in WEEK_HOURS) or 1
    mini_bars = []
    for day, h in WEEK_HOURS:
        mini_bars.append(ft.Container(
            width=22, height=int(4 + (h / max_h) * 34),
            bgcolor=INK if h else "#E3E5E8", border_radius=4,
            tooltip=f"{day}: {fa_num(h)} ساعت",
        ))
    work_card = card(ft.Column([
        txt("ساعات کار", size=15, font=FONT_B, color=INK),
        kv_row("امروز", fa_hours(emp["work_min"]), icon=ft.Icons.SCHEDULE),
        kv_row("این هفته", f'{fa_num(week_sum)} ساعت', icon=ft.Icons.DATE_RANGE),
        kv_row("این ماه", "۱۴۳ ساعت", icon=ft.Icons.CALENDAR_MONTH),
        ft.Container(height=4),
        ft.Row(mini_bars, spacing=6, vertical_alignment=ft.CrossAxisAlignment.END),
        txt("ساعات کار روزهای هفته", size=11, font=FONT, color=TEXT_MUTED),
    ], spacing=10), pad=18)

    # ── حضور و غیاب امروز ──
    att = emp["attendance"]
    if att["exited"]:
        exit_val, exit_color = fa_num(att["exited"]), TEXT_MAIN
    elif att["status"] == "present":
        exit_val, exit_color = "اکنون در کارخانه", "#1E8E4E"
    else:
        exit_val, exit_color = "—", TEXT_MUTED
    attendance_card = card(ft.Column([
        ft.Row([
            txt("حضور و غیاب امروز", size=15, font=FONT_B, color=INK),
            ft.Container(expand=True),
            att_chip(att["status"], att["coverage"]),
        ]),
        kv_row("ساعت ورود", fa_num(att["entered"]) if att["entered"] else "—",
               icon=ft.Icons.LOGIN),
        kv_row("ساعت خروج", exit_val, value_color=exit_color, icon=ft.Icons.LOGOUT),
        kv_row("مجموع ساعات کار", fa_hours(att["work_min"]) if att["entered"] else "—",
               icon=ft.Icons.TIMER),
        kv_row("تأخیر ورود",
               f'{fa_num(att["late_min"])} دقیقه' if att["late_min"] else "ندارد",
               value_color=WARN if att["late_min"] else TEXT_MAIN,
               icon=ft.Icons.SCHEDULE),
    ], spacing=10), pad=18)

    # ── مکان‌های حضور امروز ──
    log = att["zone_log"]
    loc_head = ft.Row([
        txt("مکان‌های حضور امروز", size=15, font=FONT_B, color=INK),
        ft.Container(expand=True),
        mini_caption(ft.Icons.LOCATION_ON,
                     f'{fa_num(len(log))} جابه‌جایی' if log else "بدون داده"),
    ])
    if log:
        bar = ft.Row([
            ft.Container(
                expand=seg["minutes"], height=22, border_radius=4,
                bgcolor=ZONE_COLORS.get(seg["zone"], "#CDD2D7"),
                tooltip=f'{seg["zone"]} — {fa_num(seg["start"])} تا {fa_num(seg["end"])}',
            )
            for seg in log
        ], spacing=2)
        legend = ft.Row([
            ft.Row([
                ft.Container(width=9, height=9, border_radius=2,
                             bgcolor=ZONE_COLORS.get(zone, "#CDD2D7")),
                txt(f"{zone} — {fa_hours(mins)}", size=11, font=FONT, color=TEXT_MUTED),
            ], spacing=5, tight=True)
            for zone, mins in att["zone_totals"][:6]
        ], wrap=True, spacing=14, run_spacing=6)
        seg_rows = []
        for seg in log:
            seg_rows.append(ft.Row([
                ft.Container(width=10, height=10, border_radius=3,
                             bgcolor=ZONE_COLORS.get(seg["zone"], "#CDD2D7")),
                ft.Container(width=170, content=txt(seg["zone"], size=13, font=FONT_MED,
                                                    color=INK, max_lines=1,
                                                    overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Container(width=150, content=txt(
                    f'{fa_num(seg["start"])} تا {fa_num(seg["end"])}'
                    + (" • اکنون" if seg.get("ongoing") else ""),
                    size=12, font=FONT,
                    color="#1E8E4E" if seg.get("ongoing") else TEXT_MUTED)),
                ft.Container(width=90, content=txt(fa_hours(seg["minutes"]), size=12,
                                                   font=FONT, color=TEXT_MAIN)),
                txt(seg["gw"], size=11, font=FONT, color="#9B9FA3"),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        location_card = card(ft.Column([
            loc_head,
            bar,
            legend,
            ft.Divider(height=1, thickness=1, color=BORDER),
            *seg_rows,
        ], spacing=12), pad=18)
    else:
        msg = ("مچ‌بند خارج از پوشش گیت‌وی است — داده‌ای ثبت نشده"
               if att["status"] == "present"
               else "امروز حضور ثبتی برای این کارکن وجود ندارد")
        location_card = card(ft.Column([
            loc_head,
            ft.Container(height=46, alignment=ft.Alignment.CENTER,
                         content=txt(msg, size=13, font=FONT, color=TEXT_MUTED)),
        ], spacing=10), pad=18)

    controls = [header]
    if incident:
        controls.append(incident)
    controls += [
        vitals,
        chart_card,
        ft.Row([
            ft.Container(expand=True, content=work_card),
            ft.Container(expand=True, content=attendance_card),
        ], spacing=14),
        location_card,
    ]
    return ft.Column(controls, spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)
