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
from types import SimpleNamespace
from unittest.mock import patch

os.environ["ROZTASH_LIVE"] = "0"
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import views.provisioning as v_prov  # noqa: E402
import flet as ft  # noqa: E402


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


def controls_of(control):
    yield control
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from controls_of(content)
    for child in getattr(control, "controls", None) or []:
        yield from controls_of(child)


def test_gateway_identity_comes_only_from_registered_rows():
    app = FakeApp()
    app.state["prov"] = {"inited": True, "gw_rows": [
        {"gw": "gw-line-1", "label": "خط یک", "zone": "تولید", "registered": True},
        {"gw": "gw-old", "label": "حذف‌شده", "registered": False},
    ], "gw_id": "", "label": "", "zone": "", "host": "192.168.50.1", "port": "1884"}
    view = v_prov._step2_card(app, app.state["prov"])
    controls = list(controls_of(view))
    selector = next(c for c in controls if getattr(c, "data", None) == "provisioning:gateway")
    assert isinstance(selector, ft.Dropdown)
    assert {option.key for option in selector.options} == {"gw-line-1"}
    assert not any(isinstance(c, ft.TextField) and "شناسهٔ گیت‌وی" in (c.label or "")
                   for c in controls)
    assert app.state["prov"]["gw_id"] == "gw-line-1"
    assert app.state["prov"]["label"] == "خط یک"
    selector.value = "gw-old"
    selector.on_select(SimpleNamespace(control=selector))
    assert app.state["prov"]["gw_id"] == "gw-line-1"


def test_registry_refresh_loads_new_entries_and_preserves_valid_selection():
    app = FakeApp()
    rows = [{"gw": "gw-one", "label": "یک", "zone": "واحد یک", "registered": True}]
    with patch.object(v_prov, "live_gateways", return_value=rows):
        st = v_prov._prov_state(app)
        v_prov._step2_card(app, st)
        assert st["gw_id"] == "gw-one"
        rows.append({"gw": "gw-two", "label": "دو", "zone": "واحد دو", "registered": True})
        st = v_prov._prov_state(app)
        selector = next(c for c in controls_of(v_prov._step2_card(app, st))
                        if getattr(c, "data", None) == "provisioning:gateway")
        assert {o.key for o in selector.options} == {"gw-one", "gw-two"}
        selector.value = "gw-two"
        selector.on_select(SimpleNamespace(control=selector))
        assert (st["gw_id"], st["label"], st["zone"]) == ("gw-two", "دو", "واحد دو")
        v_prov._prov_state(app)
        assert st["gw_id"] == "gw-two"


def test_deleted_or_unknown_gateway_cannot_be_flashed():
    app = FakeApp()
    st = {"sel_port": "COM7", "ident": {"mac": "aa:bb:cc:dd:ee:01",
          "chip_id": v_prov.pv.TARGET_CHIP, "flash_bytes": 16777216},
          "gw_rows": [], "gw_id": "gw-deleted", "host": "192.0.2.1", "port": "1884"}
    with patch.object(v_prov, "live_gateways", return_value=[]), \
            patch.object(v_prov.threading, "Thread") as thread:
        v_prov._start_flash(app, st)
    thread.assert_not_called()
    assert app.snacks and not st.get("flashing")
    v_prov._step2_card(app, st)
    assert not st.get("gw_id")



def wait_flash_done(st, timeout=8.0):
    t0 = time.time()
    while st.get("flashing") and time.time() - t0 < timeout:
        time.sleep(0.05)
    assert not st.get("flashing"), "فلش شبیه‌سازی‌شده تمام نشد"


