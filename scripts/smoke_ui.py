# -*- coding: utf-8 -*-
"""تست دودی — ساخت همهٔ صفحه‌ها بدون اجرای رابط گرافیکی.

اجرا:
    uv run python scripts/smoke_ui.py
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from data import ALERTS_ACTIVE  # noqa: E402

import components.sidebar as c_sidebar  # noqa: E402
import views.alerts as v_alerts  # noqa: E402
import views.attendance as v_attendance  # noqa: E402
import views.dashboard as v_dashboard  # noqa: E402
import views.employee_detail as v_detail  # noqa: E402
import views.employees as v_employees  # noqa: E402
import views.live as v_live  # noqa: E402
import views.map as v_map  # noqa: E402
import views.management as v_management  # noqa: E402
import views.reports as v_reports  # noqa: E402
import views.settings as v_settings  # noqa: E402


class FakePage:
    def __init__(self):
        self.overlay = []
        self.dialogs = []

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        pass


class FakeApp:
    def __init__(self):
        self.page = FakePage()
        self.state = {"view": "dashboard", "emp": None, "filter": "all",
                      "search": "", "emp_search": "", "att_filter": "all",
                      "att_search": "", "report_tab": "هفتگی",
                      "back_to": "dashboard"}
        self.alerts_active = [dict(a) for a in ALERTS_ACTIVE]
        self.siren_on = True

    def snack(self, msg):
        pass

    def set_siren(self, on):
        self.siren_on = on

    def close_alert(self, alert_id):
        self.alerts_active = [a for a in self.alerts_active if a["id"] != alert_id]

    def go(self, view, emp=None):
        self.state["view"] = view


def main():
    app = FakeApp()
    checks = [
        ("پوسته / نوار کناری", lambda: c_sidebar.build_sidebar("dashboard", app.go, 3)),
        ("داشبورد", lambda: v_dashboard.dashboard_view(app)),
        ("پایش زنده", lambda: v_live.live_view(app)),
        ("نقشهٔ کارخانه", lambda: v_map.map_view(app)),
        ("کارکنان", lambda: v_employees.employees_view(app)),
        ("حضور و غیاب", lambda: v_attendance.attendance_view(app)),
        ("هشدارها", lambda: v_alerts.alerts_view(app)),
        ("گزارش‌ها", lambda: v_reports.reports_view(app)),
        ("مدیریت", lambda: v_management.management_view(app)),
        ("تنظیمات", lambda: v_settings.settings_view(app)),
    ]
    for eid in (1, 2, 13, 18):
        def make(eid=eid):
            app.state["emp"] = eid
            return v_detail.employee_detail_view(app)
        checks.append((f"پروفایل کارکن {eid}", make))

    fails = 0
    for name, fn in checks:
        try:
            fn()
            print(f"OK   — {name}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"FAIL — {name}: {type(e).__name__}: {e}")

    # فایل اصلی هم باید بدون خطا ایمپورت شود
    try:
        import main as app_main  # noqa: F401,E402

        assert app_main.BUILDERS
        assert "attendance" in app_main.BUILDERS
        assert "map" in app_main.BUILDERS
        print("OK   — فایل اصلی (main.py)")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"FAIL — فایل اصلی: {type(e).__name__}: {e}")

    # دادهٔ حضور و غیاب باید برای همهٔ کارکنان کامل باشد
    try:
        from data import EMPLOYEES

        assert len(EMPLOYEES) == 24, f"تعداد کارکنان: {len(EMPLOYEES)}"
        for e in EMPLOYEES:
            a = e["attendance"]
            if a["status"] in ("present", "left"):
                assert a["entered"], f'{e["name"]}: ساعت ورود خالی'
                assert a["work_min"] >= 0, f'{e["name"]}: ساعات کار منفی'
        print("OK   — دادهٔ حضور و غیاب (۲۴ کارکن)")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"FAIL — دادهٔ حضور و غیاب: {type(e).__name__}: {e}")

    # دادهٔ نقشه — مختصات نسبی معتبر و تصویر پایه در assets
    try:
        from data import MAP_GATEWAYS, MAP_IMAGE

        assert MAP_GATEWAYS, "فهرست گیت‌وی‌های نقشه خالی است"
        for g in MAP_GATEWAYS:
            assert 0 <= g["x"] <= 1 and 0 <= g["y"] <= 1, f"مختصات خارج از بازه: {g}"
            assert g.get("label"), "برچسب نشانگر خالی است"
        installed = [g for g in MAP_GATEWAYS if g.get("kind") == "installed"]
        gids = [g.get("gw") for g in installed]
        assert all(gids), "گیت‌وی نصب‌شده بدون شناسهٔ gw است"
        assert len(gids) == len(set(gids)), "شناسهٔ گیت‌وی نصب‌شده تکراری است"
        _assets = os.path.join(_HERE, "..", "src", "assets", MAP_IMAGE)
        assert os.path.exists(_assets), f"تصویر نقشه پیدا نشد: {_assets}"
        print("OK   — دادهٔ نقشهٔ کارخانه (نشانگرها و تصویر پایه)")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"FAIL — دادهٔ نقشهٔ کارخانه: {type(e).__name__}: {e}")

    # ── بخش «کارکنان» با دادهٔ زندهٔ شبیه‌سازی‌شده ──
    try:
        import components.employee_form as c_form

        stub = [
            {"mac": "f3:b6:d6:b7:47:d7", "registered": True, "name": "حمید نوری",
             "dept": "تولید روغن", "role": "خط روغن ۲", "shift": "صبح", "note": "",
             "present": True, "rssi": -70, "gw": "gw-test-1", "zone": "test",
             "last_seen": None, "last_seen_age_s": 5.0,
             "health": {"state": "done", "fail": "none", "wearing": True,
                        "ended": True, "bpm": [75, 76, 77], "n": 3, "avg": 76.0,
                        "ts": None, "age_s": 25.0},
             "vitals": {"battery": 90, "dev_fw": "2.0.2.3", "spo2": 99,
                        "spo2_ack": True, "hrv_ack": False, "hrv_frames": 0,
                        "ts": None, "age_s": 30.0, "readings_age_s": 30.0},
             "status": "ok", "issues": []},
            {"mac": "aa:bb:cc:dd:ee:01", "registered": False, "name": None,
             "dept": None, "role": None, "shift": None, "note": None, "present": True,
             "rssi": -80, "gw": "gw-test-1", "zone": "test", "last_seen": None,
             "last_seen_age_s": 9.0, "health": None, "vitals": None,
             "status": "ok", "issues": []},
        ]
        orig_emp = v_employees.live_employees
        orig_detail = v_detail.live_employees
        v_employees.live_employees = lambda force=False: stub
        v_detail.live_employees = lambda force=False: stub
        app.state["emp"] = "f3:b6:d6:b7:47:d7"
        v_employees.employees_view(app)
        v_detail.employee_detail_view(app)
        c_form.open_employee_form(app, mac="aa:bb:cc:dd:ee:01")
        v_employees.live_employees = orig_emp
        v_detail.live_employees = orig_detail
        print("OK   — کارکنان: فهرست زنده، پروفایل و فرم (شبیه‌سازی)")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"FAIL — کارکنان زنده (شبیه‌سازی): {type(e).__name__}: {e}")

    print()
    print("نتیجه:", "همهٔ صفحه‌ها سالم" if not fails else f"{fails} خطا")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
