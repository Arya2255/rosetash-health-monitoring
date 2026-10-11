# -*- coding: utf-8 -*-
"""تست صفحهٔ «آماده‌سازی گیت‌وی» — بدون پل، بدون برد و بدون رابط گرافیکی.

بررسی‌ها:
  - رندر سه‌گامی در حالت بدون پل (بنر صداقت + راهنماها)
  - کارت بستهٔ همراه با نسخهٔ فریمور واقعی
  - منطق هشدار هویت برد (مک تکراری/ناهماهنگ) — تابع خالص
  - اسکن پورت شبیه‌سازی‌شده و انتخاب پورت
  - گارد شروع فلش (پورت انتخاب‌نشده → فقط پیام، بدون رشتهٔ جدید)
  - مسیر شکست فلش: کارت خطای فارسی + لاگ
  - مسیر موفق فلش: تأیید هش + ثبت خودکار در دفتر پل (شبیه‌سازی‌شده)
  - مسیر «بدون تنظیمات»: ثبت در دفتر انجام نمی‌شود و پیام صادقانه می‌آید

اجرا از ریشهٔ مخزن:
    uv run python tests/test_provisioning_ui.py
"""
import os
import sys
import time

os.environ["ROZTASH_LIVE"] = "0"
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import views.provisioning as v_prov  # noqa: E402


def norm(s):
    """نرمال‌سازی مقایسه — نیم‌فاصله (U+200C) حذف می‌شود."""
    return str(s).replace("\u200c", "")


class FakePage:
    def __init__(self):
        self.overlay = []
        self.dialogs = []
        self.width = None
        self.height = 800
        self.updated = 0
        # توجه: run_task ندارد — یعنی صفحه باید بدون تیکر هم سالم بسازد

    def update(self):
        self.updated += 1

    def show_dialog(self, d):
        self.dialogs.append(d)


class FakeApp:
    def __init__(self):
        self.page = FakePage()
        self.state = {"view": "provisioning"}
        self.snacks = []
        self.rendered = 0

    def snack(self, msg):
        self.snacks.append(str(msg))

    def go(self, view, emp=None):
        self.state["view"] = view

    def render(self):
        self.rendered += 1


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


def texts_of(ctrl):
    out = []
    walk(ctrl, out)
    return norm("\n".join(out))


def wait_flash_done(st, timeout=8.0):
    t0 = time.time()
    while st.get("flashing") and time.time() - t0 < timeout:
        time.sleep(0.05)
    assert not st.get("flashing"), "فلش شبیه‌سازی‌شده تمام نشد"


