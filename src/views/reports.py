# -*- coding: utf-8 -*-
"""گزارش‌ها — ساعتی تا سالیانه، نمودار و خلاصهٔ واحدها."""

import flet as ft

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, fa_date,
    fa_num, txt,
)
from data import WEEK_HOURS, dept_summary
from layout import is_phone, table_scroll
from components.common import card


def reports_view(app):
    state = app.state
    state.setdefault("report_tab", "هفتگی")
    phone = is_phone(app)

    tabs = ["ساعتی", "روزانه", "هفتگی", "ماهانه", "سالیانه"]
    pills_map = {}

    def on_tab(name):
        state["report_tab"] = name
        for kk, (c, t_) in pills_map.items():
            active = kk == name
            c.bgcolor = INK if active else WHITE
            c.border = ft.Border.all(1, INK if active else BORDER)
            t_.color = WHITE if active else INK
        app.snack(f'گزارش «{name}» آماده شد — داده نمایشی')
        app.page.update()

    tab_controls = []
    for name in tabs:
        active = state["report_tab"] == name
        t_ = txt(name, size=13, font=FONT_MED, color=WHITE if active else INK)
        c = ft.Container(
            content=t_, padding=ft.Padding.symmetric(horizontal=14, vertical=7),
            border_radius=999, bgcolor=INK if active else WHITE,
            border=ft.Border.all(1, INK if active else BORDER),
            on_click=lambda e, n=name: on_tab(n),
        )
        pills_map[name] = (c, t_)
        tab_controls.append(c)

    unit_dd = ft.Dropdown(
        width=150 if not phone else 128, text_size=13,
        options=[ft.dropdown.Option(key="all", text="همهٔ واحدها"),
                 ft.dropdown.Option(key="oil", text="تولید روغن"),
                 ft.dropdown.Option(key="plastic", text="تولید پلاستیک"),
                 ft.dropdown.Option(key="pack", text="خط بسته‌بندی"),
                 ft.dropdown.Option(key="store", text="انبار")],
        value="all",
    )
    refresh_btn = ft.Button(
        "تهیه گزارش", icon=ft.Icons.REFRESH, height=42,
        style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=lambda e: app.snack(f'گزارش «{state["report_tab"]}» به‌روزرسانی شد'),
    )
    export_btn = ft.OutlinedButton(
        "خروجی اکسل", icon=ft.Icons.DOWNLOAD, height=42,
        style=ft.ButtonStyle(color=INK,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=lambda e: app.snack("فایل اکسل نمونه ساخته شد — در فاز ۲ به داده واقعی متصل می‌شود"),
    )
    if phone:
        # موبایل: قرص‌ها در یک ردیف می‌پیچند و فیلترها زیرشان می‌آیند
        filter_card = card(ft.Column([
            ft.Row(tab_controls, spacing=8, wrap=True, run_spacing=8),
            ft.Row([unit_dd, refresh_btn, export_btn], spacing=8,
                   wrap=True, run_spacing=8),
        ], spacing=10), pad=14)
    else:
        filter_card = card(ft.Row([
            ft.Row(tab_controls, spacing=8),
            ft.Container(expand=True),
            unit_dd,
            refresh_btn,
            export_btn,
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER), pad=14)

    # ── نمودار ساعات کار هفته ──
    today_name = fa_date().split()[0]
    bars = []
    bw = 26 if phone else 40
    for day, h in WEEK_HOURS:
        bh = max(4, int((h / 10) * 150))
        is_today = day == today_name
        bars.append(ft.Column([
            txt(f'{fa_num(h)} س', size=11, font=FONT_MED, color=TEXT_MUTED),
            ft.Container(width=bw, height=bh, border_radius=ft.BorderRadius.only(top_left=6, top_right=6),
                         bgcolor=INK if is_today else "#CDD2D7"),
            txt(day, size=11, font=FONT_MED if is_today else FONT,
                color=INK if is_today else TEXT_MUTED),
        ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER))

    chart_card = card(ft.Column([
        ft.Row([
            txt("ساعات کار — هفتهٔ جاری", size=15, font=FONT_B, color=INK),
            ft.Container(expand=True),
            txt("میانگین روزانه: ۸ س ۲۴ د", size=12, font=FONT, color=TEXT_MUTED),
        ]),
        ft.Container(
            height=215, alignment=ft.Alignment.BOTTOM_CENTER,
            content=ft.Row(bars, spacing=12 if phone else 24,
                           alignment=ft.MainAxisalignment.Alignment(0, 0),
                           vertical_alignment=ft.CrossAxisAlignment.END),
        ),
    ], spacing=14), pad=18)

    # ── خلاصهٔ واحدها ──
    def _dept_cell(text_ctrl):
        """سلول نام واحد — موبایل: عرض ثابت و کشیدن افقی."""
        if phone:
            return ft.Container(width=130, content=text_ctrl)
        return ft.Container(expand=True, content=text_ctrl)

    header = table_scroll(app, ft.Row([
        _dept_cell(txt("واحد", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=80, content=txt("نفرات", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=130, content=txt("میانگین ساعات", size=12, font=FONT_MED, color=TEXT_MUTED)),
        ft.Container(width=110, content=txt("حوادث امروز", size=12, font=FONT_MED, color=TEXT_MUTED)),
    ], spacing=10))
    rows = [header]
    for r in dept_summary():
        rows.append(ft.Container(
            content=table_scroll(app, ft.Row([
                _dept_cell(txt(r["dept"], size=13, font=FONT_MED, color=INK)),
                ft.Container(width=80, content=txt(fa_num(r["n"]), size=13, font=FONT, color=INK)),
                ft.Container(width=130, content=txt(f'{fa_num(r["avg_h"])} ساعت', size=13, font=FONT, color=INK)),
                ft.Container(width=110, content=txt(
                    fa_num(r["inc"]) if r["inc"] else "—", size=13, font=FONT_MED,
                    color="#E30613" if r["inc"] else TEXT_MUTED)),
            ], spacing=10)),
            padding=ft.Padding.symmetric(vertical=9),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        ))
    summary_card = card(ft.Column([
        txt("خلاصه به تفکیک واحد", size=15, font=FONT_B, color=INK),
        ft.Container(height=2),
        *rows,
    ], spacing=4), pad=18)

    return ft.Column([filter_card, chart_card, summary_card],
                     spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)