def main():
    test_gateway_identity_comes_only_from_registered_rows()
    test_deleted_or_unknown_gateway_cannot_be_flashed()
    test_registry_refresh_loads_new_entries_and_preserves_valid_selection()
    # ── ۱) رندر پایه بدون پل ──
    app = FakeApp()
    page = v_prov.provisioning_view(app)
    t = texts_of(page)
    for needle in ("آماده‌سازی گیتوی", "اسکن پورت‌های سریال",
                   "شروع فلش کامل", "dialout",
                   "CP210x", "فریمور 0.5.2", "192.168.50.1", "DHCP", "W5500"):
        assert norm(needle) in t, f"متن پیدا نشد: {needle}\n---\n{t[:1000]}"
    for obsolete in ("SSID", "رمز وای‌فای", "RoztashGw",
                     "بدون تنظیمات", "خودش AP باز می‌کند"):
        assert norm(obsolete) not in t, f"گزینهٔ قدیمی هنوز نمایش داده می‌شود: {obsolete}"
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

    # ── ۴) گاردها: بدون پورت و بدون تأیید هویت فلش شروع نمی‌شود ──
    st["sel_port"] = None
    st["flashing"] = False
    app.snacks.clear()
    v_prov._start_flash(app, st)
    assert app.snacks and "پورت" in app.snacks[-1], app.snacks
    assert st["flashing"] is False

    st.update({"sel_port": "/dev/ttyUSB0", "ident": None})
    app.snacks.clear()
    v_prov._start_flash(app, st)
    assert app.snacks and "ESP32-S3" in app.snacks[-1], app.snacks
    assert st["flashing"] is False

    # ── ۵) مسیر شکست فلش ──
    registry_patch = patch.object(v_prov, "live_gateways", return_value=[
        {"gw": "gw-test-1", "label": "", "zone": "سالن تست", "registered": True}])
    registry_patch.start()
    orig_flash = v_prov.pv.flash_gateway
    v_prov.pv.flash_gateway = lambda port, cfg=None, expected_chip="esp32s3", expected_flash_bytes=16777216, expected_mac="", progress=None: (
        False, {"log": ["A fatal error occurred: Failed to connect to ESP32",
                        "Connecting........"],
                "verified": False, "error": "برد جواب نداد — دکمهٔ BOOT را نگه دار",
                "returncode": 2})
    try:
        st.update({"sel_port": "/dev/ttyUSB0", "ident": {
                       "mac": "88:57:21:b8:ac:28",
                       "chip_id": v_prov.pv.TARGET_CHIP,
                       "flash_bytes": 16 * 1024 * 1024},
                   "gw_id": "gw-test-1", "host": "192.168.50.1",
                   "port": "1884", "zone": "تست", "label": ""})
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

    captured_config = {}

    def fake_flash_config(port, cfg=None, expected_chip="esp32s3",
                          expected_flash_bytes=16 * 1024 * 1024,
                          expected_mac="", progress=None):
        captured_config["cfg"] = cfg
        captured_config["hardware"] = (expected_chip, expected_flash_bytes,
                                       expected_mac)
        return True, {"log": ["Hash of data verified."], "verified": True,
                      "error": "", "returncode": 0}

    v_prov.pv.flash_gateway = fake_flash_config
    v_prov.save_gateway = fake_save
    try:
        st.update({"done": None, "reg": None,
                   "gw_id": "gw-test-1", "label": "", "zone": "سالن تست",
                   "host": "192.168.50.1", "port": "1884",
                   "ident": {"mac": "88:57:21:b8:ac:28",
                             "chip_id": v_prov.pv.TARGET_CHIP,
                             "flash_bytes": 16 * 1024 * 1024}})
        v_prov._start_flash(app, st)
        wait_flash_done(st)
        t = texts_of(v_prov.provisioning_view(app))
        assert "فلش کامل شد" in t, t[:1200]
        assert norm("در دفتر گیتویها ثبت شد") in t, t[:1200]
        assert saved.get("gw") == "gw-test-1", saved
        assert saved.get("kind") == "installed", saved
        assert saved.get("mac") == "88:57:21:b8:ac:28", saved
        assert st["done"]["verified"] is True
        assert captured_config["hardware"] == (
            "esp32s3", 16 * 1024 * 1024, "88:57:21:b8:ac:28")
        assert captured_config["cfg"] == {
            "gw_id": "gw-test-1", "zone": "سالن تست",
            "mqtt_host": "192.168.50.1", "mqtt_port": 1884,
            "health_interval_s": 600, "scan_interval_ms": 160,
            "scan_window_ms": 80, "measure_timeout_s": 45,
        }
    finally:
        v_prov.pv.flash_gateway = orig_flash
        v_prov.save_gateway = orig_save

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
    with patch.object(v_prov, "live_gateways", return_value=st["gw_rows"]):
        view = v_prov.provisioning_view(app)
        dropdown = next(c for c in controls_of(view)
                        if getattr(c, "data", None) == "provisioning:gateway")
        assert "انبار محصولات" in dropdown.options[0].text

    # ── ۱۰) فهرست پورت خالی → راهنمای کابل فقط-شارژ ──
    st.update({"ports": [], "sel_port": None})
    t = texts_of(v_prov.provisioning_view(app))
    assert norm("پورتی پیدا نشد") in t
    assert norm("کابل دیتادار") in t or norm("فقط-شارژ") in t

    registry_patch.stop()
    print("OK — همهٔ بررسی‌های صفحهٔ آماده‌سازی گیتوی پاس شد")


if __name__ == "__main__":
    main()
