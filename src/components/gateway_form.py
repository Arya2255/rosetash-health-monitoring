# -*- coding: utf-8 -*-
"""فرم تعریف و ویرایش گیت‌وی — دیالوگ مشترک بخش «گیت‌وی‌ها» و نقشه.

ثبت در دفتر پل انجام می‌شود (backend/bridge.py — /api/gateways) و رابط
کاربری فقط از لایهٔ data استفاده می‌کند.

  - شناسهٔ گیت‌وی همان است که در config.json برد می‌آید (نمونه: gw-test-1)؛
    پس از نصب برد با همان شناسه، دادهٔ زنده خودکار به همین ردیف می‌چسبد.
  - در ثبت تازه، شناسهٔ پیشنهادی خودکار (gw-۱، gw-۲…) پیش‌فرض می‌شود و
    قابل تغییر است؛ خالی گذاشتنش هم یعنی ساخت خودکار در سرور.
  - در ویرایش، شناسه فقط برای نقاط پیشنهادی (بدون برد) قابل تغییر است؛
    نقاط نصب‌شده قفل‌اند تا با config.json برد یکی بمانند — تغییر شناسهٔ
    نصب‌شده فقط با حذف و تعریف مجدد منطقی است.
  - موقعیت روی نقشه این‌جا فقط نمایش داده می‌شود؛ جابه‌جایی با «چیدن روی
    نقشه» در صفحهٔ نقشه انجام می‌شود. «برداشتن از نقشه» پین را برمی‌دارد.
"""

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE,
    fa_num, txt,
)
from data import delete_gateway, save_gateway

KINDS = (("installed", "نصب‌شده — برد روی برق و شبکه است"),
         ("proposed", "پیشنهادی — هنوز نصب نشده"))


def _pop(app):
    try:
        app.page.pop_dialog()
    except Exception:
        pass


