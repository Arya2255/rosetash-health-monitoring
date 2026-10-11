# -*- coding: utf-8 -*-
"""تست چند-دستگاهی نمای زنده — دو گیت‌وی و دو مچ‌بند ساختگی.

بررسی می‌کند که برنامه به‌ازای هر تعداد دستگاه که در snapshot پل باشد،
همه را در کارت «گیت‌وی‌ها و مچ‌بندهای در دید» فهرست کند، کارت‌های شاخص
شمارشی شوند، نوار زندهٔ داشبورد چیپ شمارشی بگیرد، و نمایش تک-دستگاهی
قبلی دست‌نخورده بماند.

اجرا از ریشهٔ مخزن:
    uv run python tests/test_multidev_ui.py
"""
import os
import sys
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))


def iso(ts):
    return datetime.fromtimestamp(ts).isoformat()


now = time.time()


def make_doc():
    return {
        "ok": True, "fetched_at": iso(now), "now": now,
        "gateways": [
            {"gw": "gw-test-1", "zone": "test", "fw": "0.1.5", "ip": "192.168.43.100",
             "rssi": -55, "uptime_s": 7200, "adv_seen": 1200, "online": True,
             "last_seen": iso(now), "age_s": 2.0},
            {"gw": "gw-zone-2", "zone": "سالن تولید ۲", "fw": "0.1.5", "ip": "192.168.43.101",
             "rssi": -67, "uptime_s": 3600, "adv_seen": 800, "online": True,
             "last_seen": iso(now - 5), "age_s": 5.0},
        ],
        "bands": [
            {"mac": "f3:b6:d6:b7:47:d7", "gw": "gw-test-1", "rssi": -61,
             "seen_at": iso(now), "age_s": 3.0},
            {"mac": "aa:bb:cc:dd:ee:01", "gw": "gw-zone-2", "rssi": -78,
             "seen_at": iso(now - 10), "age_s": 10.0},
        ],
        "health": [
            {"gw": "gw-test-1", "mac": "f3:b6:d6:b7:47:d7", "state": "done", "fail": "none",
             "wearing": True, "ended": True, "bpm": [79, 78, 77], "n": 3, "avg": 78,
             "ts": iso(now - 30), "age_s": 30.0},
        ],
        "vitals": [
            {"gw": "gw-test-1", "mac": "f3:b6:d6:b7:47:d7", "battery": 90, "dev_fw": "2.0.2.3",
             "dev_hw": "1.0.0.0", "dev_maker": "OnMicro", "spo2_ack": False, "hrv_ack": False,
             "steps": 1234, "spo2_raw": [], "hrv_raw": [], "ts": iso(now - 30), "age_s": 30.0},
        ],
        "events": [],
    }


class FakePage:
    def update(self):
        pass


class FakeApp:
    def __init__(self):
        self.state = {"view": "live", "live_gen": 0}
        self.page = FakePage()

    def snack(self, msg):
        pass


def texts(ctrl, out=None):
    if out is None:
        out = []
    v = getattr(ctrl, "value", None)
    if isinstance(v, str):
        out.append(v)
    controls = getattr(ctrl, "controls", None)
    if isinstance(controls, list):
        for c in controls:
            texts(c, out)
    content = getattr(ctrl, "content", None)
    if content is not None:
        texts(content, out)
    return out


import views.live as v_live  # noqa: E402
import views.dashboard as v_dash  # noqa: E402

fails = []


def norm(s):
    """یکسان‌سازی مقایسه — حذف نیم‌فاصله."""
    return s.replace("\u200c", "")


def check(name, cond):
    print(("OK   — " if cond else "FAIL — ") + name)
    if not cond:
        fails.append(name)


# ── ۱) نمای زنده با دو گیت‌وی و دو مچ‌بند ──
doc = make_doc()
v_live.live_status = lambda force=False: doc
view = v_live.live_view(FakeApp())
vals = " || ".join(texts(view))

check("گیت‌وی اول در فهرست", "gw-test-1" in vals)
check("گیت‌وی دوم در فهرست", "gw-zone-2" in vals)
check("مچ‌بند اول در فهرست", "f3:b6:d6:b7:47:d7" in vals)
check("مچ‌بند دوم در فهرست", "aa:bb:cc:dd:ee:01" in vals)
check("شمارندهٔ دستگاه‌ها", norm("۲ گیت‌وی — ۲ مچ‌بند") in norm(vals))
check("کارت گیت‌وی شمارشی", "۲ از ۲" in vals)
check("زیرنویس چند-مچ‌بندی", norm("۲ مچ‌بند در دید") in norm(vals))
check("منطقهٔ گیت‌وی دوم", "سالن تولید ۲" in vals)
check("وای‌فای گیت‌وی دوم", "۶۷" in vals)

# ── ۲) حالت تک-دستگاهی قبلی حفظ شود ──
single = make_doc()
single["gateways"] = single["gateways"][:1]
single["bands"] = single["bands"][:1]
v_live.live_status = lambda force=False: single
view2 = v_live.live_view(FakeApp())
vals2 = " || ".join(texts(view2))
check("تک-گیت‌وی: نسخهٔ fw نمایش", "0.1.5" in vals2)
check("تک-مچ‌بند: زیرنویس ساده",
      norm("دیده می‌شود") in norm(vals2) and norm("۲ مچ‌بند در دید") not in norm(vals2))
check("تک-گیت‌وی: چیپ شمارشی نیست", "۲ از ۲" not in vals2)

# ── ۳) نوار زندهٔ داشبورد ──
summary_multi = {
    "available": True, "fetched_at": iso(now),
    "gateway": doc["gateways"][0], "band": doc["bands"][0],
    "health": doc["health"][0], "vitals": doc["vitals"][0],
    "gateways_count": 2, "gateways_online": 2, "bands_count": 2,
}
svals = norm(" || ".join(texts(v_dash._live_strip(summary_multi))))
check("نوار داشبورد: ۲ گیت‌وی", norm("۲ گیت‌وی") in svals and norm("۲ آنلاین") in svals)
check("نوار داشبورد: ۲ مچ‌بند", norm("۲ مچ‌بند") in svals)

summary_one = dict(summary_multi)
summary_one.update({"gateways_count": 1, "gateways_online": 1, "bands_count": 1})
s1 = " || ".join(texts(v_dash._live_strip(summary_one)))
check("نوار داشبورد تک: نام گیت‌وی", "gw-test-1" in s1)

print()
print("نتیجه:", "همهٔ بررسی‌ها پاس شد" if not fails else f"{len(fails)} خطا: {fails}")
sys.exit(1 if fails else 0)
