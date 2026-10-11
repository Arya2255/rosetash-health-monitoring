# -*- coding: utf-8 -*-
"""بخش «تعاریف پایه» — شرکت (با زیرشرکت)، واحد، خط و سمت.

فهرست‌های پیش‌تعریف برای فرم کارکن؛ از همین صفحه افزودن، ویرایش و حذف
می‌شوند (پل — /api/catalogs). شرکت می‌تواند زیرشرکت داشته باشد: در دیالوگ،
«زیرمجموعهٔ شرکت» را انتخاب کن.

حالت نمایشی: اگر پل در دسترس نباشد، فهرست نمونه با برچسب «دادهٔ نمایشی».
"""

import asyncio

import flet as ft

from theme import (
    BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, OFFLINE, OK, R_BTN, R_CARD,
    TEXT_MUTED, WHITE, fa_num, txt,
)
from data import delete_catalog, live_catalogs, save_catalog
from components.common import SHADOW

KIND_FA = {"company": "شرکت", "unit": "واحد", "line": "خط", "role": "سمت"}
KIND_ORDER = ("company", "unit", "line", "role")

# فهرست نمونهٔ حالت نمایشی — فقط وقتی پل در دسترس نیست
DEMO_CATALOGS = {
    "company": [
        {"id": 1, "name": "موتوسل", "parent_id": None},
        {"id": 2, "name": "روزتاش", "parent_id": 1},
        {"id": 3, "name": "پلاستیک‌سازی", "parent_id": 1},
    ],
    "unit": [{"id": 4, "name": "تولید"}, {"id": 5, "name": "کنترل کیفیت"}],
    "line": [{"id": 6, "name": "خط ۱"}, {"id": 7, "name": "خط ۲"}],
    "role": [{"id": 8, "name": "اپراتور"}, {"id": 9, "name": "سرشیفت"}],
}


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


def open_cat_form(app, kind, item=None, companies=None, on_saved=None):
    """دیالوگ افزودن/ویرایش یک تعریف پایه — برای شرکت، انتخاب والد هم هست."""
    item = item or {}
    editing = bool(item.get("id"))
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _err(msg):
        err.value = msg
        err.visible = True
        try:
            app.page.update()
        except Exception:
            pass

    name_f = ft.TextField(label=f"نام {KIND_FA[kind]}",
                          value=item.get("name") or "", text_size=13,
                          autofocus=True)
    controls = [name_f]
    parent_dd = None
    if kind == "company":
        tops = [c for c in (companies or [])
                if not c.get("parent_id") and c.get("id") != item.get("id")]
        opts = [ft.DropdownOption(key=str(c["id"]), text=c["name"])
                for c in tops]
        parent_dd = ft.Dropdown(
            label="زیرمجموعهٔ شرکت (اختیاری)",
            value=(str(item["parent_id"]) if item.get("parent_id") else None),
            text_size=13, options=opts, hint_text="خالی = شرکت اصلی")
        controls.append(parent_dd)
        controls.append(txt("اگر خالی بماند، این شرکت «اصلی» است؛ وگرنه "
                            "زیرمجموعهٔ شرکت انتخاب‌شده می‌شود.",
                            size=11, font=FONT, color=TEXT_MUTED))

    def _save(e):
        name = (name_f.value or "").strip()
        if not name:
            _err("نام لازم است")
            return
        payload = {"kind": kind, "name": name}
        if editing:
            payload["id"] = item["id"]
        if parent_dd is not None:
            if parent_dd.value:
                payload["parent_id"] = parent_dd.value
            elif editing:
                payload["parent_id"] = ""  # برداشتن والد
        ok, msg = save_catalog(payload)
        if not ok:
            _err(msg)
            return
        _pop(app)
        app.snack(f"{KIND_FA[kind]} به‌روز شد" if editing
                  else f"{KIND_FA[kind]} ثبت شد")
        if on_saved:
            on_saved()

    return _dialog(app, f"ویرایش {KIND_FA[kind]}" if editing
                   else f"افزودن {KIND_FA[kind]}", controls, err, _save)


def open_cat_delete(app, kind, item, on_done=None):
    """تأیید حذف یک تعریف پایه — شرکت دارای زیرشرکت حذف نمی‌شود."""
    item = item or {}
    err = txt("", size=12, font=FONT, color=DANGER, visible=False)

    def _del(e):
        ok, msg = delete_catalog(item.get("id"))
        if not ok:
            err.value = msg
            err.visible = True
            try:
                app.page.update()
            except Exception:
                pass
            return
        _pop(app)
        app.snack(f"{KIND_FA[kind]} حذف شد")
        if on_done:
            on_done()

    body = txt(f'{KIND_FA[kind]} «{item.get("name") or ""}» حذف شود؟ کارکنانی '
               "که قبلاً این مقدار را گرفته‌اند، متن خودشان را نگه می‌دارند.",
               size=13, font=FONT, color=TEXT_MUTED)
    return _dialog(app, f'حذف {KIND_FA[kind]}', [body], err, _del,
                   confirm_label="حذف", confirm_color=DANGER)


