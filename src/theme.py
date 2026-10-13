# -*- coding: utf-8 -*-
"""سیستم طراحی سامانه پایش سلامت کارکنان — کارخانه رزتاش (برند موتوسل)

ترکیب دو استاندارد:
- ساختار، کامپوننت و رفتار بر پایه Material Design 3
- فاصله‌گذاری، ظرافت و آرامش بصری بر پایه Apple HIG

قاعدهٔ محوری این سامانهٔ ایمنی:
«قرمز فقط و فقط برای وضعیت اضطراری»
"""

import datetime as _dt

import flet as ft

# ═══════════ رنگ‌های برند موتوسل ═══════════
BRAND_RED = "#E30613"
INK = "#1A1A1A"
WHITE = "#FFFFFF"
SURFACE = "#F5F5F5"
TEXT_MAIN = "#333333"
TEXT_MUTED = "#75797E"
BORDER = "#E5E7EA"
PAGE_BG = "#F1F2F4"

# ═══════════ رنگ‌های وضعیت ═══════════
STATUS = {
    "ok":     {"label": "عادی",      "fg": "#1E8E4E", "bg": "#E6F4EB"},
    "warn":   {"label": "هشدار",     "fg": "#B26900", "bg": "#FCF0DC"},
    "danger": {"label": "اضطراری",   "fg": WHITE,     "bg": BRAND_RED},
    "off":    {"label": "قطع اتصال", "fg": "#6F6F6F", "bg": "#ECECEC"},
}
# ═══════════ وضعیت حضور و غیاب ═══════════
ATT_STATUS = {
    "present": {"label": "حاضر",      "fg": "#1E8E4E", "bg": "#E6F4EB"},
    "left":    {"label": "خارج شده",  "fg": "#5B6B7B", "bg": "#ECEEF0"},
    "leave":   {"label": "مرخصی",     "fg": "#6B4FA0", "bg": "#EFEAF7"},
    "absent":  {"label": "غایب",      "fg": "#B26900", "bg": "#FCF0DC"},
}

OK = "#1E8E4E"
WARN = "#B26900"
DANGER = BRAND_RED
DANGER_BG = "#FCE7E8"
OFFLINE = "#6F6F6F"
INFO = "#1A5FB4"
INFO_BG = "#E8F0FB"

# نوار کناری (تیره — صنعتی)
SIDE_BG = "#16181A"
SIDE_ACTIVE = "#26292C"
SIDE_TEXT = "#E8E8E8"
SIDE_MUTED = "#8E9296"

# ═══════════ تایپوگرافی — وزیرمتن ═══════════
FONT = "Vazirmatn"
FONT_MED = "Vazirmatn Medium"
FONT_SB = "Vazirmatn SemiBold"
FONT_B = "Vazirmatn Bold"
FONT_XB = "Vazirmatn ExtraBold"

FONTS = {
    FONT: "fonts/Vazirmatn-Regular.ttf",
    FONT_MED: "fonts/Vazirmatn-Medium.ttf",
    FONT_SB: "fonts/Vazirmatn-SemiBold.ttf",
    FONT_B: "fonts/Vazirmatn-Bold.ttf",
    FONT_XB: "fonts/Vazirmatn-ExtraBold.ttf",
}

# ═══════════ فاصله‌ها و شعاع‌ها (شبکهٔ ۸) ═══════════
R_CARD = 12
R_BTN = 8
R_PILL = 999

# ═══════════ ابزار متن و اعداد ═══════════
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_num(value) -> str:
    """تبدیل اعداد لاتین به ارقام فارسی."""
    return str(value).translate(_FA_DIGITS)


def txt(value, size=15, font=FONT, color=TEXT_MAIN, **kw) -> ft.Text:
    """متن با فونت وزیرمتن و پیش‌فرض‌های سامانه."""
    return ft.Text(str(value), size=size, font_family=font, color=color, **kw)


# ═══════════ تاریخ و ساعت شمسی ═══════════
_FA_WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
_FA_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    """تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = (gy + 1) if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) \
        - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def fa_date(d: _dt.datetime = None) -> str:
    """تاریخ کامل شمسی — مثال: شنبه ۱۸ مهر ۱۴۰۵"""
    d = d or _dt.datetime.now()
    jy, jm, jd = gregorian_to_jalali(d.year, d.month, d.day)
    wd = _FA_WEEKDAYS[(d.weekday() + 2) % 7]  # شنبه = ۰
    return f"{wd} {fa_num(jd)} {_FA_MONTHS[jm - 1]} {fa_num(jy)}"


def fa_clock(d: _dt.datetime = None) -> str:
    """ساعت شمسی — مثال: ۱۷:۴۴:۰۳"""
    d = d or _dt.datetime.now()
    return fa_num(d.strftime("%H:%M:%S"))


def fa_hours(minutes: int) -> str:
    """مدت به ساعت و دقیقه — مثال: ۹ س ۲۰ د"""
    return f"{fa_num(minutes // 60)} س {fa_num(minutes % 60)} د"


def avatar_initials(name: str) -> str:
    parts = name.split()
    return parts[0][0] + "\u200c" + parts[-1][0] if len(parts) > 1 else parts[0][0]
