# -*- coding: utf-8 -*-
"""تست نقشهٔ زنده — نقطهٔ مچ‌بند، برچسب فاصلهٔ تخمینی و کارت تست فاصله.

بدون پل و بدون رابط گرافیکی؛ همهٔ داده‌های پل ساختگی به توابع نما پاس
داده می‌شود. بررسی‌ها:
  - تخمین فاصله از قدرت سیگنال و متن «≈ … متر»
  - نقطهٔ مچ‌بند فقط زیر گیت‌وی نصب‌شده و شناخته‌شده می‌آید
  - دیدن کهنه‌تر از آستانه، کم‌رنگ نمایش داده می‌شود
  - ردیف‌های وضعیت زنده: نام گیت‌وی، مک، dBm، متر و «دورترین تخمین نشست»
  - ساخت کامل نما بدون پل (پیام جایگزین) با FakeApp

اجرا از ریشهٔ مخزن:
    uv run python tests/test_map_live.py
"""
import os
import sys

os.environ["ROZTASH_LIVE"] = "0"
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import views.map as m  # noqa: E402

# ── ۱) تخمین فاصله از قدرت سیگنال ──
assert abs(m._approx_m(-59) - 1.0) < 0.01, m._approx_m(-59)
m88 = m._approx_m(-88)
assert 13 < m88 < 16, m88
assert m._m_text(-88) == "≈ ۱۴ متر", m._m_text(-88)
assert m._m_text(None) == "در دید", m._m_text(None)

# ── ۲) نقطهٔ مچ‌بند — فقط زیر گیت‌وی نصب‌شدهٔ شناخته‌شده ──
doc = {
    "ok": True,
    "gateways": [{"gw": "gw-test-1", "online": True, "fw": "0.1.5-vibrate"}],
    "bands": [
        {"mac": "f3:b6:d6:b7:47:d7", "gw": "gw-test-1", "rssi": -88,
         "age_s": 9.0, "seen_at": "S1"},
        {"mac": "aa:bb:cc:dd:ee:ff", "gw": "gw-unknown", "rssi": -70,
         "age_s": 3.0, "seen_at": "S2"},
    ],
}
dots = m._worker_dots(500, 800, doc=doc)
assert len(dots) == 1, len(dots)
assert "f3:b6:d6:b7:47:d7" in dots[0].tooltip
assert "۸۸" in dots[0].tooltip
assert dots[0].content.controls[0].bgcolor == m.WARN  # سیگنال زیر ۷۵- → نارنجی
assert dots[0].content.controls[1].content.value == "≈ ۱۴ متر"

# ── ۳) ردیف‌های وضعیت زنده و آمار تست فاصله ──
watch = {"weakest": -91, "weakest_at": 1791700000, "samples": 12,
         "last_seen": None}
rows = m._live_rows(doc, watch)


def walk(c, out):
    v = getattr(c, "value", None)
    if isinstance(v, str):
        out.append(v)
    content = getattr(c, "content", None)
    if content is not None:
        if isinstance(content, str):
            out.append(content)
        else:
            walk(content, out)
    for ch in getattr(c, "controls", None) or []:
        walk(ch, out)


texts = []
for r in rows:
    walk(r, texts)
joined = "\n".join(texts)
assert "سالن فیلتر ۱" in joined, joined
assert "-۸۸" in joined, joined
assert "≈ ۱۴ متر" in joined, joined
assert "دورترین تخمین این نشست" in joined, joined
assert "≈ ۱۹ متر" in joined, joined  # from weakest -91
assert "۱۲" in joined, joined  # تعداد مشاهده‌ها
assert "مشاهدهٔ مچ‌بند در این نشست" in joined, joined

# ── ۴) کهنه‌شدن دیدن — نقطه کم‌رنگ ──
doc2 = {"ok": True, "gateways": [], "bands": [
    {"mac": "x", "gw": "gw-test-1", "rssi": -80, "age_s": 45.0, "seen_at": "S3"}]}
dots2 = m._worker_dots(500, 800, doc=doc2)
assert len(dots2) == 1
assert dots2[0].content.controls[0].bgcolor == "#9AA0A6", "کهنه نباید رنگی بماند"
assert dots2[0].content.controls[1].content.color == m.TEXT_MUTED


# ── ۵) ساخت کامل نما بدون پل + FakeApp ──
class FakePage:
    def __init__(self):
        self.overlay = []
        self.dialogs = []

    def update(self):
        pass

    def show_dialog(self, d):
        self.dialogs.append(d)


class FakeApp:
    def __init__(self):
        self.page = FakePage()
        self.state = {"view": "map"}
        self.alerts_active = []

    def snack(self, msg):
        pass


app = FakeApp()
v = m.map_view(app)
assert v is not None
assert "map_watch" in app.state
texts2 = []
walk(v, texts2)
assert any("پل زنده در دسترس نیست" in t for t in texts2), "پیام نبود پل نیامد"

print("OK — همهٔ بررسی‌های نقشهٔ زنده پس شد")
