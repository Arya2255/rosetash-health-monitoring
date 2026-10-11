# -*- coding: utf-8 -*-
"""تست بخش «مچ‌بندها» با دادهٔ زندهٔ شبیه‌سازی‌شده — بدون شبکه.

بررسی می‌کند که:
  - فهرست مچ‌بندها در حالت زنده از پل پر می‌شود (برچسب، مک، وضعیت دید،
    صاحب یا «بی‌صاحب») و شمارنده‌ها درست‌اند؛
  - «ثبت کارکن» فقط برای مچ‌بندهای بی‌صاحب می‌آید؛
  - در نبود پل، فهرست نمایشی با بنر «دادهٔ نمایشی» برمی‌گردد؛
  - دیالوگ‌های ثبت/ویرایش/حذف مچ‌بند بدون خطا ساخته می‌شوند.

اجرا از ریشهٔ مخزن:
    uv run python tests/test_bands_ui.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

MAC1 = "f3:b6:d6:b7:47:d7"
MAC2 = "aa:bb:cc:dd:ee:01"
MAC3 = "aa:bb:cc:dd:ee:02"


def band(mac, label=None, registered=False, in_view=False, employee=None, **kw):
    base = {
        "mac": mac, "label": label, "note": None, "registered": registered,
        "in_view": in_view, "rssi": -70 if in_view else None,
        "gw": "gw-test-1" if in_view else None,
        "zone": "test" if in_view else None,
        "last_seen": None, "last_seen_age_s": 5.0 if in_view else None,
        "employee_name": employee,
    }
    base.update(kw)
    return base


def live_doc():
    return [
        band(MAC1, "مچ‌بند سالن ۲", registered=True, in_view=True,
             employee="حمید نوری"),
        band(MAC2, registered=False, in_view=True),
        band(MAC3, "مچ‌بند رزرو", registered=True, in_view=False, note="یدکی"),
    ]


class FakePage:
    def __init__(self):
        self.dialogs = []
        self.services = []

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        pass


class FakeApp:
    def __init__(self):
        self.state = {"view": "bands", "emp": None}
        self.page = FakePage()

    def snack(self, msg):
        pass

    def go(self, view, emp=None):
        self.state["view"] = view


def texts_visible(ctrl, out=None):
    """جمع متن‌های زیرشاخه — زیرشاخه‌های visible=False نادیده گرفته می‌شوند."""
    if out is None:
        out = []
    if getattr(ctrl, "visible", None) is False:
        return out
    v = getattr(ctrl, "value", None)
    if isinstance(v, str):
        out.append(v)
    controls = getattr(ctrl, "controls", None)
    if isinstance(controls, list):
        for c in controls:
            texts_visible(c, out)
    content = getattr(ctrl, "content", None)
    if isinstance(content, str):
        out.append(content)  # برچسب دکمه‌ها — رشتهٔ ساده در content
    elif content is not None:
        texts_visible(content, out)
    return out


def labels_order(ctrl, out=None):
    """برچسب فیلدها به ترتیب پیمایش."""
    if out is None:
        out = []
    if getattr(ctrl, "visible", None) is False:
        return out
    v = getattr(ctrl, "label", None)
    if isinstance(v, str):
        out.append(v)
    controls = getattr(ctrl, "controls", None)
    if isinstance(controls, list):
        for c in controls:
            labels_order(c, out)
    content = getattr(ctrl, "content", None)
    if content is not None and not isinstance(content, str):
        labels_order(content, out)
    return out


def norm(s):
    """یکسان‌سازی مقایسه — حذف نیم‌فاصله."""
    return s.replace("\u200c", "")


import views.bands as v_bands  # noqa: E402

fails = []


def check(name, cond):
    print(("OK   — " if cond else "FAIL — ") + name)
    if not cond:
        fails.append(name)


# ── ۱) فهرست زنده ──
v_bands.live_bands = lambda force=False: live_doc()
view = v_bands.bands_view(FakeApp())
vals = norm(" || ".join(texts_visible(view)))

check("برچسب مچ‌بند", norm("مچ‌بند سالن ۲") in vals)
check("مک مچ‌بند", MAC1 in vals)
check("وضعیت در دید", norm("در دید") in vals)
check("وضعیت خارج از دید", norm("از دید خارج") in vals)
check("صاحب مچ‌بند", "حمید نوری" in vals)
check("مچ‌بند بی‌صاحب", norm("بی‌صاحب") in vals)
check("دکمهٔ ثبت کارکن برای بی‌صاحب‌ها",
      vals.count(norm("ثبت کارکن")) == 2)
check("یادداشت مچ‌بند", "یدکی" in vals)
check("شمارندهٔ فهرست", norm("۳ مچبند") in vals)
check("شمارندهٔ در دید", norm("۲ در دید") in vals)
check("شمارندهٔ ثبت‌شده", norm("۲ ثبتشده") in vals)
check("شمارندهٔ بی‌صاحب", norm("۲ بیصاحب") in vals)
check("چیپ دریافت زنده", norm("دریافت زنده از پل محلی") in vals)
check("بنر نمایشی مخفی است", norm("این فهرست دادهٔ نمایشی است") not in vals)

# ── ۲) حالت نمایشی (پل قطع) ──
v_bands.live_bands = lambda force=False: None
vals2 = norm(" || ".join(texts_visible(v_bands.bands_view(FakeApp()))))
check("بنر دادهٔ نمایشی", norm("این فهرست دادهٔ نمایشی است") in vals2)
check("فهرست نمونه", norm("مچ‌بند نمونه ۱") in vals2)
check("شمارندهٔ نمایشی", norm("۳ مچبند — نمایشی") in vals2)

# ── ۳) دیالوگ‌های ثبت/ویرایش/حذف بدون خطا ساخته می‌شوند ──
app9 = FakeApp()
v_bands.open_band_form(app9)                          # ثبت مچ‌بند تازه
v_bands.open_band_form(app9, mac=MAC1)                # پیش‌انتخاب از فهرست
v_bands.open_band_form(app9, band=live_doc()[0])      # ویرایش برچسب
v_bands.open_band_delete(app9, live_doc()[0])         # تأیید حذف
check("دیالوگ‌ها ساخته شدند", len(app9.page.dialogs) == 4)

labs9 = norm(" || ".join(labels_order(app9.page.dialogs[0])))
check("دیالوگ ثبت: فیلد مک", norm("مک مچبند") in labs9)
check("دیالوگ ثبت: فیلد برچسب", norm("نام مچبند (اختیاری)") in labs9)
d2v = norm(" || ".join(texts_visible(app9.page.dialogs[1])))
check("دیالوگ پیش‌انتخاب: مک قفل", norm(f"مچ‌بند {MAC1}") in d2v)
d4v = norm(" || ".join(texts_visible(app9.page.dialogs[3])))
check("دیالوگ حذف: نام مچ‌بند", norm("مچ‌بند سالن ۲") in d4v)

print()
print("نتیجه:", "همهٔ بررسی‌ها پاس شد" if not fails else f"{len(fails)} خطا: {fails}")
sys.exit(1 if fails else 0)
