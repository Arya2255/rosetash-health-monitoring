# -*- coding: utf-8 -*-
"""فرم ثبت و ویرایش کارکن — دیالوگ مشترک بخش «کارکنان» و پروفایل.

ثبت در دفتر پل انجام می‌شود (backend/bridge.py — /api/employees) و
رابط کاربری فقط از لایهٔ data استفاده می‌کند.

  - مچ‌بند از فهرست مچ‌بندهای شناخته‌شدهٔ پل انتخاب می‌شود (بخش «مچ‌بندها»)
    به‌جای تایپ مک؛ اگر پل نبود یا فهرست خالی بود، ورود دستی مک می‌ماند.
  - شرکت/واحد/خط/سمت از «تعاریف پایه» می‌آیند؛ ترتیب فیلدها: نام و نام
    خانوادگی، بعد شرکت (خواستهٔ کارفرما).
  - سن از «سال تولد» شمسی حساب می‌شود — انتخاب از فهرست کشویی، بدون تایپ.
  - پروندهٔ پزشکی (بیماری‌ها، داروها) و عکس پرسنلی اختیاری‌اند؛ عکس قبل
    از ارسال با PIL کوچک می‌شود (اگر PIL نبود، همان فایل می‌رود).
"""

import base64
import datetime as _dt

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE,
    fa_num, gregorian_to_jalali, txt,
)
from data import (
    delete_employee, live_bands, live_catalogs, photo_src, save_employee,
)
from layout import dialog_w

SHIFTS = ("صبح", "عصر", "شب")
_BIRTH_YOUNGEST, _BIRTH_OLDEST = 15, 80  # بازهٔ سنی فهرست «سال تولد»
_MAX_UP = 1_200_000  # سقف پس از کوچک‌سازی — پل تا ۱.۶ مگابایت می‌پذیرد


def _pop(app):
    try:
        app.page.pop_dialog()
    except Exception:
        pass


def _jalali_year_now() -> int:
    """سال شمسی جاری — مبنای فهرست «سال تولد»."""
    d = _dt.date.today()
    return gregorian_to_jalali(d.year, d.month, d.day)[0]


def _dialog(app, title, controls, error_txt, on_confirm,
            confirm_label="ثبت", confirm_color=INK, tall=False):
    """بدنهٔ مشترک دیالوگ‌ها — ساخت AlertDialog و نمایش."""
    col = ft.Column([*controls, error_txt], spacing=10, tight=True)
    body = ft.Container(width=dialog_w(app), content=col)
    if tall:
        ph = int(getattr(app.page, "height", None) or 700)
        body.height = max(260, min(470, ph - 220))
        col.scroll = ft.ScrollMode.AUTO
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


