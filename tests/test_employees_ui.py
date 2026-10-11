# -*- coding: utf-8 -*-
"""تست بخش «کارکنان» با دادهٔ زندهٔ شبیه‌سازی‌شده — بدون شبکه.

بررسی می‌کند که:
  - فهرست کارکنان در حالت زنده از دفتر پل پر می‌شود (نام، وضعیت، منطقه)،
    مچ‌بند ثبت‌نشده با دکمهٔ ثبت می‌آید و شمارنده درست است؛
  - برچسب مشکل (issues) در فهرست دیده می‌شود؛
  - در نبود پل، فهرست نمایشی با بنر «دادهٔ نمایشی» برمی‌گردد؛
  - پروفایل کارکنِ واقعی (شناسه = مک) مقادیر زنده را نشان می‌دهد؛
  - کارکن غایب «خارج از دید» و پل قطع پیام راهنما می‌دهد؛
  - فرم ثبت و دیالوگ حذف بدون خطا ساخته می‌شوند؛ فیلدهای تازه (شرکت بعد
    از نام، مچ‌بند از فهرست، سن، پروندهٔ پزشکی، عکس) هم بررسی می‌شوند؛
  - مسیر نمایشی پروفایل (شناسهٔ عددی) دست‌نخورده کار می‌کند.

اجرا از ریشهٔ مخزن:
    uv run python tests/test_employees_ui.py
"""
import os
import sys
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

MAC1 = "f3:b6:d6:b7:47:d7"
MAC2 = "aa:11:bb:22:cc:33"
MAC3 = "aa:bb:cc:dd:ee:01"

now = time.time()


def iso(ts):
    return datetime.fromtimestamp(ts).isoformat()


def emp(mac, name=None, present=False, status="off", issues=None, **kw):
    base = {
        "mac": mac, "registered": name is not None, "name": name,
        "company": "موتوسل" if name else None,
        "dept": "تولید روغن" if name else None,
        "line": "خط روغن ۲" if name else None,
        "role": "اپراتور" if name else None,
        "age": 34 if name else None,
        "shift": "صبح" if name else None, "note": "",
        "conditions": None, "medications": None, "band_label": None,
        "photo": None,
        "present": present, "rssi": -70 if present else None,
        "gw": "gw-test-1" if present else None,
        "zone": "test" if present else None,
        "last_seen": iso(now - 5) if present else None,
        "last_seen_age_s": 5.0 if present else None,
        "health": None, "vitals": None,
        "status": status, "issues": issues or [],
    }
    base.update(kw)
    return base


