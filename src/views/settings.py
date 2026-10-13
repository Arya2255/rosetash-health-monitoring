# -*- coding: utf-8 -*-
"""تنظیمات — پشتیبان‌گیری، آستانه‌های هشدار، کاربران و دربارهٔ سامانه."""

import flet as ft
import applog

from theme import (
    BORDER, FONT, FONT_B, FONT_MED, INK, R_BTN, TEXT_MUTED, WHITE, txt,
)
from components.common import card, kv_row
from views.logs import export_logs  # noqa: E402
from layout import flow
from data import (
    remote_add_email, remote_down, remote_remove_email,
    remote_set_autostart, remote_setup, remote_status,
    can_backup, can_edit_map, can_manage_admins, can_manage_gateways,
    can_manage_remote, can_view_logs, get_role, list_admins,
    remove_admin, set_role, ensure_has_role, set_allowed_emails,
)
from admin_roles import DEFAULT_OWNER


def _perm_chip(label):
    return ft.Container(
        content=txt(label, size=11, font=FONT_MED, color=INK),
        bgcolor="#EFF1F3", border_radius=999,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
    )


def _role_badge(role: str):
    """برچسب نقش — ادمین اصلی یا ادمین فرعی."""
    if role == "owner":
        return _perm_chip("ادمین اصلی")
    return _perm_chip("ادمین فرعی")


