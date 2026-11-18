"""Owner-only settings navigation and routes; all state/services isolated."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import flet as ft
import main as app_main
from components.sidebar import build_drawer, build_sidebar
import views.settings as settings


def walk(control):
    yield control
    content = getattr(control, 'content', None)
    if isinstance(content, ft.Control):
        yield from walk(content)
    for child in getattr(control, 'controls', None) or []:
        yield from walk(child)


def texts(control):
    return [c.value for c in walk(control) if isinstance(c, ft.Text)]


class SettingsAccessTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {'ROZTASH_CONFIG_HOME': self.folder,
                                                 'ROZTASH_VIEW': 'login'}))
        self.enterContext(patch.object(app_main.applog, 'info'))

    def app(self, role='viewer', logged_in=True, email='admin@example.test', width=1340):
        page = SimpleNamespace(web=True, width=width, height=800, update=Mock())
        app = app_main.App(page)
        app.state.update(logged_in=logged_in, role=role, admin_email=email)
        app.root = object()
        app.ui['sidebar'] = ft.Container()
        return app

    def test_settings_menu_is_hidden_for_all_roles_except_owner(self):
        for builder in (build_sidebar, build_drawer):
            for role in ('owner', 'viewer', '', 'unknown'):
                with self.subTest(builder=builder.__name__, role=role):
                    view = builder('employees', lambda _: None, role=role)
                    self.assertEqual('تنظیمات' in texts(view), role == 'owner')
                    self.assertIn('کارکنان', texts(view))

    def test_secondary_admin_cannot_enter_settings_or_render_forced_state(self):
        for role in ('viewer', '', 'unknown'):
            for width in (1340, 390):
                with self.subTest(role=role, width=width):
                    app = self.app(role, width=width)
                    builder = Mock(return_value=ft.Text('PRIVATE SETTINGS'))
                    with patch.dict(app_main.BUILDERS, {
                        'settings': builder, 'map': lambda _: ft.Text('MAP'),
                        'login': lambda _: ft.Text('LOGIN'),
                    }):
                        app.go('settings')
                        self.assertEqual(app.state['view'], 'map')
                        app.state['view'] = 'settings'
                        app.render()
                        self.assertEqual(app.state['view'], 'map')
                    builder.assert_not_called()
                    app.open_menu()
                    self.assertNotIn('تنظیمات', texts(app.page.drawer))
                    self.assertNotIn('PRIVATE SETTINGS', texts(app.content_holder.content))

    def test_owner_retains_settings_and_role_change_removes_it_on_rerender(self):
        app = self.app('owner')
        builder = Mock(return_value=ft.Text('PRIVATE SETTINGS'))
        with patch.dict(app_main.BUILDERS, {
            'settings': builder, 'map': lambda _: ft.Text('MAP'),
        }):
            app.go('settings')
            builder.assert_called_once_with(app)
            self.assertEqual(app.state['view'], 'settings')
            self.assertIn('تنظیمات', texts(app.ui['sidebar'].content))
            app.open_menu()
            self.assertIn('تنظیمات', texts(app.page.drawer))
            app.state['role'] = 'viewer'
            app.render()
            self.assertEqual(app.state['view'], 'map')
            self.assertEqual(builder.call_count, 1)
            self.assertNotIn('تنظیمات', texts(app.ui['sidebar'].content))
            app.open_menu()
            self.assertNotIn('تنظیمات', texts(app.page.drawer))

    def test_logged_out_owner_or_owner_without_identity_has_no_settings(self):
        for logged_in, email in ((False, 'owner@example.test'), (True, None), (True, ''), (True, '  ')):
            with self.subTest(logged_in=logged_in, email=email):
                app = self.app('owner', logged_in, email)
                builder = Mock(return_value=ft.Text('PRIVATE SETTINGS'))
                with patch.dict(app_main.BUILDERS, {
                    'settings': builder, 'map': lambda _: ft.Text('MAP'),
                    'login': lambda _: ft.Text('LOGIN'),
                }):
                    app.go('settings')
                    self.assertNotEqual(app.state['view'], 'settings')
                    builder.assert_not_called()
                app.open_menu()
                self.assertNotIn('تنظیمات', texts(app.page.drawer))

    def test_denied_settings_builder_returns_before_loading_private_services(self):
        for role, logged_in, email in (('viewer', True, 'viewer@example.test'),
                                       ('owner', False, 'owner@example.test'),
                                       ('owner', True, ''), ('', True, 'unknown@example.test')):
            with self.subTest(role=role, logged_in=logged_in), \
                    patch.object(settings, 'remote_status') as remote, \
                    patch.object(settings, 'list_admins') as admins, \
                    patch.object(settings, 'get_admin_name') as profile:
                app = self.app(role, logged_in, email)
                view = settings.settings_view(app)
                self.assertEqual(texts(view), [])
                self.assertFalse(any(isinstance(c, (ft.Button, ft.TextField, ft.Switch)) for c in walk(view)))
                remote.assert_not_called()
                admins.assert_not_called()
                profile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