def live_doc():
    """دفتر نمونه: کارکن حاضر با حیاتی‌ها، کارکن غایب، و مچ‌بند ثبت‌نشده."""
    return [
        emp(MAC1, "حمید نوری", present=True, status="ok",
            conditions="فشار خون بالا", medications="آملودیپین",
            band_label="مچ‌بند سالن ۲",
            photo=f"/api/photo/{MAC1}?v=1",
            health={"state": "done", "fail": "none", "wearing": True, "ended": True,
                    "bpm": [75, 76, 77, 78], "n": 4, "avg": 76.8,
                    "ts": iso(now - 25), "age_s": 25.0},
            vitals={"battery": 90, "dev_fw": "2.0.2.3", "spo2": 99,
                    "spo2_ack": True, "hrv_ack": False, "hrv_frames": 0,
                    "ts": iso(now - 30), "age_s": 30.0, "readings_age_s": 30.0}),
        emp(MAC2, "عباس کریمی", present=False, status="off"),
        emp(MAC3, present=True, status="ok"),
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
        self.state = {"view": "employees", "emp": None, "emp_search": "",
                      "back_to": "employees"}
        self.page = FakePage()

    def snack(self, msg):
        pass

    def go(self, view, emp=None):
        self.state["view"] = view
        if view == "employee":
            self.state["emp"] = emp


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


def norm(s):
    """یکسان‌سازی مقایسه — حذف نیم‌فاصله."""
    return s.replace("\u200c", "")


def imgs(ctrl, out=None):
    """جمع نشانی عکس‌های زیرشاخه — src و تصویر آواتار."""
    if out is None:
        out = []
    if getattr(ctrl, "visible", None) is False:
        return out
    for attr in ("src", "foreground_image_src", "background_image_src"):
        v = getattr(ctrl, attr, None)
        if isinstance(v, str):
            out.append(v)
    controls = getattr(ctrl, "controls", None)
    if isinstance(controls, list):
        for c in controls:
            imgs(c, out)
    content = getattr(ctrl, "content", None)
    if content is not None and not isinstance(content, str):
        imgs(content, out)
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


def labels_order(ctrl, out=None):
    """برچسب فیلدها به ترتیب پیمایش — برای بررسی ترتیب فیلدهای فرم."""
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


import views.employees as v_emp  # noqa: E402
import views.employee_detail as v_ed  # noqa: E402
import components.employee_form as c_form  # noqa: E402

fails = []


def check(name, cond):
    print(("OK   — " if cond else "FAIL — ") + name)
    if not cond:
        fails.append(name)


# ── ۱) فهرست زنده ──
v_emp.live_employees = lambda force=False: live_doc()
app = FakeApp()
view = v_emp.employees_view(app)
vals = norm(" || ".join(texts_visible(view)))

check("نام کارکن ثبت‌شده", "حمید نوری" in vals)
check("نام کارکن غایب", "عباس کریمی" in vals)
check("چیپ وضعیت عادی", "عادی" in vals)
check("چیپ قطع اتصال (غایب)", norm("قطع اتصال") in vals)
check("ستون شیفت", norm("شیفت صبح") in vals)
check("میانگین ضربان", "۷۷" in vals)
check("منطقهٔ گیت‌وی", "test" in vals)
check("شمارندهٔ دفتر", norm("۲ کارکن ثبت‌شده") in vals)
check("شمارندهٔ ثبت‌نشده", norm("۱ مچبند ثبت‌نشده") in vals)
check("مچ‌بند ثبت‌نشده", norm("مچبند ثبت‌نشده") in vals)
check("مک مچ‌بند ثبت‌نشده", MAC3 in vals)
check("دکمهٔ ثبت روی مچ‌بند", norm("ثبت کارکن") in vals)
check("چیپ دریافت زنده", norm("دریافت زنده از پل محلی") in vals)
check("دکمهٔ افزودن کارکن", norm("افزودن کارکن") in vals)
check("شرکت در فهرست", "موتوسل" in vals)
check("عکس پرسنلی در فهرست",
      any("127.0.0.1:8726/api/photo" in s for s in imgs(view)))
check("بنر نمایشی مخفی است", norm("این فهرست دادهٔ نمایشی است") not in vals)

# ── ۲) برچسب مشکل در فهرست ──
doc2 = live_doc()
doc2[0]["status"] = "warn"
doc2[0]["issues"] = ["battery_low"]
v_emp.live_employees = lambda force=False: doc2
vals2 = norm(" || ".join(texts_visible(v_emp.employees_view(FakeApp()))))
check("برچسب مشکل شارژ باتری", norm("شارژ مچبند کم است") in vals2)
check("وضعیت هشدار", "هشدار" in vals2)

# ── ۳) حالت نمایشی (پل قطع) ──
v_emp.live_employees = lambda force=False: None
vals3 = norm(" || ".join(texts_visible(v_emp.employees_view(FakeApp()))))
check("بنر دادهٔ نمایشی", norm("این فهرست دادهٔ نمایشی است") in vals3)
check("فهرست نمونه", "یاسر کاظمی" in vals3)
check("شمارندهٔ نمایشی", norm("۲۴ کارکن") in vals3)
check("بدون دکمهٔ افزودن", norm("افزودن کارکن") not in vals3)

# ── ۴) پروفایل زنده ──
v_ed.live_employees = lambda force=False: live_doc()
app4 = FakeApp()
app4.state.update({"view": "employee", "emp": MAC1})
p4 = v_ed.employee_detail_view(app4)
pvals = norm(" || ".join(texts_visible(p4)))

check("پروفایل: نام", "حمید نوری" in pvals)
check("پروفایل: مک مچ‌بند", MAC1 in pvals)
check("پروفایل: میانگین ضربان", "۷۷" in pvals)
check("پروفایل: نمونهٔ پنجره", norm("۴ نمونه") in pvals)
check("پروفایل: اکسیژن", "۹۹" in pvals)
check("پروفایل: باتری", "۹۰" in pvals)
check("پروفایل: وضعیت عادی", "عادی" in pvals)
check("پروفایل: حضور در دید", norm("اکنون در دید گیت‌وی است") in pvals)
check("پروفایل: کارت فاز بعد", norm("تاریخچهٔ حضور") in pvals)
check("پروفایل: دکمهٔ ویرایش", norm("ویرایش") in pvals)
check("پروفایل: دکمهٔ حذف کارکن", norm("حذف کارکن") in pvals)
check("پروفایل: شرکت", "موتوسل" in pvals)
check("پروفایل: سن", norm("۳۴ ساله") in pvals)
check("پروفایل: برچسب مچ‌بند", norm("مچ‌بند «مچ‌بند سالن ۲»") in pvals)
check("پروفایل: کارت پروندهٔ پزشکی", norm("پروندهٔ پزشکی") in pvals)
check("پروفایل: بیماری زمینه‌ای", "فشار خون بالا" in pvals)
check("پروفایل: داروی خاص", "آملودیپین" in pvals)
check("پروفایل: عکس پرسنلی",
      any("127.0.0.1:8726/api/photo" in s for s in imgs(p4)))

# ── ۴ب) پروفایل مچ‌بند ثبت‌نشده: دکمهٔ ثبت، بدون دکمهٔ حذف ──
app4b = FakeApp()
app4b.state.update({"view": "employee", "emp": MAC3})
p4b = norm(" || ".join(texts_visible(v_ed.employee_detail_view(app4b))))
check("ثبت‌نشده: دکمهٔ ثبت کارکن", norm("ثبت کارکن") in p4b)
check("ثبت‌نشده: بدون دکمهٔ حذف", norm("حذف کارکن") not in p4b)
check("ثبت‌نشده: نام پیش‌فرض", norm("مچبند ثبتنشده") in p4b)

# ── ۵) پروفایل با مشکل ──
doc5 = live_doc()
doc5[0]["status"] = "danger"
doc5[0]["issues"] = ["spo2_low"]
v_ed.live_employees = lambda force=False: doc5
app5 = FakeApp()
app5.state.update({"view": "employee", "emp": MAC1})
p5 = norm(" || ".join(texts_visible(v_ed.employee_detail_view(app5))))
check("پروفایل: بنر مشکل", norm("افت اکسیژن خون") in p5)
check("پروفایل: وضعیت اضطراری", "اضطراری" in p5)

# ── ۶) پروفایل کارکن غایب ──
v_ed.live_employees = lambda force=False: live_doc()
app6 = FakeApp()
app6.state.update({"view": "employee", "emp": MAC2})
p6 = norm(" || ".join(texts_visible(v_ed.employee_detail_view(app6))))
check("غایب: خارج از دید", norm("خارج از دید گیت‌وی‌ها") in p6)
check("غایب: وضعیت قطع اتصال", norm("قطع اتصال") in p6)
check("غایب: پروندهٔ پزشکی ثبت‌نشده", norm("ثبت نشده") in p6)

# ── ۷) پل قطع در پروفایل ──
v_ed.live_employees = lambda force=False: None
app7 = FakeApp()
app7.state.update({"view": "employee", "emp": MAC1})
p7 = norm(" || ".join(texts_visible(v_ed.employee_detail_view(app7))))
check("پل قطع: پیام راهنما", norm("پل محلی در دسترس نیست") in p7)
check("پل قطع: تلاش دوباره", norm("تلاش دوباره") in p7)

# ── ۸) مسیر نمایشی پروفایل دست‌نخورده ──
v_ed.live_employees = lambda force=False: None
app8 = FakeApp()
app8.state.update({"view": "employee", "emp": 1})
p8 = norm(" || ".join(texts_visible(v_ed.employee_detail_view(app8))))
check("نمایشی: نام نمونه", "رضا محمدی" in p8)

# ── ۹) فرم ثبت/ویرایش و دیالوگ حذف — با فهرست مچ‌بند و تعاریف پایه ──
STUB_BANDS = [
    {"mac": MAC3, "label": "مچ‌بند انبار", "registered": True, "in_view": True,
     "employee_name": None},
    {"mac": "aa:bb:cc:dd:ee:09", "label": None, "registered": False,
     "in_view": True, "employee_name": None},
    {"mac": "aa:bb:cc:dd:ee:08", "label": "مچ‌بند رضا", "registered": True,
     "in_view": False, "employee_name": "رضا دیگر"},
]
STUB_CATS = {
    "company": [{"id": 1, "name": "موتوسل", "parent_id": None},
                {"id": 2, "name": "روزتاش", "parent_id": 1}],
    "unit": [{"id": 3, "name": "تولید روغن"}],
    "line": [{"id": 4, "name": "خط روغن ۲"}],
    "role": [{"id": 5, "name": "اپراتور"}],
}
app9 = FakeApp()
c_form.live_bands = lambda force=False: STUB_BANDS
c_form.live_catalogs = lambda force=False: STUB_CATS
c_form.open_employee_form(app9)                     # افزودن — انتخاب از فهرست
c_form.open_employee_form(app9, mac=MAC3)           # پیش‌انتخاب مچ‌بند در دید
c_form.open_employee_form(app9, emp=live_doc()[0])  # ویرایش کارکن موجود
c_form.open_delete_confirm(app9, live_doc()[0])     # تأیید حذف
check("دیالوگ‌ها ساخته شدند", len(app9.page.dialogs) == 4)

d9 = app9.page.dialogs[0]
d9v = norm(" || ".join(texts_visible(d9)))
opts9 = opts_text(d9)
labs9 = labels_order(d9)
check("فرم: فهرست مچ‌بند (برچسب و مک)", any("مچ‌بند انبار" in o for o in opts9))
check("فرم: مکِ مچ‌بند دیگران نیست",
      not any("aa:bb:cc:dd:ee:08" in o for o in opts9))
check("فرم: بدون ورود دستی مک", "مک مچ‌بند" not in labs9)
check("فرم: شرکت بعد از نام",
      labs9.index("نام و نام خانوادگی") < labs9.index("شرکت"))
check("فرم: فیلد سن", "سن" in labs9)
check("فرم: پروندهٔ پزشکی", norm("پروندهٔ پزشکی — اختیاری") in d9v)
check("فرم: انتخاب عکس", norm("انتخاب عکس") in d9v)
check("فرم: شرکت از فهرست (زیرشرکت)",
      any("موتوسل / روزتاش" in o for o in opts9))
check("فرم: گزینهٔ فعلی مچ‌بند", any(MAC3 in o for o in opts9))

d9c = norm(" || ".join(texts_visible(app9.page.dialogs[2])))
check("فرم ویرایش: مچ‌بند قفل", norm(f"مچ‌بند {MAC1}") in d9c)
check("فرم ویرایش: سن فعلی", "34" in d9c)

# ── ۹ب) فرم بدون پل — ورود دستی مک و فیلدهای متنی ──
c_form.live_bands = lambda force=False: None
c_form.live_catalogs = lambda force=False: None
app9b = FakeApp()
c_form.open_employee_form(app9b)
labs9b = labels_order(app9b.page.dialogs[0])
check("فرم بی‌پل: ورود دستی مک", "مک مچ‌بند" in labs9b)
check("فرم بی‌پل: شرکت متنی", "شرکت" in labs9b)
c_form.live_bands = lambda force=False: STUB_BANDS
c_form.live_catalogs = lambda force=False: STUB_CATS

print()
print("نتیجه:", "همهٔ بررسی‌ها پاس شد" if not fails else f"{len(fails)} خطا: {fails}")
sys.exit(1 if fails else 0)
