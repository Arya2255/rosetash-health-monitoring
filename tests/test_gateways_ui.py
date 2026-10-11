# -*- coding: utf-8 -*-
"""تست بخش «گیت‌وی‌ها» و حالت چیدن نقشه — بدون پل و بدون رابط گرافیکی.

بررسی‌ها:
  - ریاضی جابه‌جایی پین (حاشیهٔ ۲٪) و استخراج دلتای رویداد
  - نقشهٔ نمایشی بدون پل — پیام صریح، پین غیرقابل کشیدن
  - نقشه با دفتر پل — پین چیده‌شده، چیده‌نشده و کشف‌شده
  - کشیدن پین در حالت چیدن: start/update/end → ذخیرهٔ x/y گردشده
  - صفحهٔ گیت‌وی‌ها: فهرست زنده، کشف‌شده‌ها، شمارنده‌ها و حالت نمایشی
  - فرم تعریف گیت‌وی: پیشنهاد شناسه، اعتبارسنجی نام، بدنهٔ ارسالی

اجرا از ریشهٔ مخزن:
    uv run python tests/test_gateways_ui.py
"""
import os
import sys
import types

os.environ["ROZTASH_LIVE"] = "0"
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import components.gateway_form as gf  # noqa: E402
import views.gateways as gv  # noqa: E402
import views.map as m  # noqa: E402


def norm(s):
    """نرمال‌سازی برای مقایسه — نیم‌فاصله (U+200C) حذف می‌شود."""
    return str(s).replace("\u200c", "")


class FakePage:
    def __init__(self):
        self.overlay = []
        self.dialogs = []
        self.width = None
        self.height = 800
        self.updated = 0

    def update(self):
        self.updated += 1

    def show_dialog(self, d):
        self.dialogs.append(d)

    def pop_dialog(self):
        if self.dialogs:
            self.dialogs.pop()


class FakeApp:
    def __init__(self, view="map"):
        self.page = FakePage()
        self.state = {"view": view, "emp": None}
        self.alerts_active = []
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


def find_gd(ctrl, out):
    """همهٔ GestureDetectorهای درخت کنترل‌ها."""
    if isinstance(ctrl, m.ft.GestureDetector):
        out.append(ctrl)
    content = getattr(ctrl, "content", None)
    if content is not None and not isinstance(content, str):
        find_gd(content, out)
    for ch in getattr(ctrl, "controls", None) or []:
        find_gd(ch, out)
    return out


ROWS = [
    {"gw": "gw-test-1", "label": "سالن فیلتر ۱", "kind": "installed",
     "x": 0.28, "y": 0.25, "registered": True, "live": True, "online": True,
     "fw": "0.1.5", "zone": "فیلتر", "age_s": 5.0},
    {"gw": "gw-anbar-1", "label": "انبار محصولات", "kind": "proposed",
     "x": None, "y": None, "registered": True, "live": False, "online": False},
    {"gw": "gw-new-9", "label": None, "kind": "installed", "x": None,
     "y": None, "registered": False, "live": True, "online": True,
     "zone": "انبار"},
]

DOC = {
    "ok": True,
    "bands": [{"mac": "f3:b6:d6:b7:47:d7", "gw": "gw-test-1",
               "rssi": -70, "age_s": 4.0, "seen_at": "S1"}],
    "gateways": [{"gw": "gw-test-1", "online": True, "fw": "0.1.5"},
                 {"gw": "gw-new-9", "online": True}],
    "map_gateways": [dict(r) for r in ROWS],
}


