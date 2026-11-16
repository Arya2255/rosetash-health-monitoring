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
# PDMB1062 reference: -82 dBm at 1 m, n=2.5 (calibration in ed21cb9).
m82 = m._approx_m(-82)
assert m82 is not None and abs(m82 - 1.0) < 0.01, m82
m107 = m._approx_m(-107)
assert m107 is not None and abs(m107 - 10.0) < 0.01, m107
m88 = m._approx_m(-88)
assert m88 is not None and 1.7 < m88 < 1.8, m88
assert m._m_text(-88) == "≈ ۲ متر", m._m_text(-88)
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
assert dots[0].content.controls[1].content.value == "≈ ۲ متر"

# ── ۳) ردیف‌های وضعیت زنده و آمار تست فاصله ──
# Keep the rounded session maximum distinct from the current 2 m estimate.
watch = {"weakest": -94, "weakest_at": 1791700000, "samples": 12,
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
assert "≈ ۲ متر" in joined, joined
assert "دورترین تخمین این نشست" in joined, joined
assert "≈ ۳ متر" in joined, joined  # from weakest -94
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

# Explicit empty live registry must not borrow demo gateway positions.
assert m._worker_dots(500, 800, doc=doc, rows=[]) == []
strongest_doc = {"bands": [{"mac": "aa:bb:cc:dd:ee:01", "gw": "gw-winner",
                            "rssi": -50, "age_s": 1}]}
registry = [
    {"gw": "gw-other", "label": "سالن دیگر", "kind": "installed", "x": 0.1, "y": 0.2},
    {"gw": "gw-winner", "label": "نزدیک‌ترین ناحیه", "kind": "installed", "x": 0.8, "y": 0.7},
]
chosen = m._worker_dots(500, 800, doc=strongest_doc, rows=registry)
assert len(chosen) == 1 and "نزدیک‌ترین ناحیه" in chosen[0].tooltip
assert chosen[0].left > 300
registry[1]["kind"] = "proposed"
assert m._worker_dots(500, 800, doc=strongest_doc, rows=registry) == []

print("OK — همهٔ بررسی‌های نقشهٔ زنده پس شد")
