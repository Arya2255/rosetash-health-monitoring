# -*- coding: utf-8 -*-
"""کمک‌های چیدمان ریسپانسیو — موبایل (نسخهٔ وب روی گوشی) تا دسکتاپ.

آستانه: عرض کمتر از PHONE_W یعنی چیدمان موبایل. عرض صفحه از page.width
خوانده می‌شود و اگر هنوز معلوم نباشد، دسکتاپ فرض می‌شود. همهٔ نماها فقط از
این کمک‌ها استفاده می‌کنند تا رفتار یکسان بماند.
"""

import flet as ft

PHONE_W = 800       # کمتر از این = چیدمان موبایل (گوشی عمودی و افقی کوچک)
DESKTOP_W = 1340    # عرض فرضی وقتی page.width هنوز گزارش نشده است


def page_w(host) -> int:
    """عرض مؤثر صفحه — نبود مقدار یعنی دسکتاپ."""
    w = getattr(getattr(host, "page", None), "width", None)
    try:
        w = float(w) if w is not None else None
    except (TypeError, ValueError):
        w = None
    return int(w) if w and w > 0 else DESKTOP_W


def is_phone(host) -> bool:
    """آیا چیدمان موبایل لازم است؟"""
    return page_w(host) < PHONE_W


def strip_expand(control):
    """expand را از کنترل برمی‌دارد — قبل از استک‌کردن در ستون موبایل."""
    if getattr(control, "expand", None):
        try:
            control.expand = None
            if isinstance(control, (ft.Container, ft.Row, ft.Column)):
                control.expand_loose = False
        except Exception:
            pass
    return control


def flow(host, controls, spacing=14, phone_spacing=None, row_kw=None):
    """ردیف روی دسکتاپ؛ ستون تمام‌عرض روی موبایل — برای ردیف‌های کارت.

    روی موبایل expandها برداشته می‌شوند تا کارت‌ها به‌جای اسکویز،
    تمام‌عرض و زیر هم بنشینند.
    """
    if not is_phone(host):
        return ft.Row(controls, spacing=spacing, **(row_kw or {}))
    for c in controls:
        strip_expand(c)
    return ft.Column(controls, spacing=(phone_spacing if phone_spacing is not None
                                        else spacing),
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def filter_row(host, pills, trailing=None, spacing=8):
    """نوار فیلتر/جستجو — موبایل: قرص‌ها می‌پیچند و کادر جستجو زیر می‌آید."""
    if not is_phone(host):
        kids = [*pills, ft.Container(expand=True)]
        if trailing is not None:
            kids.append(trailing)
        return ft.Row(kids, spacing=spacing,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)
    kids = [ft.Row(pills, wrap=True, spacing=spacing, run_spacing=spacing)]
    if trailing is not None:
        kids.append(trailing)
    return ft.Column(kids, spacing=spacing,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def table_scroll(host, row):
    """ردیف عریض جدول — روی موبایل افقی قابل‌کشیدن می‌شود."""
    if is_phone(host):
        try:
            row.scroll = ft.ScrollMode.AUTO
        except Exception:
            pass
    return row


def dialog_w(host, base=380) -> int:
    """عرض بدنهٔ دیالوگ — روی موبایل باریک‌تر تا از صفحه بیرون نزند."""
    w = page_w(host)
    if w >= PHONE_W:
        return base
    return max(240, min(base, w - 96))


def page_scroll(host, controls, spacing=14):
    """ستون ریشهٔ صفحه — روی موبایل کل صفحه اسکرول می‌خورد.

    روی دسکتاپ جدول/شبکهٔ داخلی خودش اسکرول دارد؛ روی موبایل جدول ارتفاع
    ثابت می‌گیرد و اسکرول به کل صفحه منتقل می‌شود تا همه‌چیز در دسترس باشد.
    """
    if is_phone(host):
        return ft.Column(controls, spacing=spacing, expand=True,
                         scroll=ft.ScrollMode.AUTO)
    return ft.Column(controls, spacing=spacing, expand=True)


def list_card(host, card, h=430):
    """کارت فهرست‌دار — روی موبایل ارتفاع ثابت تا اسکرولِ صفحه ممکن شود."""
    if is_phone(host):
        try:
            card.expand = None
            card.expand_loose = False
            card.height = h
        except Exception:
            pass
    return card