def _mime_of(data: bytes) -> str | None:
    """نوع عکس از امضای فایل — JPG/PNG/WebP یا None."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _downscale(data: bytes) -> bytes | None:
    """کوچک‌سازی عکس پرسنلی با PIL — None یعنی ممکن نشد، همان فایل می‌رود."""
    try:
        import io

        from PIL import Image as PILImage

        im = PILImage.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((512, 512))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()
    except Exception:
        return None


def _cat_field(catalogs, kind, label, value):
    """فیلد انتخاب از تعاریف پایه — اگر فهرست خالی بود، ورود دستی ساده."""
    items = [it for it in (catalogs.get(kind) or []) if it.get("name")]
    if not items:
        return ft.TextField(label=label, value=value or "", text_size=13)
    if kind == "company":  # والدها اول، زیرشرکت‌ها بعدشان
        tops = [it for it in items if not it.get("parent_id")]
        kids = [it for it in items if it.get("parent_id")]
        ordered = []
        for t in tops:
            ordered.append(t)
            ordered += [k for k in kids if k.get("parent_id") == t["id"]]
        ordered += [k for k in kids if k not in ordered]
        items = ordered
    opts, seen = [], set()
    for it in items:
        name = it["name"]
        if name in seen:
            continue
        text = name
        if kind == "company" and it.get("parent_id"):
            parent = next((p["name"] for p in items
                           if p.get("id") == it["parent_id"]), None)
            if parent:
                text = f"{parent} / {name}"
        opts.append(ft.DropdownOption(key=name, text=text))
        seen.add(name)
    if value and value not in seen:
        opts.insert(0, ft.DropdownOption(key=value, text=f"{value} (فعلی)"))
    return ft.Dropdown(label=label, value=value or None, text_size=13,
                       options=opts)


def open_employee_form(app, mac: str = "", emp: dict | None = None, on_saved=None):
    """دیالوگ ثبت/ویرایش کارکن.

    mac فقط «پیش‌انتخاب مچ‌بند» است (مثلاً از دکمهٔ ثبت روی مچ‌بند در دید)؛
    در ثبت تازه می‌توان مچ‌بند دیگری هم از فهرست انتخاب کرد. در ویرایش،
    مچ‌بند قفل است (کلید دفتر).
    """
    emp = emp or {}
    editing = bool(emp.get("mac"))
    fixed_mac = (mac or emp.get("mac") or "").strip().lower()
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _err(msg):
        err.value = msg
        err.visible = True
        try:
            app.page.update()
        except Exception:
            pass

    def _update():
        try:
            app.page.update()
        except Exception:
            pass

    bands = live_bands()
    catalogs = live_catalogs() or {}

    # ── انتخاب مچ‌بند ──
    mac_f = None
    band_dd = None
    band_controls = []
    if editing:
        band_controls.append(ft.Row([
            ft.Icon(ft.Icons.WATCH, size=16, color=TEXT_MUTED),
            txt(f"مچ‌بند {fixed_mac}", size=13, font=FONT_MED, color=TEXT_MUTED),
        ], spacing=6))
    elif bands:
        opts, seen = [], set()
        for b in bands:
            m = b.get("mac")
            if not m or m in seen:
                continue
            if b.get("employee_name") and m != fixed_mac:
                continue  # تخصیص‌داده‌شده به کارکن دیگر
            label = b.get("label") or "مچ‌بند"
            suffix = ""
            if m == fixed_mac:
                suffix = " (انتخاب‌شده)"
            elif b.get("in_view"):
                suffix = " (در دید)"
            opts.append(ft.DropdownOption(key=m, text=f"{label} — {m}{suffix}"))
            seen.add(m)
        if fixed_mac and fixed_mac not in seen:
            opts.insert(0, ft.DropdownOption(
                key=fixed_mac, text=f"مچ‌بند — {fixed_mac} (انتخاب‌شده)"))
        band_dd = ft.Dropdown(label="مچ‌بند", value=fixed_mac or None,
                              text_size=13, options=opts,
                              hint_text="از فهرست انتخاب کن")
        band_controls.append(band_dd)
        band_controls.append(txt(
            "مچ‌بند تازه است و در فهرست نیست؟ اول در بخش «مچ‌بندها» ثبتش کن.",
            size=11, font=FONT, color=TEXT_MUTED))
    else:
        mac_f = ft.TextField(label="مک مچ‌بند", hint_text="f3:b6:d6:b7:47:d7",
                             text_size=13, value=fixed_mac or "")
        band_controls.append(mac_f)

    # ── مشخصات ──
    name_f = ft.TextField(label="نام و نام خانوادگی", value=emp.get("name") or "",
                          text_size=13, autofocus=True)
    company_f = _cat_field(catalogs, "company", "شرکت", emp.get("company"))
    jy_now = _jalali_year_now()
    year_keys = [str(y) for y in range(jy_now - _BIRTH_OLDEST,
                                       jy_now - _BIRTH_YOUNGEST + 1)]
    cur_birth = None
    if emp.get("age"):
        try:
            cand = str(int(jy_now - int(emp["age"])))
            if cand in year_keys:
                cur_birth = cand
        except (TypeError, ValueError):
            cur_birth = None
    birth_dd = ft.Dropdown(
        label="سال تولد", value=cur_birth, text_size=13,
        options=[ft.DropdownOption(key=k, text=fa_num(k)) for k in year_keys],
        hint_text="انتخاب کن")
    dept_f = _cat_field(catalogs, "unit", "واحد", emp.get("dept"))
    line_f = _cat_field(catalogs, "line", "خط", emp.get("line"))
    role_f = _cat_field(catalogs, "role", "سمت", emp.get("role"))
    shift_f = ft.Dropdown(
        label="شیفت", value=emp.get("shift") or "صبح", text_size=13,
        options=[ft.DropdownOption(key=s, text=s) for s in SHIFTS],
    )
    note_f = ft.TextField(label="یادداشت", value=emp.get("note") or "", text_size=13)

    # ── پروندهٔ پزشکی (اختیاری) ──
    sec_med = txt("پروندهٔ پزشکی — اختیاری", size=12, font=FONT_B, color=TEXT_MUTED)
    cond_f = ft.TextField(label="بیماری‌های زمینه‌ای",
                          value=emp.get("conditions") or "", text_size=13,
                          multiline=True, min_lines=1, max_lines=2,
                          hint_text="مثلاً دیابت، فشار خون")
    med_f = ft.TextField(label="داروهای خاص در حال مصرف",
                         value=emp.get("medications") or "", text_size=13,
                         multiline=True, min_lines=1, max_lines=2,
                         hint_text="مثلاً انسولین، آملودیپین")

    # ── عکس پرسنلی (اختیاری) ──
    photo_state = {"bytes": None, "mime": None, "cleared": False}
    cur_url = photo_src(emp) if editing else None
    preview_holder = ft.Container(
        width=64, height=64, border_radius=32,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        border=ft.Border.all(1, BORDER), bgcolor="#F1F2F4",
        alignment=ft.alignment.Alignment(0, 0),
    )
    rm_btn = ft.TextButton("حذف عکس", icon=ft.Icons.DELETE_OUTLINE)

    def _refresh_photo():
        if photo_state["bytes"]:
            preview_holder.content = ft.Image(
                src=base64.b64encode(photo_state["bytes"]).decode(),
                width=64, height=64, fit=ft.BoxFit.COVER)
        elif cur_url and not photo_state["cleared"]:
            preview_holder.content = ft.Image(
                src=cur_url, width=64, height=64, fit=ft.BoxFit.COVER)
        else:
            preview_holder.content = ft.Icon(
                ft.Icons.PERSON, size=26, color=TEXT_MUTED)
        rm_btn.visible = bool(photo_state["bytes"]
                              or (cur_url and not photo_state["cleared"]))

    def _on_pick_result(e: ft.FilePickerResultEvent):
        files = e.files or []
        if not files:
            return
        f = files[0]
        raw = getattr(f, "bytes", None)
        try:
            if raw:
                data = (bytes(raw) if isinstance(raw, (bytes, bytearray))
                        else base64.b64decode(str(raw)))
            else:
                with open(str(f.path or ""), "rb") as fh:
                    data = bytes(fh.read())
        except Exception:
            _err("خواندن فایل عکس ممکن نشد")
            return
        small = _downscale(data)
        if small is not None:
            data, mime = small, "image/jpeg"
        else:
            mime = _mime_of(data)
        if not mime:
            _err("فرمت عکس پشتیبانی نمی‌شود — JPG یا PNG انتخاب کن")
            return
        if len(data) > _MAX_UP:
            _err("این عکس بزرگ است — عکس کوچک‌تری انتخاب کن")
            return
        photo_state["bytes"] = data
        photo_state["mime"] = mime
        photo_state["cleared"] = False
        _refresh_photo()
        _update()

    def _pick(e):
        fp = getattr(app, "_file_picker", None)
        if fp is None:
            fp = ft.FilePicker()
            app._file_picker = fp
            try:
                app.page.services.append(fp)
            except Exception:
                pass
        fp.on_result = _on_pick_result
        try:
            fp.pick_files(dialog_title="انتخاب عکس پرسنلی",
                          allow_multiple=False,
                          file_type=ft.FilePickerFileType.IMAGE,
                          with_data=True)
        except Exception:
            _err("انتخابگر فایل در این حالت پشتیبانی نمی‌شود")

    def _remove_photo(e):
        photo_state["bytes"] = None
        photo_state["cleared"] = True
        _refresh_photo()
        _update()

    rm_btn.on_click = _remove_photo
    _refresh_photo()
    photo_block = ft.Row([
        preview_holder,
        ft.Column([
            txt("عکس پرسنلی — اختیاری", size=12, font=FONT_B, color=TEXT_MUTED),
            ft.Row([
                ft.TextButton("انتخاب عکس", icon=ft.Icons.ADD_A_PHOTO,
                              on_click=_pick),
                rm_btn,
            ], spacing=4),
        ], spacing=2),
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    controls = [photo_block, name_f, company_f, birth_dd]
    controls += band_controls
    controls += [dept_f, line_f, role_f, shift_f, note_f,
                 ft.Divider(height=1, color=BORDER), sec_med, cond_f, med_f]

    def _save(e):
        name = (name_f.value or "").strip()
        if not name:
            _err("نام کارکن لازم است")
            return
        if editing:
            mac_val = fixed_mac
        elif band_dd is not None:
            mac_val = (band_dd.value or "").strip()
        else:
            mac_val = (mac_f.value or "").strip() if mac_f else ""
        if not mac_val:
            _err("مچ‌بند انتخاب نشده — از فهرست یک مچ‌بند انتخاب کن"
                 if band_dd is not None else
                 "مک مچ‌بند لازم است — نمونه: f3:b6:d6:b7:47:d7")
            return
        age_val = ""
        if birth_dd.value and birth_dd.value in year_keys:
            age_val = str(jy_now - int(birth_dd.value))
        payload = {
            "mac": mac_val, "name": name,
            "company": (company_f.value or "").strip(),
            "age": age_val,
            "dept": (dept_f.value or "").strip(),
            "line": (line_f.value or "").strip(),
            "role": (role_f.value or "").strip(),
            "shift": shift_f.value or "صبح",
            "note": (note_f.value or "").strip(),
            "conditions": (cond_f.value or "").strip(),
            "medications": (med_f.value or "").strip(),
        }
        if photo_state["bytes"]:
            payload["photo"] = (f"data:{photo_state['mime']};base64,"
                                + base64.b64encode(photo_state["bytes"]).decode())
        elif photo_state["cleared"]:
            payload["photo"] = ""
        ok, msg = save_employee(payload)
        if not ok:
            _err(msg)
            return
        _pop(app)
        app.snack("اطلاعات کارکن به‌روز شد" if editing else "کارکن ثبت شد")
        if on_saved:
            on_saved()

    return _dialog(app, "ویرایش کارکن" if editing else "ثبت کارکن",
                   controls, err, _save, tall=True)


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
