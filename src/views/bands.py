# -*- coding: utf-8 -*-
"""بخش «مچ‌بندها» — دفتر مچ‌بندهای شناخته‌شده، متصل به پل زنده.

مچ‌بندها از سه منبع می‌آیند: دفتر مچ‌بندها (ثبت با برچسب)، مچ‌بندهای
در دید گیت‌وی‌ها، و مچ‌بندهای تخصیص‌داده‌شده به کارکنان. از همین صفحه:
ثبت مچ‌بند تازه (مک + برچسب)، ویرایش برچسب، حذف از دفتر، و «ثبت کارکن»
برای مچ‌بندهای بی‌صاحب (فرم کارکن با همان مچ‌بند باز می‌شود).

حالت نمایشی: اگر پل در دسترس نباشد، فهرست نمونه با برچسب «دادهٔ نمایشی».
"""

import asyncio

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN, R_CARD,
    TEXT_MAIN, TEXT_MUTED, WHITE, fa_num, txt,
)
from data import delete_band, live_bands, save_band
from layout import dialog_w, is_phone, list_card, page_scroll
from components.common import SHADOW, rel_age
from components.employee_form import open_employee_form

# فهرست نمونهٔ حالت نمایشی — فقط وقتی پل در دسترس نیست
DEMO_BANDS = [
    {"mac": "f3:b6:d6:b7:47:d7", "label": "مچ‌بند نمونه ۱", "note": None,
     "registered": True, "in_view": True, "rssi": -68, "gw": "gw-test-1",
     "zone": "سالن تست", "last_seen": None, "last_seen_age_s": 4.0,
     "employee_name": "حمید نوری"},
    {"mac": "aa:11:bb:22:cc:33", "label": None, "note": None,
     "registered": False, "in_view": True, "rssi": -81, "gw": "gw-test-1",
     "zone": "سالن تست", "last_seen": None, "last_seen_age_s": 9.0,
     "employee_name": None},
    {"mac": "aa:bb:cc:dd:ee:02", "label": "مچ‌بند نمونه ۳", "note": "رزرو",
     "registered": True, "in_view": False, "rssi": None, "gw": None,
     "zone": None, "last_seen": None, "last_seen_age_s": None,
     "employee_name": None},
]


def _pop(app):
    try:
        app.page.pop_dialog()
    except Exception:
        pass


