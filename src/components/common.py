# -*- coding: utf-8 -*-
"""کامپوننت‌های مشترک رابط کاربری."""

import flet as ft

from theme import (
    ATT_STATUS, BORDER, BRAND_RED, FONT, FONT_B, FONT_MED, FONT_SB, INK,
    OFFLINE, OK, R_BTN, R_CARD, R_PILL, STATUS, TEXT_MAIN, TEXT_MUTED, WARN,
    WHITE, avatar_initials, fa_num, txt,
)
from data import photo_src  # noqa: E402 — فقط از لایهٔ داده، طبق قاعده

# سایهٔ ملایم کارت‌ها — طبق حس HIG
SHADOW = ft.BoxShadow(blur_radius=14, color="#0e000000")


def card(content, pad=16, radius=R_CARD, bg=WHITE, border_color=BORDER, **kw):
    """کارت پایه — پس‌زمینهٔ سفید، گوشهٔ گرد، سایهٔ ملایم."""
    return ft.Container(
        content=content,
        padding=pad,
        bgcolor=bg,
        border_radius=radius,
        border=ft.Border.all(1, border_color) if border_color else None,
        shadow=SHADOW,
        **kw,
    )


def status_chip(status, big=False):
    """چیپ وضعیت کارکن — عادی / هشدار / اضطراری / قطع اتصال."""
    s = STATUS[status]
    fg = s["fg"]
    dot = ft.Container(
        width=7, height=7, border_radius=4,
        bgcolor=WHITE if status == "danger" else fg,
    )
    return ft.Container(
        content=ft.Row(
            [dot, txt(s["label"], size=12, font=FONT_MED, color=fg)],
            spacing=6, tight=True,
        ),
        bgcolor=s["bg"],
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=R_PILL,
        border=ft.Border.all(1, fg if status == "danger" else "transparent"),
    )


def att_chip(status, coverage=True):
    """چیپ وضعیت حضور — حاضر / خارج شده / مرخصی / غایب."""
    s = ATT_STATUS[status]
    label = s["label"]
    if not coverage and status == "present":
        label = "حاضر — خارج از پوشش"
    fg = s["fg"]
    return ft.Container(
        content=ft.Row([
            ft.Container(width=7, height=7, border_radius=4, bgcolor=fg),
            txt(label, size=12, font=FONT_MED, color=fg),
        ], spacing=6, tight=True),
        bgcolor=s["bg"],
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=R_PILL,
    )


def stat_card(label, value, sub, icon, color, icon_bg):
    """کارت شاخص کلیدی (KPI)."""
    return card(
        ft.Column([
            ft.Row([
                ft.Container(
                    content=ft.Icon(icon, size=18, color=color),
                    bgcolor=icon_bg, border_radius=10,
                    padding=ft.Padding.all(8),
                ),
                ft.Container(expand=True),
                txt(label, size=13, font=FONT_MED, color=TEXT_MUTED),
            ]),
            txt(value, size=30, font=FONT, color=INK),
            txt(sub, size=12, font=FONT, color=TEXT_MUTED),
        ], spacing=8),
        pad=16,
    )


def pill(label, active=False, on_click=None):
    """دکمهٔ قرصی فیلتر — فعال: تیره؛ غیرفعال: سفید."""
    t = txt(label, size=13, font=FONT_MED, color=WHITE if active else TEXT_MAIN)
    c = ft.Container(
        content=t,
        padding=ft.Padding.symmetric(horizontal=14, vertical=7),
        border_radius=R_PILL,
        bgcolor=INK if active else WHITE,
        border=ft.Border.all(1, INK if active else BORDER),
        on_click=on_click,
    )
    return c, t


def section_header(title, sub=None, trailing=None):
    """عنوان بخش + توضیح + محتوای سمت چپ."""
    left = ft.Column(
        [txt(title, size=18, font=FONT_B, color=INK)]
        + ([txt(sub, size=12, font=FONT, color=TEXT_MUTED)] if sub else []),
        spacing=2,
    )
    children = [left, ft.Container(expand=True)]
    if trailing is not None:
        children.append(trailing)
    return ft.Row(children, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def avatar_circle(name, r=19, bg="#E9EBEE", fg=TEXT_MAIN):
    return ft.CircleAvatar(
        radius=r, bgcolor=bg,
        content=txt(avatar_initials(name), size=r * 0.72, font=FONT_SB, color=fg),
    )


def kv_row(label, value, value_color=TEXT_MAIN, icon=None):
    """ردیف کلید — مقدار."""
    kids = []
    if icon:
        kids.append(ft.Icon(icon, size=16, color=TEXT_MUTED))
    kids += [txt(label, size=13, font=FONT, color=TEXT_MUTED),
             ft.Container(expand=True),
             txt(value, size=13, font=FONT_MED, color=value_color)]
    return ft.Row(kids, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def mini_caption(icon, text, color=TEXT_MUTED, size=12):
    return ft.Row(
        [ft.Icon(icon, size=15, color=color), txt(text, size=size, font=FONT, color=color)],
        spacing=5, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def back_button(on_click):
    """دکمهٔ بازگشت — در چیدمان راست‌به‌چپ جهت فلش خودکار آینه می‌شود."""
    return ft.IconButton(
        ft.Icons.ARROW_BACK, on_click=on_click,
        icon_color=INK, tooltip="بازگشت",
        style=ft.ButtonStyle(bgcolor=WHITE, shape=ft.RoundedRectangleBorder(radius=R_BTN)),
    )


# ═══════════ کمک‌های بخش «کارکنان» — دادهٔ زندهٔ پل ═══════════

# برچسب فارسی کدهای مشکل — خروجی issues پل (backend/bridge.py)
ISSUE_LABELS = {
    "hr_high": "ضربان بالاتر از حد مجاز",
    "hr_low": "ضربان پایین‌تر از حد مجاز",
    "spo2_low": "افت اکسیژن خون",
    "battery_low": "شارژ مچ‌بند کم است",
    "measure_fail": "اندازه‌گیری ضربان ناموفق بود",
    "not_wearing": "مچ‌بند روی دست نیست",
}


def rel_age(seconds):
    """سن رؤیت به متن کوتاه — «۷ ثانیه پیش»."""
    if seconds is None:
        return "—"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{fa_num(seconds)} ثانیه پیش"
    if seconds < 3600:
        return f"{fa_num(seconds // 60)} دقیقه پیش"
    return f"{fa_num(seconds // 3600)} ساعت پیش"


def rssi_quality(rssi):
    """کیفیت سیگنال مچ‌بند از RSSI — (برچسب، رنگ)."""
    if rssi is None:
        return "—", TEXT_MUTED
    if rssi >= -75:
        return "خوب", OK
    if rssi >= -85:
        return "متوسط", WARN
    return "ضعیف", OFFLINE


def person_avatar(emp, r=19, fallback_bg="#E9EBEE", fg=TEXT_MAIN):
    """آواتار کارکن — عکس پرسنلی اگر باشد، وگرنه حرف اول نام.

    emp دیکشنری کارکن از پل است (فیلد photo نشانی نسبی پل)؛ اگر رشتهٔ ساده
    داده شود فقط دایرهٔ حرف اول ساخته می‌شود.
    """
    if isinstance(emp, dict):
        url = photo_src(emp)
        if url:
            return ft.CircleAvatar(radius=r, foreground_image_src=url)
        name = emp.get("name")
    else:
        name = emp
    return avatar_circle(name or "؟", r=r, bg=fallback_bg, fg=fg)
