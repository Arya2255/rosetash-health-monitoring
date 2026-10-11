# -*- coding: utf-8 -*-
"""فرم ثبت و ویرایش کارکن — دیالوگ مشترک بخش «کارکنان» و پروفایل.

ثبت در دفتر پل انجام می‌شود (backend/bridge.py — /api/employees) و
رابط کاربری فقط از لایهٔ data استفاده می‌کند.
"""

import flet as ft

from theme import (
    DANGER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt,
)
from data import delete_employee, save_employee

SHIFTS = ("صبح", "عصر", "شب")


def _pop(app):
    try:
        app.page.pop_dialog()
    except Exception:
        pass


def _dialog(app, title, controls, error_txt, on_confirm,
            confirm_label="ثبت", confirm_color=INK):
    """بدنهٔ مشترک دیالوگ‌ها — ساخت AlertDialog و نمایش."""
    dlg = ft.AlertDialog(
        modal=True,
        title=txt(title, size=16, font=FONT_B, color=INK),
        content=ft.Container(
            width=380,
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


def open_employee_form(app, mac: str = "", emp: dict | None = None, on_saved=None):
    """دیالوگ ثبت/ویرایش کارکن.

    mac ثابت (مثلاً مچ‌بند ثبت‌نشده) → فیلد مک نمایشی و قفل است؛
    بدون mac → فیلد مک برای ثبت دستی باز می‌شود.
    """
    emp = emp or {}
    fixed_mac = (mac or emp.get("mac") or "").strip().lower()
    editing = bool(emp.get("mac"))
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _err(msg):
        err.value = msg
        err.visible = True
        try:
            app.page.update()
        except Exception:
            pass

    name_f = ft.TextField(label="نام و نام خانوادگی", value=emp.get("name") or "",
                          text_size=13, autofocus=True)
    dept_f = ft.TextField(label="واحد / دپارتمان", value=emp.get("dept") or "",
                          text_size=13)
    role_f = ft.TextField(label="خط / سمت", value=emp.get("role") or "", text_size=13)
    shift_f = ft.Dropdown(
        label="شیفت", value=emp.get("shift") or "صبح", text_size=13,
        options=[ft.DropdownOption(key=s, text=s) for s in SHIFTS],
    )
    note_f = ft.TextField(label="یادداشت", value=emp.get("note") or "", text_size=13)

    mac_f = None
    controls = []
    if fixed_mac:
        controls.append(ft.Row([
            ft.Icon(ft.Icons.WATCH, size=16, color=TEXT_MUTED),
            txt(f"مچ‌بند {fixed_mac}", size=13, font=FONT_MED, color=TEXT_MUTED),
        ], spacing=6))
    else:
        mac_f = ft.TextField(label="مک مچ‌بند", hint_text="f3:b6:d6:b7:47:d7",
                             text_size=13)
        controls.append(mac_f)
    controls += [name_f, dept_f, role_f, shift_f, note_f]

    def _save(e):
        name = (name_f.value or "").strip()
        mac_val = fixed_mac or ((mac_f.value or "").strip() if mac_f else "")
        if not name:
            _err("نام کارکن لازم است")
            return
        if not mac_val:
            _err("مک مچ‌بند لازم است — نمونه: f3:b6:d6:b7:47:d7")
            return
        ok, msg = save_employee({
            "mac": mac_val, "name": name,
            "dept": (dept_f.value or "").strip(),
            "role": (role_f.value or "").strip(),
            "shift": shift_f.value or "صبح",
            "note": (note_f.value or "").strip(),
        })
        if not ok:
            _err(msg)
            return
        _pop(app)
        app.snack("اطلاعات کارکن به‌روز شد" if editing else "کارکن ثبت شد")
        if on_saved:
            on_saved()

    return _dialog(app, "ویرایش کارکن" if editing else "ثبت کارکن",
                   controls, err, _save)


def open_delete_confirm(app, emp: dict, on_done=None):
    """تأیید حذف کارکن از دفتر — مچ‌بندش اگر در دید باشد «ثبت‌نشده» می‌شود."""
    emp = emp or {}
    name = (emp.get("name") or "").strip() or (emp.get("mac") or "")
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _del(e):
        ok, msg = delete_employee(emp.get("mac") or "")
        if not ok:
            err.value = msg
            err.visible = True
            try:
                app.page.update()
            except Exception:
                pass
            return
        _pop(app)
        app.snack("کارکن از دفتر حذف شد")
        if on_done:
            on_done()

    body = txt(f"«{name}» از دفتر کارکنان حذف شود؟ مچ‌بندش اگر در دید گیت‌وی "
               "باشد، دوباره «ثبت‌نشده» نمایش داده می‌شود.",
               size=13, font=FONT, color=TEXT_MUTED)
    return _dialog(app, "حذف کارکن", [body], err, _del,
                   confirm_label="حذف", confirm_color=DANGER)