def _dialog(app, title, controls, error_txt, on_confirm,
            confirm_label="ثبت", confirm_color=INK):
    """بدنهٔ مشترک دیالوگ‌های این صفحه."""
    dlg = ft.AlertDialog(
        modal=True,
        title=txt(title, size=16, font=FONT_B, color=INK),
        content=ft.Container(
            width=dialog_w(app),
            content=ft.Column([*controls, error_txt], spacing=10, tight=True),
        ),
        actions=[
            ft.TextButton("انصراف", on_click=lambda e: _pop(app)),
            ft.Button(
                confirm_label,
                style=ft.ButtonStyle(bgcolor=confirm_color, color=WHITE,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=on_confirm,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    app.page.show_dialog(dlg)
    return dlg


def _view_chip(in_view):
    """چیپ وضعیت دید مچ‌بند — در دید / از دید خارج."""
    if in_view:
        dot_bg, bg, fg, label = OK, "#E6F4EB", OK, "در دید"
    else:
        dot_bg, bg, fg, label = OFFLINE, "#ECECEC", TEXT_MUTED, "از دید خارج"
    return ft.Container(
        content=ft.Row([
            ft.Container(width=7, height=7, border_radius=4, bgcolor=dot_bg),
            txt(label, size=12, font=FONT_MED, color=fg),
        ], spacing=6, tight=True),
        bgcolor=bg, border_radius=999,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
    )


def open_band_form(app, band: dict | None = None, mac: str = "", on_saved=None):
    """دیالوگ ثبت/ویرایش مچ‌بند در دفتر — برچسب و یادداشت اختیاری است."""
    band = band or {}
    editing = bool(band.get("mac"))
    fixed = (mac or band.get("mac") or "").strip().lower()
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _err(msg):
        err.value = msg
        err.visible = True
        try:
            app.page.update()
        except Exception:
            pass

    controls = []
    mac_f = None
    if fixed:
        controls.append(ft.Row([
            ft.Icon(ft.Icons.WATCH, size=16, color=TEXT_MUTED),
            txt(f"مچ‌بند {fixed}", size=13, font=FONT_MED, color=TEXT_MUTED),
        ], spacing=6))
    else:
        mac_f = ft.TextField(label="مک مچ‌بند", hint_text="f3:b6:d6:b7:47:d7",
                             text_size=13, autofocus=True)
        controls.append(mac_f)
    label_f = ft.TextField(label="نام مچ‌بند (اختیاری)",
                           value=band.get("label") or "", text_size=13,
                           hint_text="مثلاً مچ‌بند سالن فیلتر")
    note_f = ft.TextField(label="یادداشت (اختیاری)",
                          value=band.get("note") or "", text_size=13)
    controls += [label_f, note_f]

    def _save(e):
        mac_val = fixed or ((mac_f.value or "").strip() if mac_f else "")
        if not mac_val:
            _err("مک مچ‌بند لازم است — نمونه: f3:b6:d6:b7:47:d7")
            return
        ok, msg = save_band({"mac": mac_val,
                             "label": (label_f.value or "").strip(),
                             "note": (note_f.value or "").strip()})
        if not ok:
            _err(msg)
            return
        _pop(app)
        app.snack("مچ‌بند به‌روز شد" if editing else "مچ‌بند ثبت شد")
        if on_saved:
            on_saved()

    return _dialog(app, "ویرایش مچ‌بند" if editing else "ثبت مچ‌بند",
                   controls, err, _save)


def open_band_delete(app, band: dict, on_done=None):
    """تأیید حذف مچ‌بند از دفتر — مچ‌بند تخصیص‌دار حذف نمی‌شود."""
    band = band or {}
    mac = band.get("mac") or ""
    title = band.get("label") or mac
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _del(e):
        ok, msg = delete_band(mac)
        if not ok:
            err.value = msg
            err.visible = True
            try:
                app.page.update()
            except Exception:
                pass
            return
        _pop(app)
        app.snack("مچ‌بند از دفتر حذف شد")
        if on_done:
            on_done()

    body = txt(f"مچ‌بند «{title}» از دفتر حذف شود؟ اگر دوباره در دید گیت‌وی "
               "باشد، باز در همین فهرست ظاهر می‌شود.",
               size=13, font=FONT, color=TEXT_MUTED)
    return _dialog(app, "حذف مچ‌بند", [body], err, _del,
                   confirm_label="حذف", confirm_color=DANGER)


def bands_view(app):
    state = app.state
    phone = is_phone(app)
    gen = state.get("bands_gen", 0) + 1
    state["bands_gen"] = gen

    last = {"doc": None}
    list_holder = ft.ListView(expand=True, spacing=0)
    count_text = txt("", size=12, font=FONT, color=TEXT_MUTED)

    # ── چیپ حالت داده ──
    mode_dot = ft.Container(width=7, height=7, border_radius=4, bgcolor=OFFLINE)
    mode_txt = txt("در حال بررسی پل محلی…", size=12, font=FONT_MED,
                   color=TEXT_MUTED)
    mode_chip = ft.Container(
        content=ft.Row([mode_dot, mode_txt], spacing=6, tight=True),
        bgcolor="#F1F2F4", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=12, vertical=5),
    )

    demo_banner = ft.Container(
        visible=False,
        content=ft.Row([
            ft.Icon(ft.Icons.CLOUD_OFF, size=18, color="#B4690E"),
            txt("پل محلی در دسترس نیست — این فهرست دادهٔ نمایشی است",
                size=13, font=FONT_MED, color="#B4690E", expand=True),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor="#FCF0DC", border_radius=R_CARD,
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )

    def _refresh_now():
        _apply(live_bands(force=True))
        try:
            app.page.update()
        except Exception:
            pass

    def _register_emp(b):
        open_employee_form(app, mac=b.get("mac") or "", on_saved=_refresh_now)

    def _edit_band(b):
        open_band_form(app, band=b, on_saved=_refresh_now)

    def _delete_band(b):
        open_band_delete(app, b, on_done=_refresh_now)

    add_btn = ft.Button(
        "ثبت مچ‌بند", icon=ft.Icons.WATCH, height=40, visible=False,
        style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=lambda e: open_band_form(app, on_saved=_refresh_now),
    )

    def _band_row(b):
        mac = b.get("mac") or ""
        label = b.get("label") or ""
        title = label or f"مچ‌بند {mac}"
        sub_bits = [mac] if label else []
        if b.get("in_view"):
            rssi = b.get("rssi")
            rssi_txt = fa_num(round(rssi)) if rssi is not None else "—"
            sub_bits.append(f'{b.get("zone") or b.get("gw") or "—"} — آنتن {rssi_txt}')
        elif b.get("last_seen_age_s") is not None:
            sub_bits.append(f'آخرین دید: {rel_age(b.get("last_seen_age_s"))}')
        if b.get("note"):
            sub_bits.append(b["note"])
        sub = " — ".join(sub_bits) if sub_bits else "هنوز در دید هیچ گیت‌ویی نبوده"
        emp_name = b.get("employee_name")
        if phone:
            # موبایل: وضعیت دید و کارکن در خط دوم — ستون‌های جدا حذف می‌شوند
            head = "در دید" if b.get("in_view") else "از دید خارج"
            head += f" — {emp_name}" if emp_name else " — بی‌صاحب"
            sub = f"{head} — {sub}" if sub else head
        actions = []
        if not emp_name:
            if phone:
                actions.append(ft.IconButton(
                    ft.Icons.PERSON_ADD, tooltip="ثبت کارکن", icon_size=18,
                    icon_color=INK,
                    on_click=lambda ev, bb=b: _register_emp(bb)))
            else:
                actions.append(ft.TextButton(
                    "ثبت کارکن", icon=ft.Icons.PERSON_ADD,
                    on_click=lambda ev, bb=b: _register_emp(bb)))
        actions.append(ft.IconButton(
            ft.Icons.EDIT, tooltip="ویرایش برچسب", icon_size=18,
            icon_color=TEXT_MUTED, on_click=lambda ev, bb=b: _edit_band(bb)))
        if not emp_name:
            actions.append(ft.IconButton(
                ft.Icons.DELETE_OUTLINE, tooltip="حذف از دفتر", icon_size=18,
                icon_color=DANGER, on_click=lambda ev, bb=b: _delete_band(bb)))
        cells = [
            ft.Container(
                content=ft.Icon(ft.Icons.WATCH, size=20,
                                color=INK if b.get("registered") else TEXT_MUTED),
                bgcolor="#F1F2F4", border_radius=12,
                padding=ft.Padding.all(9)),
            ft.Column([
                txt(title, size=14, font=FONT_MED, color=INK),
                txt(sub, size=11, font=FONT, color=TEXT_MUTED,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=1, expand=True),
        ]
        if not phone:
            cells.append(ft.Container(width=110, content=_view_chip(b.get("in_view"))))
            cells.append(ft.Container(width=170, content=txt(
                emp_name or "بی‌صاحب", size=12,
                font=FONT_MED if emp_name else FONT,
                color=INK if emp_name else TEXT_MUTED,
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)))
        cells += actions
        return ft.Container(
            content=ft.Row(cells, spacing=10,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        )

    def _render():
        doc = last["doc"]
        if doc is None:
            rows = [_band_row(b) for b in DEMO_BANDS]
            list_holder.controls = rows
            count_text.value = f'{fa_num(len(DEMO_BANDS))} مچ‌بند — نمایشی'
            return
        list_holder.controls = [_band_row(b) for b in doc] or [
            ft.Container(
                height=80, alignment=ft.alignment.Alignment(0, 0),
                content=txt("هنوز مچ‌بندی شناخته نشده — با «ثبت مچ‌بند» یا "
                            "با روشن‌شدن گیت‌وی‌ها پر می‌شود",
                            size=13, font=FONT, color=TEXT_MUTED))]
        n_view = sum(1 for b in doc if b.get("in_view"))
        n_reg = sum(1 for b in doc if b.get("registered"))
        n_free = sum(1 for b in doc if not b.get("employee_name"))
        count_text.value = (f'{fa_num(len(doc))} مچ‌بند — '
                            f'{fa_num(n_view)} در دید — {fa_num(n_reg)} ثبت‌شده '
                            f'— {fa_num(n_free)} بی‌صاحب')

    def _apply(doc):
        last["doc"] = doc
        if doc is None:
            mode_dot.bgcolor = OFFLINE
            mode_txt.value = "پل محلی در دسترس نیست"
            mode_txt.color = TEXT_MUTED
            mode_chip.bgcolor = "#ECECEC"
            demo_banner.visible = True
            add_btn.visible = False
        else:
            mode_dot.bgcolor = OK
            mode_txt.value = "دریافت زنده از پل محلی"
            mode_txt.color = OK
            mode_chip.bgcolor = "#E6F4EB"
            demo_banner.visible = False
            add_btn.visible = True
        _render()

    _apply(live_bands())

    if phone:
        header = ft.Column([
            ft.Row([txt("مچ‌بندها", size=20, font=FONT_B, color=INK),
                    ft.Container(expand=True), mode_chip],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            count_text,
            ft.Row([add_btn], spacing=10),
        ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    else:
        header = ft.Row([
            txt("مچ‌بندها", size=20, font=FONT_B, color=INK),
            count_text,
            ft.Container(expand=True),
            add_btn,
            mode_chip,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    table_card = ft.Container(
        content=list_holder,
        padding=ft.Padding.symmetric(vertical=4),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        expand=True,
    )
    list_card(app, table_card, h=460)

    async def _loop():
        while state.get("view") == "bands" and state.get("bands_gen") == gen:
            try:
                _apply(live_bands())
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(2)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    return page_scroll(app, [header, demo_banner, table_card])