def _dialog(app, title, controls, error_txt, on_confirm,
            confirm_label="ثبت", confirm_color=INK):
    """بدنهٔ مشترک دیالوگ‌ها — ساخت AlertDialog و نمایش."""
    col = ft.Column([*controls, error_txt], spacing=10, tight=True)
    body = ft.Container(width=380, content=col)
    dlg = ft.AlertDialog(
        modal=True,
        title=txt(title, size=16, font=FONT_B, color=INK),
        content=body,
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


def suggest_gw_id(rows) -> str:
    """شناسهٔ پیشنهادی gw-۱، gw-۲… — کوچک‌ترین شمارهٔ بلااستفاده."""
    used = {str(r.get("gw") or "") for r in (rows or [])}
    n = 1
    while f"gw-{n}" in used:
        n += 1
    return f"gw-{n}"


def open_gateway_form(app, gw: str = "", row: dict | None = None,
                      rows=None, on_saved=None):
    """دیالوگ تعریف/ویرایش گیت‌وی.

    row ردیف موجود برای ویرایش است (شناسهٔ نصب‌شده‌ها قفل است، پیشنهادی‌ها
    قابل تغییر)؛ در ثبت تازه شناسهٔ پیشنهادی از rows حساب می‌شود.
    """
    row = row or {}
    editing = bool(row.get("gw"))
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _err(msg):
        err.value = msg
        err.visible = True
        try:
            app.page.update()
        except Exception:
            pass

    label_f = ft.TextField(label="نام نمایشی", value=row.get("label") or "",
                           text_size=13, autofocus=True,
                           hint_text="مثلاً سالن فیلتر ۲")
    zone_f = ft.TextField(label="منطقه / سالن", value=row.get("zone") or "",
                          text_size=13, hint_text="مثلاً سالن فیلتر")
    lock_id = editing and (row.get("kind") or "proposed") != "proposed"
    if editing:
        gw_f = ft.TextField(label="شناسهٔ گیت‌وی", value=row.get("gw") or "",
                            text_size=13, read_only=lock_id,
                            hint_text=(None if lock_id else
                                       "خالی = بدون تغییر"))
    else:
        gw_f = ft.TextField(label="شناسهٔ گیت‌وی",
                            value=(gw or "").strip() or suggest_gw_id(rows),
                            text_size=13,
                            hint_text="خالی = خودکار؛ نمونه: gw-filter-2")
    cur_kind = row.get("kind") or "proposed"
    kind_dd = ft.Dropdown(
        label="وضعیت", value=cur_kind, text_size=13,
        options=[ft.DropdownOption(key=k, text=t) for k, t in KINDS],
    )
    note_f = ft.TextField(label="یادداشت", value=row.get("note") or "",
                          text_size=13, multiline=True, min_lines=1,
                          max_lines=2)

    # ── موقعیت روی نقشه — فقط نمایش + برداشتن ──
    clear_pos = {"on": False}
    placed = row.get("x") is not None and row.get("y") is not None

    def _pos_text():
        if clear_pos["on"]:
            return "از نقشه برداشته می‌شود (با ثبت)"
        if not placed:
            return "هنوز روی نقشه چیده نشده — در حالت «چیدن» جاگذاری کن"
        return (f"روی نقشه: افقی {fa_num(round(row['x'] * 100))}٪، "
                f"عمودی {fa_num(round(row['y'] * 100))}٪")

    pos_lbl = txt(_pos_text(), size=11, font=FONT, color=TEXT_MUTED)

    pos_btn = None
    if placed:
        def _clear(e):
            clear_pos["on"] = True
            pos_lbl.value = _pos_text()
            pos_btn.visible = False
            try:
                app.page.update()
            except Exception:
                pass
        pos_btn = ft.TextButton("برداشتن از نقشه", icon=ft.Icons.LOCATION_OFF,
                                on_click=_clear)

    controls = [label_f, gw_f, zone_f, kind_dd,
                ft.Divider(height=1, color=BORDER), note_f, pos_lbl]
    if pos_btn is not None:
        controls.append(pos_btn)

    def _save(e):
        label = (label_f.value or "").strip()
        if not label:
            _err("نام نمایشی لازم است")
            return
        old = (row.get("gw") or "") if editing else ""
        if editing and lock_id:
            gw_val = old
        else:
            gw_val = ((gw_f.value or "").strip().lower() or old)
        renaming = bool(editing and gw_val and gw_val != old)
        if renaming:
            clash = any((r.get("gw") or "") == gw_val for r in (rows or []))
            if clash:
                _err("این شناسه همین حالا در دفتر هست — شناسهٔ دیگری بردار")
                return
        payload = {
            "gw": gw_val,
            "label": label,
            "zone": (zone_f.value or "").strip(),
            "kind": kind_dd.value or "proposed",
            "note": (note_f.value or "").strip(),
        }
        if clear_pos["on"]:
            payload["x"], payload["y"] = "", ""
        elif renaming and placed:
            # موقعیت فعلی همراه شناسهٔ تازه منتقل می‌شود
            payload["x"], payload["y"] = row["x"], row["y"]
        if renaming:
            ok, msg = delete_gateway(old)
            if not ok:
                _err(msg)
                return
        ok, msg = save_gateway(payload)
        if not ok:
            _err(msg)
            return
        _pop(app)
        app.snack("گیت‌وی به‌روز شد" if editing else "گیت‌وی ثبت شد")
        if on_saved:
            on_saved()

    return _dialog(app, "ویرایش گیت‌وی" if editing else "تعریف گیت‌وی",
                   controls, err, _save)


def open_gateway_delete(app, row: dict, on_done=None):
    """تأیید حذف گیت‌وی از دفتر — اگر دوباره دیده شود «تعریف‌نشده» می‌ماند."""
    row = row or {}
    name = (row.get("label") or row.get("gw") or "").strip()
    gid = row.get("gw") or ""
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _del(e):
        ok, msg = delete_gateway(gid)
        if not ok:
            err.value = msg
            err.visible = True
            try:
                app.page.update()
            except Exception:
                pass
            return
        _pop(app)
        app.snack("گیت‌وی از دفتر حذف شد")
        if on_done:
            on_done()

    body = txt(f"«{name}» ({gid}) از دفتر گیت‌وی‌ها حذف شود؟ اگر بردش هنوز "
               "روشن و آنلاین باشد، دوباره به‌صورت «کشف‌شده — تعریف‌نشده» "
               "در فهرست می‌آید.", size=13, font=FONT, color=TEXT_MUTED)
    return _dialog(app, "حذف گیت‌وی", [body], err, _del,
                   confirm_label="حذف", confirm_color=DANGER)