def main():
    # ── ۱) ریاضی جابه‌جایی ──
    nx, ny = m._moved(0.5, 0.5, 400, 800, 40, 80)
    assert abs(nx - 0.6) < 1e-9 and abs(ny - 0.6) < 1e-9, (nx, ny)
    nx, ny = m._moved(0.5, 0.5, 400, 800, -10000, 10000)
    assert abs(nx - 0.02) < 1e-9 and abs(ny - 0.98) < 1e-9, (nx, ny)
    ev = types.SimpleNamespace(local_delta=types.SimpleNamespace(x=3, y=-4))
    assert m._delta_xy(ev) == (3.0, -4.0)
    assert m._delta_xy(None) == (0.0, 0.0)
    assert m._delta_xy(types.SimpleNamespace(local_delta=None)) == (0.0, 0.0)

    # ── ۲) نقشهٔ نمایشی بدون پل ──
    app = FakeApp("map")
    v = m.map_view(app)
    t = texts_of(v)
    assert "پل زنده در دسترس نیست" in t, t
    assert "پل در دسترس نیست — چیدمان نمایشی و غیرقابل ویرایش." in t, t
    assert "برای تعریف و چیدمان، پل باید بالا باشد." in t, t
    assert not find_gd(v, []), "بدون پل هیچ پینی نباید قابل کشیدن باشد"

    # ── ۳) نقشه با دفتر پل — پین‌ها و ردیف‌های فهرست ──
    m.live_status = lambda force=False: DOC
    app2 = FakeApp("map")
    v2 = m.map_view(app2)
    t2 = texts_of(v2)
    assert "سالن فیلتر ۱" in t2 and "انبار محصولات" in t2, t2
    assert "روی نقشه چیده نشده" in t2, t2          # ردیف gw-anbar-1
    assert "gw-new-9" in t2 and "هنوز تعریف نشده" in t2, t2
    assert "1 گیتوی کشف‌شده هنوز تعریف نشده" in t2 or "۱ گیتوی" in t2, t2
    assert not find_gd(v2, []), "حالت چیدن خاموش است — پین نباید کشیدنی باشد"

    # ── ۴) حالت چیدن — سه پین کشیدنی، ذخیرهٔ موقعیت ──
    saved = []
    orig_save = m.save_gateway
    m.save_gateway = lambda d: (saved.append(dict(d)), (True, ""))[1]
    try:
        app3 = FakeApp("map")
        app3.state["map_edit"] = True
        v3 = m.map_view(app3)
        gds = find_gd(v3, [])
        assert len(gds) == 3, f"سه پین باید کشیدنی باشند: {len(gds)}"

        W, H = m._display_size(app3)

        class E:
            local_delta = types.SimpleNamespace(x=40.0, y=80.0)

        gd = gds[0]
        gd.on_pan_start(None)
        gd.on_pan_update(E())
        gd.on_pan_end(None)
        assert saved, "ذخیرهٔ موقعیت صدا زده نشد"
        assert saved[-1]["gw"] == "gw-test-1", saved[-1]
        exp_x, exp_y = round(0.28 + 40.0 / W, 4), round(0.25 + 80.0 / H, 4)
        assert abs(saved[-1]["x"] - exp_x) < 1e-6, (saved[-1], exp_x)
        assert abs(saved[-1]["y"] - exp_y) < 1e-6, (saved[-1], exp_y)
        assert any("ذخیره شد" in s for s in app3.snacks), app3.snacks

        # پین چیده‌نشده هم از نقطهٔ پیش‌فرض کشیدنی است و ذخیره می‌شود
        gd2 = gds[1]
        gd2.on_pan_start(None)
        gd2.on_pan_end(None)
        assert saved[-1]["gw"] == "gw-anbar-1", saved[-1]
        assert 0.02 <= saved[-1]["x"] <= 0.98
        assert 0.02 <= saved[-1]["y"] <= 0.98
    finally:
        m.save_gateway = orig_save

    # ── ۵) صفحهٔ گیت‌وی‌ها — فهرست زنده و کشف‌شده ──
    gv.live_gateways = lambda force=False: [dict(r) for r in ROWS]
    app4 = FakeApp("gateways")
    v4 = gv.gateways_view(app4)
    t4 = texts_of(v4)
    for needle in ("سالن فیلتر ۱", "انبار محصولات", "gw-new-9",
                   "روی نقشه", "آنلاین", "پیشنهادی", "هنوز تعریف نشده",
                   "گیتوی‌های تعریف‌شده", "نقشه کارخانه"):
        assert norm(needle) in t4, f"«{needle}» در صفحه نیامد"

    # ── ۶) صفحهٔ گیت‌وی‌ها بدون پل — حالت نمایشی ──
    gv.live_gateways = lambda force=False: None
    app5 = FakeApp("gateways")
    v5 = gv.gateways_view(app5)
    t5 = texts_of(v5)
    assert "پل محلی در دسترس نیست" in t5, t5
    assert "سالن فیلتر ۱" in t5, t5

    # ── ۷) پیشنهاد شناسهٔ خودکار ──
    assert gf.suggest_gw_id([]) == "gw-1"
    assert gf.suggest_gw_id([{"gw": "gw-1"}, {"gw": "gw-2"}]) == "gw-3"
    assert gf.suggest_gw_id([{"gw": "gw-test-1"}]) == "gw-1"

    # ── ۸) فرم تعریف — اعتبارسنجی نام و بدنهٔ ارسالی ──
    posted = []
    orig_save2 = gf.save_gateway
    gf.save_gateway = lambda d: (posted.append(dict(d)), (True, ""))[1]
    try:
        app6 = FakeApp("gateways")
        gf.open_gateway_form(app6, rows=ROWS,
                             on_saved=lambda: app6.render())
        assert app6.page.dialogs, "دیالوگ فرم باز نشد"
        dlg = app6.page.dialogs[-1]
        fields = dlg.content.content.controls

        dlg.actions[1].on_click(None)          # نام خالی → نباید بفرستد
        assert not posted, "فرم با نام خالی نباید ثبت کند"

        fields[0].value = "سالن فیلتر ۲"        # label
        fields[2].value = "فیلتر ۲"             # zone
        fields[3].value = "installed"          # kind
        dlg.actions[1].on_click(None)
        assert posted, "ثبت انجام نشد"
        assert posted[-1]["label"] == "سالن فیلتر ۲", posted[-1]
        assert posted[-1]["zone"] == "فیلتر ۲", posted[-1]
        assert posted[-1]["kind"] == "installed", posted[-1]
        assert posted[-1]["gw"] == "gw-1", posted[-1]   # پیشنهاد خودکار
        assert app6.rendered == 1, "بعد از ثبت، فهرست باید تازه شود"
    finally:
        gf.save_gateway = orig_save2

    # ── ۹) فرم ویرایش — شناسه قفل و برداشتن از نقشه ──
    posted2 = []
    gf.save_gateway = lambda d: (posted2.append(dict(d)), (True, ""))[1]
    try:
        app7 = FakeApp("gateways")
        row = dict(ROWS[0])
        gf.open_gateway_form(app7, row=row, rows=ROWS)
        dlg2 = app7.page.dialogs[-1]
        fields2 = dlg2.content.content.controls
        assert fields2[1].value == "gw-test-1", fields2[1].value
        assert fields2[1].read_only is True, "در ویرایش شناسه باید قفل باشد"
        fields2[0].value = "سالن فیلتر ۱ (به‌روز)"
        pos_btn = [c for c in fields2
                   if "برداشتن" in norm(str(getattr(c, "content", "")))]
        assert pos_btn, "دکمهٔ برداشتن از نقشه باید باشد (ردیف چیده‌شده)"
        pos_btn[0].on_click(None)
        dlg2.actions[1].on_click(None)
        assert posted2 and posted2[-1]["x"] == "" and posted2[-1]["y"] == "", posted2
    finally:
        gf.save_gateway = orig_save2

    # ── ۱۰) تغییر شناسهٔ نقطهٔ پیشنهادی — حذف قدیم و ثبت تازه ──
    posted3, deleted = [], []
    orig_del = gf.delete_gateway
    gf.save_gateway = lambda d: (posted3.append(dict(d)), (True, ""))[1]
    gf.delete_gateway = lambda gid: (deleted.append(gid), (True, ""))[1]
    try:
        app8 = FakeApp("gateways")
        prop = dict(ROWS[1])
        prop["x"], prop["y"] = 0.4, 0.5
        gf.open_gateway_form(app8, row=prop, rows=ROWS)
        dlg3 = app8.page.dialogs[-1]
        f3 = dlg3.content.content.controls
        assert not f3[1].read_only, "شناسهٔ نقطهٔ پیشنهادی باید قابل تغییر باشد"
        f3[1].value = "gw-test-1"          # تکراری → باید رد شود
        dlg3.actions[1].on_click(None)
        assert not posted3 and not deleted, "شناسهٔ تکراری نباید ثبت شود"
        f3[1].value = "gw-filter-2"        # آزاد → تغییر شناسه
        dlg3.actions[1].on_click(None)
        assert deleted == ["gw-anbar-1"], deleted
        assert posted3[-1]["gw"] == "gw-filter-2", posted3[-1]
        assert posted3[-1]["x"] == 0.4 and posted3[-1]["y"] == 0.5, posted3[-1]
    finally:
        gf.save_gateway = orig_save2
        gf.delete_gateway = orig_del

    print("OK — همهٔ بررسی‌های گیت‌وی‌ها و چیدن نقشه پاس شد")


if __name__ == "__main__":
    main()