def main():
    # ── ۱) رندر پایه بدون پل ──
    app = FakeApp()
    page = v_prov.provisioning_view(app)
    t = texts_of(page)
    for needle in ("آماده‌سازی گیتوی", "اسکن پورت‌های سریال",
                   "شروع فلش کامل", "بدون تنظیمات", "پل بالا نیست",
                   "RoztashGw", "dialout", "CP210x", "فریمور 0.2."):
        assert norm(needle) in t, f"متن پیدا نشد: {needle}\n---\n{t[:1000]}"
    st = app.state["prov"]
    assert st["inited"] and st["ports"] is None

    # رندر دوباره — وضعیت باید پایدار بماند و خطا ندهد
    v_prov.provisioning_view(app)
    assert app.state["prov"] is st

    # ── ۲) هشدارهای هویت برد — تابع خالص ──
    rows = [
        {"gw": "gw-anbar-1", "mac": "88:57:21:b8:ac:28", "registered": True},
        {"gw": "gw-filter-1", "mac": "", "registered": True},
        {"gw": "gw-x", "registered": False},
    ]
    w = v_prov._identity_warnings(
        {"mac": "88:57:21:b8:ac:28"}, rows, "gw-filter-1")
    assert len(w) == 1 and "gw-anbar-1" in w[0], w
    w = v_prov._identity_warnings(
        {"mac": "AA:BB:CC:DD:EE:FF"}, rows, "gw-anbar-1")
    assert len(w) == 1 and norm("نمی‌خواند") in norm(w[0]), w
    w = v_prov._identity_warnings(
        {"mac": "88:57:21:b8:ac:28"}, rows, "gw-anbar-1")
    assert w == [], w
    assert v_prov._identity_warnings(None, rows, "x") == []
    assert v_prov._identity_warnings({"mac": ""}, rows, "x") == []

    # ── ۳) اسکن پورت شبیه‌سازی‌شده + انتخاب ──
    orig_ports = v_prov.pv.list_serial_ports
    v_prov.pv.list_serial_ports = lambda: [
        {"port": "/dev/ttyUSB0", "label": "CP2102 USB to UART"},
        {"port": "/dev/ttyACM0", "label": "مچ‌بند؟"},
    ]
    try:
        v_prov._scan_ports(app, st)
        page = v_prov.provisioning_view(app)
        t = texts_of(page)
        assert "/dev/ttyUSB0" in t and "CP2102" in t, t[:800]
        st["sel_port"] = "/dev/ttyUSB0"
        t = texts_of(v_prov.provisioning_view(app))
        assert "انتخابشده" in t, t[:800]
    finally:
        v_prov.pv.list_serial_ports = orig_ports

    # ── ۴) گارد شروع فلش بدون پورت ──
    st["sel_port"] = None
    st["flashing"] = False
    app.snacks.clear()
    v_prov._start_flash(app, st)
    assert app.snacks and "پورت" in app.snacks[-1], app.snacks
    assert st["flashing"] is False

    # ── ۵) مسیر شکست فلش ──
    orig_flash = v_prov.pv.flash_gateway
    v_prov.pv.flash_gateway = lambda port, cfg=None, progress=None: (
        False, {"log": ["A fatal error occurred: Failed to connect to ESP32",
                        "Connecting........"],
                "verified": False, "error": "برد جواب نداد — دکمهٔ BOOT را نگه دار",
                "returncode": 2})
    try:
        st.update({"sel_port": "/dev/ttyUSB0", "cfg_mode": "config",
                   "gw_id": "gw-test-1", "ssid": "net", "host": "10.0.0.1",
                   "pass": "", "port": "1884", "zone": "تست", "label": ""})
        v_prov._start_flash(app, st)
        wait_flash_done(st)
        t = texts_of(v_prov.provisioning_view(app))
        assert "فلش ناموفق بود" in t, t[:1200]
        assert norm("دکمهٔ BOOT") in t, t[:1200]
        assert "Failed to connect" in t
        assert st["done"]["ok"] is False
    finally:
        v_prov.pv.flash_gateway = orig_flash

    # ── ۶) مسیر موفق فلش + ثبت خودکار در دفتر ──
    orig_flash = v_prov.pv.flash_gateway
    orig_save = v_prov.save_gateway
    saved = {}

    def fake_save(doc):
        saved.update(doc)
        return True, ""

    v_prov.pv.flash_gateway = lambda port, cfg=None, progress=None: (
        True, {"log": ["Hash of data verified."], "verified": True,
               "error": "", "returncode": 0})
    v_prov.save_gateway = fake_save
    try:
        st.update({"cfg_mode": "config", "done": None, "reg": None,
                   "gw_id": "gw-test-1", "label": "", "zone": "سالن تست",
                   "ident": {"mac": "88:57:21:b8:ac:28"}})
        v_prov._start_flash(app, st)
        wait_flash_done(st)
        t = texts_of(v_prov.provisioning_view(app))
        assert "فلش کامل شد" in t, t[:1200]
        assert norm("در دفتر گیتویها ثبت شد") in t, t[:1200]
        assert saved.get("gw") == "gw-test-1", saved
        assert saved.get("kind") == "installed", saved
        assert saved.get("mac") == "88:57:21:b8:ac:28", saved
        assert st["done"]["verified"] is True
    finally:
        v_prov.pv.flash_gateway = orig_flash
        v_prov.save_gateway = orig_save

    # ── ۷) مسیر «بدون تنظیمات» ──
    captured = {}
    orig_flash = v_prov.pv.flash_gateway

    def fake_flash_blank(port, cfg=None, progress=None):
        captured["cfg"] = cfg
        return True, {"log": ["Hash of data verified."], "verified": True,
                      "error": "", "returncode": 0}

    v_prov.pv.flash_gateway = fake_flash_blank
    try:
        st.update({"cfg_mode": "blank", "done": None, "reg": None})
        v_prov._start_flash(app, st)
        wait_flash_done(st)
        assert captured.get("cfg") is None, captured
        t = texts_of(v_prov.provisioning_view(app))
        assert norm("بدون تنظیمات فلش شد") in t, t[:1200]
        assert st["reg"] and st["reg"][0] is False
    finally:
        v_prov.pv.flash_gateway = orig_flash

    # ── ۸) نمایش پیشرفت زنده (وضعیت مستقیم) ──
    st.update({"flashing": True, "percent": 42,
               "log": ["Writing at 0x00010000... (42 %)", "Hash of data verified."]})
    t = texts_of(v_prov.provisioning_view(app))
    assert "در حال نوشتن" in t and "۴۲" in t, t[:800]
    assert "Hash of data verified." in t
    st["flashing"] = False

    # ── ۹) تراشه‌های دفتر برای انتخاب سریع شناسه ──
    st.update({"gw_rows": [{"gw": "gw-anbar-1", "label": "انبار محصولات",
                            "zone": "انبار", "registered": True}],
               "done": None, "reg": None})
    t = texts_of(v_prov.provisioning_view(app))
    assert norm("انبار محصولات") in t, t[:800]

    # ── ۱۰) فهرست پورت خالی → راهنمای کابل فقط-شارژ ──
    st.update({"ports": [], "sel_port": None})
    t = texts_of(v_prov.provisioning_view(app))
    assert norm("پورتی پیدا نشد") in t
    assert norm("کابل دیتادار") in t or norm("فقط-شارژ") in t

    print("OK — همهٔ بررسی‌های صفحهٔ آماده‌سازی گیتوی پاس شد")


if __name__ == "__main__":
    main()
