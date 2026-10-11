# -*- coding: utf-8 -*-
"""تست بخش «تعاریف پایه» — شرکت (با زیرشرکت)، واحد، خط، سمت — بدون شبکه.

بررسی می‌کند که:
  - چهار تب شرکت/واحد/خط/سمت با فهرست‌های پل پر می‌شوند؛
  - زیرشرکت با نشان «↳» و نام والد دیده می‌شود؛
  - در نبود پل، فهرست نمایشی با بنر «دادهٔ نمایشی» برمی‌گردد؛
  - دیالوگ‌های افزودن/ویرایش/حذف بدون خطا ساخته می‌شوند.

اجرا از ریشهٔ مخزن:
    uv run python tests/test_definitions_ui.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

CATS = {
    "company": [{"id": 1, "name": "موتوسل", "parent_id": None},
                {"id": 2, "name": "روزتاش", "parent_id": 1}],
    "unit": [{"id": 3, "name": "تولید"}],
    "line": [{"id": 4, "name": "خط ۱"}],
    "role": [{"id": 5, "name": "اپراتور"}],
}


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
        self.state = {"view": "definitions", "emp": None}
        self.page = FakePage()

    def snack(self, msg):
        pass

    def go(self, view, emp=None):
        self.state["view"] = view


def texts_visible(ctrl, out=None):
    """جمع متن‌های زیرشاخه — تب‌ها هم پیمایش می‌شوند."""
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
    tabs = getattr(ctrl, "tabs", None)
    if isinstance(tabs, list):
        for t in tabs:
            lb = getattr(t, "label", None)
            if isinstance(lb, str):
                out.append(lb)
            texts_visible(t, out)
    content = getattr(ctrl, "content", None)
    if isinstance(content, str):
        out.append(content)
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


def opts_text(ctrl, out=None):
    """جمع متن گزینه‌های Dropdown زیرشاخه."""
    if out is None:
        out = []
    if getattr(ctrl, "visible", None) is False:
        return out
    options = getattr(ctrl, "options", None)
    if isinstance(options, list):
        for o in options:
            t = getattr(o, "text", None)
            if isinstance(t, str):
                out.append(t)
    controls = getattr(ctrl, "controls", None)
    if isinstance(controls, list):
        for c in controls:
            opts_text(c, out)
    content = getattr(ctrl, "content", None)
    if content is not None and not isinstance(content, str):
        opts_text(content, out)
    return out


def norm(s):
    """یکسان‌سازی مقایسه — حذف نیم‌فاصله."""
    return s.replace("\u200c", "")


import views.definitions as v_defs  # noqa: E402

fails = []


def check(name, cond):
    print(("OK   — " if cond else "FAIL — ") + name)
    if not cond:
        fails.append(name)


# ── ۱) حالت زنده ──
v_defs.live_catalogs = lambda force=False: CATS
view = v_defs.definitions_view(FakeApp())
vals = norm(" || ".join(texts_visible(view)))

check("تب شرکت", "شرکت" in vals)
check("تب واحد", "واحد" in vals)
check("تب خط", "خط" in vals)
check("تب سمت", "سمت" in vals)
check("شرکت اصلی", "موتوسل" in vals)
check("زیرشرکت با نشان", norm("↳ روزتاش") in vals)
check("زیرشرکت: نام والد", norm("زیرمجموعهٔ موتوسل") in vals)
check("واحد", "تولید" in vals)
check("خط", norm("خط ۱") in vals)
check("سمت", "اپراتور" in vals)
check("شمارندهٔ کل", norm("۵ مورد — زنده") in vals)
check("دکمهٔ افزودن شرکت", norm("افزودن شرکت") in vals)
check("چیپ دریافت زنده", norm("دریافت زنده از پل محلی") in vals)
check("بنر نمایشی مخفی است", norm("این فهرست دادهٔ نمایشی است") not in vals)

# ── ۲) حالت نمایشی (پل قطع) ──
v_defs.live_catalogs = lambda force=False: None
vals2 = norm(" || ".join(texts_visible(v_defs.definitions_view(FakeApp()))))
check("بنر دادهٔ نمایشی", norm("این فهرست دادهٔ نمایشی است") in vals2)
check("نمونهٔ نمایشی", norm("پلاستیک‌سازی") in vals2)
check("شمارندهٔ نمایشی", norm("— نمایشی") in vals2)

# ── ۳) دیالوگ‌های افزودن/ویرایش/حذف بدون خطا ساخته می‌شوند ──
app3 = FakeApp()
v_defs.open_cat_form(app3, "company", companies=CATS["company"])
v_defs.open_cat_form(app3, "unit", item=CATS["unit"][0])
v_defs.open_cat_delete(app3, "company", CATS["company"][0])
check("دیالوگ‌ها ساخته شدند", len(app3.page.dialogs) == 3)

labs3 = labels_order(app3.page.dialogs[0])
check("دیالوگ شرکت: فیلد نام", norm("نام شرکت") in labs3)
check("دیالوگ شرکت: انتخاب والد", norm("زیرمجموعهٔ شرکت (اختیاری)") in labs3)
opts3 = opts_text(app3.page.dialogs[0])
check("گزینهٔ والد", any("موتوسل" in o for o in opts3))
check("والدِ خودش در گزینه‌ها نیست", len(opts3) == 1)
d3v = norm(" || ".join(texts_visible(app3.page.dialogs[2])))
check("دیالوگ حذف: نام شرکت", "موتوسل" in d3v)

print()
print("نتیجه:", "همهٔ بررسی‌ها پاس شد" if not fails else f"{len(fails)} خطا: {fails}")
sys.exit(1 if fails else 0)