def _user_row(email, role):
    """ردیف ادمین."""
    return ft.Row([
        ft.CircleAvatar(radius=15, bgcolor="#E9EBEE",
                        content=ft.Icon(ft.Icons.PERSON, size=14, color=INK)),
        ft.Column([
            txt(email, size=13, font=FONT_MED, color=INK),
            txt("ادمین اصلی" if role == "owner" else "ادمین فرعی", size=11, font=FONT, color=TEXT_MUTED),
        ], spacing=1, expand=True),
        _role_badge(role),
    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def settings_view(app):
    # نقش کاربر لاگین‌شده
    admin_email = app.state.get("admin_email", "")
    my_role = ensure_has_role(admin_email)
    is_owner = can_manage_admins(my_role)

    sections = []

    # ═══════════ بخش مدیریت ادمین‌ها — فقط ادمین اصلی ═══════════
    if is_owner:
        admins_list = list_admins()

        def _open_add_dialog(e):
            email_field = ft.TextField(
                hint_text="ایمیل ادمین جدید",
                text_size=13,
                expand=True,
            )

            add_dlg = ft.AlertDialog(
                title=txt("افزودن ادمین فرعی", size=16, font=FONT_B, color=INK),
                content=ft.Column([
                    ft.Row([email_field]),
                    txt("ادمین فرعی: دسترسی محدود — پشتیبان‌گیری، لاگ، دسترسی اینترنت و چیدن نقشه ندارد", 
                        size=11, font=FONT, color=TEXT_MUTED),
                ], spacing=12, tight=True),
                actions=[
                    ft.TextButton(
                        "انصراف",
                        on_click=lambda e: setattr(add_dlg, 'open', False) or app.page.update(),
                    ),
                    ft.Button(
                        "افزودن",
                        style=ft.ButtonStyle(
                            bgcolor=INK, color=WHITE, shape=ft.RoundedRectangleBorder(radius=R_BTN),
                        ),
                        on_click=lambda e: _add_admin(e, email_field, add_dlg),
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            app.page.overlay.append(add_dlg)
            add_dlg.open = True
            app.page.update()

        def _add_admin(e, email_field, dlg):
            email = (email_field.value or "").strip().lower()
            if not email or "@" not in email:
                app.snack("ایمیل معتبر نیست")
                return
            ok, msg = set_role(email, "viewer")
            app.snack(msg)
            if ok:
                dlg.open = False
                app.page.update()
                # به‌روزرسانی لیست ایمیل‌های مجاز در Cloudflare
                _sync_allowed_emails()
                app.render()

        def _sync_allowed_emails():
            """همگام‌سازی ایمیل‌های مجاز ورود با لیست ادمین‌ها."""
            admins = list_admins()
            emails = [a["email"] for a in admins]
            if emails:
                ok, msg = set_allowed_emails(emails)
                if not ok:
                    applog.error("همگام‌سازی ایمیل‌های مجاز: %s", msg)

        admin_rows = []
        for a in admins_list:
            email = a["email"]
            role = a["role"]
            
            # ادمین اصلی
            if email.lower() == DEFAULT_OWNER.lower():
                admin_rows.append(
                    ft.Row([
                        ft.Icon(ft.Icons.STAR, size=16, color="#FFB900"),
                        ft.Container(content=txt(email, size=13, font=FONT_MED, color=INK), expand=True),
                        _role_badge("owner"),
                        ft.IconButton(
                            ft.Icons.LOCK,
                            icon_size=16,
                            icon_color=TEXT_MUTED,
                            tooltip="ادمین اصلی — ثابت و غیرقابل تغییر",
                            disabled=True,
                        ),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                )
            else:
                # ادمین فرعی
                admin_rows.append(
                    ft.Row([
                        ft.Icon(ft.Icons.PERSON, size=16, color=INK),
                        ft.Container(content=txt(email, size=13, font=FONT, color=INK), expand=True),
                        _role_badge(role),
                        ft.IconButton(
                            ft.Icons.DELETE_OUTLINE,
                            icon_size=16,
                            icon_color="#B3261E",
                            tooltip="حذف ادمین فرعی",
                            on_click=lambda e, em=email: _remove_admin_click(e, em),
                        ),
                    ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                )

        def _remove_admin_click(e, email):
            def _do_remove(ev):
                ok, msg = remove_admin(email)
                app.snack(msg)
                if ok:
                    confirm_dlg.open = False
                    app.page.update()
                    # همگام‌سازی ایمیل‌های مجاز
                    admins = list_admins()
                    emails = [a["email"] for a in admins]
                    if emails:
                        set_allowed_emails(emails)
                    app.render()
            
            confirm_dlg = ft.AlertDialog(
                title=txt(f"حذف ادمین", size=16, font=FONT_B, color=INK),
                content=txt(f"آیا از حذف {email} مطمئن هستید؟", size=13, font=FONT, color=TEXT_MUTED),
                actions=[
                    ft.TextButton("انصراف", on_click=lambda ev: setattr(confirm_dlg, 'open', False) or app.page.update()),
                    ft.Button(
                        "حذف",
                        style=ft.ButtonStyle(bgcolor="#B3261E", color=WHITE, shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                        on_click=_do_remove,
                    ),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            app.page.overlay.append(confirm_dlg)
            confirm_dlg.open = True
            app.page.update()

        admins_card = card(ft.Column([
            txt("مدیریت ادمین‌ها", size=15, font=FONT_B, color=INK),
            txt("فقط ادمین اصلی می‌تواند ادمین‌های دیگر را اضافه، حذف یا ویرایش کند.",
                size=12, font=FONT, color=TEXT_MUTED),
            ft.Divider(height=1, color=BORDER),
            *admin_rows,
            ft.Row([
                ft.Button(
                    "افزودن ادمین", icon=ft.Icons.PERSON_ADD, height=40,
                    style=ft.ButtonStyle(
                        bgcolor=INK, color=WHITE,
                        shape=ft.RoundedRectangleBorder(radius=R_BTN),
                    ),
                    on_click=_open_add_dialog,
                ),
            ]),
        ], spacing=8), pad=18)
        sections.append(admins_card)

    # ── پشتیبان‌گیری — فقط owner ──
    if can_backup(my_role):
        backup_card = card(ft.Column([
            txt("پشتیبان‌گیری", size=15, font=FONT_B, color=INK),
            ft.Switch(label="پشتیبان‌گیری ابری روزانه", value=True,
                      on_change=lambda e: app.snack("تنظیم پشتیبان‌گیری ذخیره شد")),
            ft.Row([
                txt("ساعت اجرا", size=13, font=FONT, color=TEXT_MUTED),
                ft.Container(expand=True),
                ft.Dropdown(
                    width=120, text_size=13, value="23:00",
                    options=[ft.dropdown.Option(key="23:00", text="۲۳:۰۰"),
                             ft.dropdown.Option(key="14:00", text="۱۴:۰۰"),
                             ft.dropdown.Option(key="02:00", text="۰۲:۰۰")],
                ),
            ]),
            ft.Switch(label="پشتیبان‌گیری روی حافظهٔ USB", value=False,
                      on_change=lambda e: app.snack("تنظیم پشتیبان USB ذخیره شد")),
            ft.Row([
                ft.OutlinedButton(
                    "پشتیبان‌گیری فوری", icon=ft.Icons.CLOUD_UPLOAD, height=40,
                    style=ft.ButtonStyle(color=INK,
                                         shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                    on_click=lambda e: app.snack("نسخهٔ پشتیبان ساخته شد — نمونه"),
                ),
            ]),
            txt("آخرین نسخهٔ پشتیبان: امروز ۲۳:۰۰ — موفق", size=12, font=FONT, color=TEXT_MUTED),
        ], spacing=8), pad=18)
        sections.append(backup_card)

    # ── آستانه‌های هشدار — همه ──
    def th(label, value):
        return ft.TextField(label=label, value=value, width=132, text_size=13)

    thresholds_card = card(ft.Column([
        txt("آستانه‌های هشدار", size=15, font=FONT_B, color=INK),
        ft.Row([
            th("ضربان بالا", "120"),
            th("ضربان پایین", "50"),
            th("کمینهٔ اکسیژن (٪)", "92"),
        ], spacing=10, wrap=True, run_spacing=10),
        ft.Row([
            txt("حساسیت تشخیص سقوط", size=13, font=FONT, color=TEXT_MUTED),
            ft.Container(expand=True),
            ft.Dropdown(
                width=120, text_size=13, value="mid",
                options=[ft.dropdown.Option(key="low", text="کم"),
                         ft.dropdown.Option(key="mid", text="متوسط"),
                         ft.dropdown.Option(key="high", text="زیاد")],
            ),
        ]),
        ft.Row([
            ft.Button(
                "ذخیرهٔ آستانه‌ها", height=40,
                style=ft.ButtonStyle(bgcolor=INK, color=WHITE,
                                     shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                on_click=lambda e: app.snack("آستانه‌های هشدار ذخیره شد — نمونه"),
            ),
        ]),
        txt("اعمال روی همهٔ مچ‌بندها — تخصیص به واحد در فاز ۲", size=11,
            font=FONT, color=TEXT_MUTED),
    ], spacing=10), pad=18)
    sections.append(thresholds_card)

    # ═══════════ دسترسی از اینترنت — فقط ادمین اصلی ═══════════
    if can_manage_remote(my_role):
        rs = remote_status() or {}
        if rs.get("running") and rs.get("locked"):
            net_color = "#1E8E4E"
        elif rs.get("running"):
            net_color = "#B26900"
        else:
            net_color = "#9AA0A6"

        def _net_setup(e=None):
            ok, msg = remote_setup()
            app.snack(msg)
            app.render()

        def _net_down(e=None):
            ok, msg = remote_down()
            app.snack(msg)
            app.render()

        def _net_auto(e):
            ok, msg = remote_set_autostart(bool(e.control.value))
            app.snack(msg)

        def _net_add(e=None):
            ok, msg = remote_add_email(net_new_email.value or "")
            app.snack(msg)
            if ok:
                net_new_email.value = ""
                app.render()

        def _net_rm(addr):
            def _do(e=None):
                ok, msg = remote_remove_email(addr)
                app.snack(msg)
                app.render()
            return _do

        def _net_copy(e=None):
            url = rs.get("url") or ""
            try:
                svc = getattr(app.page, "services", None)
                if svc is not None and url:
                    clip = ft.Clipboard()
                    svc.append(clip)
                    clip.set(url)
                    app.snack("آدرس کپی شد")
                else:
                    app.snack("کپی خودکار ممکن نشد — آدرس را دستی انتخاب کن")
            except Exception:
                app.snack("کپی خودکار ممکن نشد — آدرس را دستی انتخاب کن")

        net_new_email = ft.TextField(hint_text="ایمیل ادمین", text_size=13,
                                     expand=True)

        net_email_rows = [
            ft.Row([
                ft.Icon(ft.Icons.MAIL_OUTLINE, size=16, color=INK),
                ft.Container(content=txt(addr, size=13, font=FONT, color=INK),
                             expand=True),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16,
                              icon_color="#B3261E", tooltip="حذف",
                              on_click=_net_rm(addr)),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            for addr in (rs.get("emails") or [])
        ] or [txt("هنوز ایمیلی تعریف نشده — اولین ایمیل ادمین را اضافه کن.",
                  size=12, font=FONT, color=TEXT_MUTED)]

        net_card = card(ft.Column([
            txt("دسترسی از اینترنت", size=15, font=FONT_B, color=INK),
            txt("پنل از بیرون با قفل ایمیلی کلادفلر باز می‌شود — ایمیل‌های مجاز "
                "در بخش «مدیریت ادمین‌ها» تعریف می‌شوند.",
                size=12, font=FONT, color=TEXT_MUTED),
            ft.Row([
                ft.Container(width=8, height=8, border_radius=4,
                             bgcolor=net_color),
                txt("وضعیت: " + (rs.get("label") or "—"), size=13,
                    font=FONT_MED, color=INK),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.REFRESH, icon_size=18, icon_color=INK,
                              tooltip="به‌روزرسانی",
                              on_click=lambda e: app.render()),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            txt(rs.get("detail") or "", size=11, font=FONT, color=TEXT_MUTED),
            ft.Row([
                ft.Button("راه‌اندازی و اتصال", icon=ft.Icons.LINK, height=38,
                          style=ft.ButtonStyle(
                              bgcolor=INK, color=WHITE,
                              shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                          on_click=_net_setup),
                ft.OutlinedButton("قطع اتصال", icon=ft.Icons.LINK_OFF, height=38,
                                  style=ft.ButtonStyle(
                                      color=INK,
                                      shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                                  on_click=_net_down),
            ], spacing=10, wrap=True, run_spacing=8),
            ft.Switch(label="اتصال خودکار هنگام اجرای برنامه",
                      value=bool(rs.get("auto_start")), on_change=_net_auto),
            ft.Divider(height=1, color=BORDER),
            ft.Row([
                txt("آدرس پنل:", size=12, font=FONT, color=TEXT_MUTED),
                ft.Container(content=ft.Text(rs.get("url") or "—", size=13,
                                             font_family=FONT, color=INK,
                                             selectable=True), expand=True),
                ft.IconButton(ft.Icons.COPY, icon_size=16, icon_color=INK,
                              tooltip="کپی آدرس", on_click=_net_copy),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=8), pad=18)
        sections.append(net_card)

    # ═══════════ لاگ برنامه — فقط ادمین اصلی ═══════════
    if can_view_logs(my_role):
        logs_card = card(ft.Column([
            txt("لاگ برنامه", size=15, font=FONT_B, color=INK),
            txt("رخدادها و خطاهای خود برنامه برای عیب‌یابی — دادهٔ سلامت در لاگ "
                "نوشته نمی‌شود.", size=12, font=FONT, color=TEXT_MUTED),
            ft.Row([
                ft.OutlinedButton(
                    "مشاهدهٔ لاگ", icon=ft.Icons.ARTICLE_OUTLINED, height=40,
                    style=ft.ButtonStyle(color=INK,
                                         shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                    on_click=lambda e: app.go("logs"),
                ),
                ft.OutlinedButton(
                    "خروجی zip", icon=ft.Icons.DOWNLOAD, height=40,
                    style=ft.ButtonStyle(color=INK,
                                         shape=ft.RoundedRectangleBorder(radius=R_BTN)),
                    on_click=lambda e: export_logs(app),
                ),
            ], spacing=10, wrap=True, run_spacing=8),
        ], spacing=8), pad=18)
        sections.append(logs_card)

    # ═══════════ دربارهٔ سامانه — همه ═══════════
    about_card = card(ft.Column([
        txt("دربارهٔ سامانه", size=15, font=FONT_B, color=INK),
        kv_row("نسخه", "۰٫۱ — نمونهٔ اولیهٔ رابط کاربری"),
        kv_row("برند", "موتوسل — کارخانه رزتاش"),
        kv_row("فناوری", "Flet — دسکتاپ اتاق HSE"),
        kv_row("وضعیت داده‌ها", "نمایشی — اتصال به بک‌اند در فاز ۲"),
        txt("مستندات کامل طراحی در فایل DESIGN.md مخزن پروژه", size=11,
            font=FONT, color=TEXT_MUTED),
    ], spacing=8), pad=18)
    sections.append(about_card)

    # ═══════════ چیدمان دوستونه ═══════════
    left_col = []
    right_col = []
    
    if is_owner:
        # مدیریت ادمین اول
        left_col.append(sections.pop(0) if sections else None)
    
    if can_backup(my_role):
        # پشتیبان‌گیری
        right_col.append(sections.pop(0) if sections else None)
    
    if can_manage_remote(my_role):
        # دسترسی از اینترنت
        left_col.append(sections.pop(0) if sections else None)
    
    # آستانه‌ها همیشه هست
    right_col.append(sections.pop(0) if sections else None)
    
    if can_view_logs(my_role):
        # لاگ
        left_col.append(sections.pop(0) if sections else None)
    
    # درباره
    right_col.append(sections.pop(0) if sections else None)
    
    # حذف Noneها
    left_col = [s for s in left_col if s]
    right_col = [s for s in right_col if s]

    return ft.Column([
        flow(app, [
            ft.Container(expand=True, content=ft.Column(left_col, spacing=14)),
            ft.Container(expand=True, content=ft.Column(right_col, spacing=14)),
        ], spacing=14, row_kw={"vertical_alignment": ft.CrossAxisAlignment.START}),
    ], scroll=ft.ScrollMode.AUTO, expand=True)
