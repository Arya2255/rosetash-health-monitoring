# -*- coding: utf-8 -*-
"""پروفایل کارکن — سلامت لحظه‌ای، نمودار ضربان، ساعات کار و تردد."""

import flet as ft

from theme import (
    BORDER, DANGER, DANGER_BG, FONT, FONT_B, FONT_MED, FONT_SB, INK, R_BTN,
    TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_hours, fa_num, txt,
)
from data import EMPLOYEES, WEEK_HOURS, ZONE_COLORS
from components.common import (
    att_chip, avatar_circle, back_button, card, kv_row, mini_caption, status_chip,
)

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


def employee_detail_view(app):
    emp = _find(app.state.get("emp"))
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
