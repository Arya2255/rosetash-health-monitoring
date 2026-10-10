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

    print()
    print("نتیجه:", "همهٔ صفحه‌ها سالم" if not fails else f"{fails} خطا")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
