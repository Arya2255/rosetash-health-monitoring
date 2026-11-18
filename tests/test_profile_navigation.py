"""Profile origin and active navigation use real route and click handlers."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import flet as ft
import main as app_main
from components.sidebar import NAV_ITEMS
from theme import SIDE_ACTIVE
import views.dashboard as dashboard
import views.employees as employees
import views.employee_detail as detail


class Page:
    web = True
    width = 1340
    height = 800
    drawer = None
    def update(self):
        pass


def walk(control):
    yield control
    content = getattr(control, 'content', None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, 'controls', None) or []:
        yield from walk(child)


def texts(control):
    return [c.value for c in walk(control) if isinstance(c, ft.Text)]


def active_labels(control):
    navigation_labels = {label for _key, label, _icon in NAV_ITEMS}
    return [label for c in walk(control) if getattr(c, 'bgcolor', None) == SIDE_ACTIVE
            for label in texts(c) if label in navigation_labels]


class ProfileNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {'ROZTASH_CONFIG_HOME': self.temp, 'ROZTASH_VIEW': 'login'}))
        self.app = app_main.App(Page())
        self.app.state.update(logged_in=True, admin_email='fixture@example.test', role='owner')
        self.app.root = object()
        self.app.ui['sidebar'] = ft.Container()
        builders = {key: (lambda app: ft.Text(app.state['view'])) for key in app_main.BUILDERS}
        self.enterContext(patch.dict(app_main.BUILDERS, builders, clear=True))

    def test_origin_stays_highlighted_in_desktop_and_mobile_after_rerender(self):
        for origin, label, _icon in NAV_ITEMS:
            with self.subTest(origin=origin):
                self.app.page.width = 1340
                self.app.go(origin)
                self.app.state['back_to'] = 'dashboard' if origin != 'dashboard' else 'employees'
                self.app.go('employee', 1)
                self.assertEqual(self.app.state['back_to'], origin)
                self.assertEqual(active_labels(self.app.ui['sidebar'].content), [label])
                self.app.render()
                self.assertEqual(active_labels(self.app.ui['sidebar'].content), [label])
                self.app.page.width = 390
                self.app.on_resize()
                self.app.open_menu()
                self.assertEqual(active_labels(self.app.page.drawer), [label])

    def test_another_profile_preserves_origin_and_next_section_replaces_it(self):
        self.app.go('employees')
        self.app.go('employee', 1)
        self.app.go('employee', 2)
        self.assertEqual(self.app.state['back_to'], 'employees')
        self.app.go('dashboard')
        self.app.go('employee', 3)
        self.assertEqual(self.app.state['back_to'], 'dashboard')

    def test_no_valid_origin_falls_back_to_employees(self):
        self.app.state.update(view='login', back_to='reports')
        self.app.go('employee', 1)
        self.assertEqual(self.app.state['back_to'], 'employees')
        self.assertEqual(active_labels(self.app.ui['sidebar'].content), ['کارکنان'])

    def test_back_handler_returns_to_origin_for_demo_live_and_missing_profile(self):
        mac = 'aa:bb:cc:dd:ee:01'
        profiles = ((1, []), (mac, []), (mac, [{
            'mac': mac, 'registered': True, 'name': 'Fixture', 'status': 'off',
            'present': False, 'shift': 'صبح',
        }]))
        for origin in ('dashboard', 'employees'):
            for employee, document in profiles:
                with self.subTest(origin=origin, employee=employee, live=bool(document)), \
                        patch.object(detail, 'live_employees', return_value=document):
                    self.app.go(origin)
                    self.app.go('employee', employee)
                    view = detail.employee_detail_view(self.app)
                    back = next(c for c in walk(view) if isinstance(c, ft.IconButton)
                                and getattr(c, 'tooltip', '') == 'بازگشت')
                    back.on_click(None)
                    self.assertEqual(self.app.state['view'], origin)

    def test_dashboard_live_employee_card_preserves_dashboard_origin(self):
        mac = 'aa:bb:cc:dd:ee:01'
        person = {'mac': mac, 'registered': True, 'name': 'Fixture',
                  'status': 'danger', 'dept': 'Fixture unit', 'present': True}
        self.enterContext(patch.object(dashboard, 'live_status', return_value={
            'ok': True, 'employees': [person], 'alerts_active': []}))
        self.app.go('dashboard')
        view = dashboard.dashboard_view(self.app)
        grid = next(c for c in walk(view) if isinstance(c, ft.GridView))
        grid.controls[0].on_click(None)
        self.assertEqual(self.app.state['emp'], mac)
        self.assertEqual(self.app.state['back_to'], 'dashboard')
        self.assertEqual(active_labels(self.app.ui['sidebar'].content), ['داشبورد'])

    def test_registered_employee_row_keeps_shift_group_search_and_origin(self):
        doc = [{'mac': 'aa:bb:cc:dd:ee:01', 'registered': True, 'name': 'Fixture',
                'shift': 'عصر', 'staff_group': 'hse', 'status': 'off', 'present': False}]
        with patch.object(employees, 'live_employees', return_value=doc):
            self.app.go('employees')
            self.app.state.update(emp_shift='عصر', emp_group='hse', emp_search='Fixture')
            view = employees.employees_view(self.app)
            rows = next(c for c in walk(view) if getattr(c, 'data', None) == 'employees:list')
            rows.controls[0].on_click(None)
            self.assertEqual(self.app.state['back_to'], 'employees')
            self.app.go(self.app.state['back_to'])
            rebuilt = employees.employees_view(self.app)
            self.assertEqual(next(c for c in walk(rebuilt) if getattr(c, 'data', None) == 'employees:shift').value, 'عصر')
            self.assertEqual(next(c for c in walk(rebuilt) if getattr(c, 'data', None) == 'employees:group').value, 'hse')
            self.assertEqual(next(c for c in walk(rebuilt) if getattr(c, 'data', None) == 'employees:search').value, 'Fixture')

    def test_demo_employee_row_preserves_origin(self):
        with patch.object(employees, 'live_employees', return_value=None):
            self.app.go('employees')
            self.app.state['emp_shift'] = 'all'
            view = employees.employees_view(self.app)
            rows = next(c for c in walk(view) if getattr(c, 'data', None) == 'employees:list')
            rows.controls[0].on_click(None)
        self.assertEqual(self.app.state['back_to'], 'employees')
        self.assertEqual(active_labels(self.app.ui['sidebar'].content), ['کارکنان'])


if __name__ == '__main__':
    unittest.main()