def definitions_view(app):
    state = app.state
    gen = state.get("def_gen", 0) + 1
    state["def_gen"] = gen
    state.setdefault("def_tab", 0)

    last = {"cats": None}
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
        _apply(live_catalogs(force=True))
        try:
            app.page.update()
        except Exception:
            pass

    def _kind_of_tab():
        idx = state.get("def_tab", 0)
        idx = idx if isinstance(idx, int) and 0 <= idx < len(KIND_ORDER) else 0
        return KIND_ORDER[idx]

    def _add(e):
        kind = _kind_of_tab()
        companies = (last["cats"] or {}).get("company") or []
        open_cat_form(app, kind, companies=companies, on_saved=_refresh_now)

    def _edit(kind, it):
        companies = (last["cats"] or {}).get("company") or []
        open_cat_form(app, kind, item=it, companies=companies,
                      on_saved=_refresh_now)

    def _delete(kind, it):
        open_cat_delete(app, kind, it, on_done=_refresh_now)

    add_btn = ft.Button(
        "افزودن", icon=ft.Icons.ADD, height=40, visible=False,
        style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                             shape=ft.RoundedRectangleBorder(radius=R_BTN)),
        on_click=_add,
    )

    def _cat_row(kind, it, items):
        name = it.get("name") or ""
        is_child = kind == "company" and it.get("parent_id")
        title = f"↳ {name}" if is_child else name
        sub_bits = []
        if is_child:
            parent = next((p["name"] for p in items
                           if p.get("id") == it["parent_id"]), None)
            if parent:
                sub_bits.append(f"زیرمجموعهٔ {parent}")
        if kind == "company":
            kids = [c for c in items if c.get("parent_id") == it.get("id")]
            if kids:
                sub_bits.append(f'{fa_num(len(kids))} زیرشرکت')
        sub = " — ".join(sub_bits) if sub_bits else ""
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.BUSINESS if kind == "company" else
                        ft.Icons.LABEL_OUTLINE, size=18,
                        color=INK if not is_child else TEXT_MUTED),
                    bgcolor="#F1F2F4", border_radius=10,
                    padding=ft.Padding.all(8)),
                ft.Column([
                    txt(title, size=14, font=FONT_MED, color=INK),
                    *([txt(sub, size=11, font=FONT, color=TEXT_MUTED,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]
                      if sub else []),
                ], spacing=1, expand=True),
                ft.IconButton(ft.Icons.EDIT, tooltip="ویرایش", icon_size=18,
                              icon_color=TEXT_MUTED,
                              on_click=lambda ev, k=kind, x=it: _edit(k, x)),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="حذف",
                              icon_size=18, icon_color=DANGER,
                              on_click=lambda ev, k=kind, x=it: _delete(k, x)),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, BORDER)),
        )

    def _ordered(kind, items):
        """شرکت‌ها: والد و بعد زیرشرکت‌هایش؛ بقیه: به ترتیب نام."""
        if kind != "company":
            return items
        tops = [it for it in items if not it.get("parent_id")]
        kids = [it for it in items if it.get("parent_id")]
        out = []
        for t in tops:
            out.append(t)
            out += [k for k in kids if k.get("parent_id") == t["id"]]
        out += [k for k in kids if k not in out]
        return out

    panels = {}
    tab_headers = []
    for kind in KIND_ORDER:
        holder = ft.ListView(expand=True, spacing=0)
        panels[kind] = holder
        tab_headers.append(ft.Tab(label=KIND_FA[kind]))

    tab_bar = ft.TabBar(tabs=tab_headers)
    tab_view = ft.TabBarView(expand=True,
                             controls=[panels[k] for k in KIND_ORDER])

    def _on_tab(e):
        state["def_tab"] = e.control.selected_index or 0
        add_btn.content = f'افزودن {KIND_FA[_kind_of_tab()]}'
        try:
            app.page.update()
        except Exception:
            pass

    tabs = ft.Tabs(
        length=len(KIND_ORDER),
        selected_index=state.get("def_tab", 0),
        on_change=_on_tab,
        expand=True,
        content=ft.Column(expand=True, controls=[tab_bar, tab_view]),
    )

    def _render():
        cats = last["cats"]
        if cats is None:
            cats = DEMO_CATALOGS
        total = 0
        for kind in KIND_ORDER:
            items = [it for it in (cats.get(kind) or []) if it.get("name")]
            total += len(items)
            ordered = _ordered(kind, items)
            panels[kind].controls = ([_cat_row(kind, it, items)
                                      for it in ordered] or [
                ft.Container(
                    height=70, alignment=ft.Alignment.CENTER,
                    content=txt(f"هنوز {KIND_FA[kind]}ی تعریف نشده — با دکمهٔ "
                                "افزودن شروع کن", size=13, font=FONT,
                                color=TEXT_MUTED))])
        suffix = "نمایشی" if last["cats"] is None else "زنده"
        count_text.value = f"{fa_num(total)} مورد — {suffix}"

    def _apply(cats):
        last["cats"] = cats
        if cats is None:
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
        add_btn.content = f'افزودن {KIND_FA[_kind_of_tab()]}'
        _render()

    _apply(live_catalogs())

    header = ft.Row([
        txt("تعاریف پایه", size=20, font=FONT_B, color=INK),
        count_text,
        ft.Container(expand=True),
        add_btn,
        mode_chip,
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    table_card = ft.Container(
        content=tabs,
        padding=ft.Padding.symmetric(vertical=4),
        bgcolor=WHITE, border_radius=R_CARD,
        border=ft.Border.all(1, BORDER), shadow=SHADOW,
        expand=True,
    )

    async def _loop():
        while state.get("view") == "definitions" and state.get("def_gen") == gen:
            try:
                _apply(live_catalogs())
                app.page.update()
            except Exception:
                return
            await asyncio.sleep(3)

    if hasattr(app.page, "run_task"):
        app.page.run_task(_loop)

    return ft.Column([header, demo_banner, table_card],
                     spacing=14, expand=True)
