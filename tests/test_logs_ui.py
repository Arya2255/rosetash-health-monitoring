# -*- coding: utf-8 -*-
"""تست صفحهٔ «لاگ برنامه» — رندر، فیلتر سطح، جستجو و خروجی zip.

بدون پنجره و بدون شبکه؛ لاگ در پوشهٔ موقت ساخته می‌شود و صفحه از همان
می‌خواند (ROZTASH_LOG_DIR).

اجرا از ریشهٔ مخزن:
    uv run python tests/test_logs_ui.py
"""
import os
import sys
import tempfile
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

TMP = tempfile.mkdtemp(prefix="roztash-logs-ui-")
os.environ["ROZTASH_LOG_DIR"] = TMP

import applog  # noqa: E402
import views.logs as v_logs  # noqa: E402

fails = []


def check(name, cond):
    print(("OK   — " if cond else "FAIL — ") + name)
    if not cond:
        fails.append(name)


def norm(s):
    """یکسان‌سازی مقایسه — حذف نیم‌فاصله."""
    return s.replace("\u200c", "")


class FakePage:
    def __init__(self):
        self.overlay = []
        self.dialogs = []
        self.width = None
        self.height = 800
        self.tasks = []

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        pass

    def run_task(self, fn):
        self.tasks.append(fn)


class FakeApp:
    def __init__(self):
        self.page = FakePage()
        self.state = {"view": "logs"}
        self.snacks = []

    def snack(self, msg):
        self.snacks.append(msg)

    def go(self, view, emp=None):
        self.state["view"] = view


def texts(ctrl, out=None):
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
            texts(c, out)
    content = getattr(ctrl, "content", None)
    if isinstance(content, str):
        out.append(content)          # برچسب دکمه‌ها — رشتهٔ ساده در content
    elif content is not None:
        texts(content, out)
    return out


# ── دادهٔ آزمایشی: یک سشن با سه سطح ──
applog.setup(directory=TMP, force=True)
applog.info("رخداد اطلاعاتی نمونه")
applog.warn("رخداد هشدار نمونه")
applog.error("رخداد خطای نمونه")
applog.close()


def find_back(ctrl):
    """دکمهٔ بازگشت در درخت — IconButton با tooltip «بازگشت»."""
    if getattr(ctrl, "tooltip", None) == "بازگشت":
        return ctrl
    for c in (getattr(ctrl, "controls", None) or []):
        r = find_back(c)
        if r is not None:
            return r
    content = getattr(ctrl, "content", None)
    if content is not None and not isinstance(content, str):
        return find_back(content)
    return None


# ── ۱) رندر پایه ──
app = FakeApp()
view = v_logs.logs_view(app)
vals = norm(" || ".join(texts(view)))
check("عنوان صفحه", norm("لاگ برنامه") in vals)
check("سطر اطلاعاتی دیده می‌شود", norm("رخداد اطلاعاتی نمونه") in vals)
check("سطر هشدار دیده می‌شود", norm("رخداد هشدار نمونه") in vals)
check("سطر خطا دیده می‌شود", norm("رخداد خطای نمونه") in vals)
check("برچسب سطح خطا", norm("خطا") in vals)
check("دکمهٔ خروجی zip", norm("خروجی zip") in vals)
_back = find_back(view)
check("دکمهٔ بازگشت وجود دارد", _back is not None)
if _back is not None:
    _back.on_click(None)
check("بازگشت به تنظیمات", app.state["view"] == "settings")
check("مسیر پوشهٔ لاگ دیده می‌شود", TMP in vals or norm("پوشهٔ لاگ") in vals)
check("شمارندهٔ خطوط", norm("خط — تازه") in vals)
check("کار در پس‌زمینه ثبت شد (به‌روزرسانی خودکار)", len(app.page.tasks) == 1)

# ── ۲) فیلتر سطح: فقط خطا ──
app.state["logs_level"] = "error"
vals_err = norm(" || ".join(texts(v_logs.logs_view(app))))
check("فیلتر خطا: خطا می‌ماند", norm("رخداد خطای نمونه") in vals_err)
check("فیلتر خطا: هشدار حذف می‌شود", norm("رخداد هشدار نمونه") not in vals_err)
check("فیلتر خطا: اطلاعاتی حذف می‌شود",
      norm("رخداد اطلاعاتی نمونه") not in vals_err)

# ── ۳) فیلتر سطح: هشدار (هشدار + خطا) ──
app.state["logs_level"] = "warn"
vals_warn = norm(" || ".join(texts(v_logs.logs_view(app))))
check("فیلتر هشدار: هشدار می‌ماند", norm("رخداد هشدار نمونه") in vals_warn)
check("فیلتر هشدار: خطا می‌ماند", norm("رخداد خطای نمونه") in vals_warn)
check("فیلتر هشدار: اطلاعاتی حذف می‌شود",
      norm("رخداد اطلاعاتی نمونه") not in vals_warn)

# ── ۴) حالت بدون نتیجه ──
app.state["logs_level"] = "all"
app.state["logs_search"] = "چیزی که نیست"
vals_empty = norm(" || ".join(texts(v_logs.logs_view(app))))
check("پیام نبود نتیجه", norm("چیزی با این فیلتر/جستجو پیدا نشد") in vals_empty)

# ── ۵) جستجو ──
app.state["logs_search"] = "هشدار نمونه"
vals_s = norm(" || ".join(texts(v_logs.logs_view(app))))
check("جستجو: سطر هشدار می‌ماند", norm("رخداد هشدار نمونه") in vals_s)
check("جستجو: سطر خطا حذف می‌شود", norm("رخداد خطای نمونه") not in vals_s)

# ── ۶) بستهٔ خالی: پیام راهنما ──
tmp_empty = tempfile.mkdtemp(prefix="roztash-logs-ui-empty-")
os.environ["ROZTASH_LOG_DIR"] = tmp_empty
vals_e = norm(" || ".join(texts(v_logs.logs_view(FakeApp()))))
check("پوشهٔ خالی: پیام راهنما", norm("هنوز خطی در لاگ ثبت نشده") in vals_e)
os.environ["ROZTASH_LOG_DIR"] = TMP

# ── ۷) خروجی zip از صفحه ──
app2 = FakeApp()
zp = v_logs.export_logs(app2)
check("خروجی zip ساخته شد", bool(zp) and os.path.exists(zp))
check("پیام خروجی برای کاربر",
      bool(app2.snacks) and norm("خروجی ساخته شد") in norm(app2.snacks[0]))
with zipfile.ZipFile(zp) as zf:
    content = zf.read(zf.namelist()[1] if len(zf.namelist()) > 1
                      else zf.namelist()[0])
check("zip بیرون از برنامه خواندنی است",
      b"session-info" in content or "رخداد خطای نمونه".encode() in content)

# ── ۸) تور اسکرین‌شات: کلید نما در BUILDERS ──
import main as app_main  # noqa: E402

check("صفحه در BUILDERS ثبت شده", "logs" in app_main.BUILDERS)

print()
print("نتیجه:", "همهٔ بررسی‌ها پاس شد" if not fails else f"{len(fails)} خطا: {fails}")
sys.exit(1 if fails else 0)