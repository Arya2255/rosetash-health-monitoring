"""Personnel controls with synthetic data and actual Flet event handlers."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import flet as ft
import main as app_main
import live
from bridge_auth import verify_request
from components.sidebar import NAV_ITEMS,build_sidebar,build_drawer
import components.employee_form as form
import views.employees as employees
import views.bands as bands

MAC='aa:bb:cc:dd:ee:01'


def walk(control,visible=True):
    if visible and getattr(control,'visible',True) is False:return
    yield control
    content=getattr(control,'content',None)
    if isinstance(content,ft.Control):yield from walk(content,visible)
    for attr in ('controls','actions'):
        for child in getattr(control,attr,None) or []:yield from walk(child,visible)


def text(control):
    return '\n'.join(str(v) for c in walk(control) for v in
                     (getattr(c,'value',None),getattr(c,'content',None)) if isinstance(v,str))


def tagged(control,tag):
    return next(c for c in walk(control,False) if getattr(c,'data',None)==tag)


class Page:
    width=1340
    height=850
    def __init__(self):self.dialogs=[];self.services=[]
    def show_dialog(self,dialog):self.dialogs.append(dialog)
    def pop_dialog(self):self.dialogs.pop()
    def update(self):pass


class App:
    def __init__(self,role='viewer',**state):
        self.state={'view':'employees','logged_in':True,'role':role,
                    'admin_email':'admin@example.test',**state}
        self.page=Page();self.messages=[]
    def snack(self,message):self.messages.append(message)
    def go(self,view,emp=None):self.state.update(view=view,emp=emp)


def employee(i,name,shift,group='employee'):
    return {'mac':f'aa:bb:cc:dd:ee:{i:02x}','name':name,'shift':shift,
            'staff_group':group,'registered':True,'present':False,'status':'off'}


class PersonnelUITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(form,'live_bands',return_value=[]))
        self.enterContext(patch.object(form,'live_catalogs',return_value={}))
        self.enterContext(patch.object(form,'photo_src',return_value=None))
        self.enterContext(patch.object(ft.Control,'update'))

    def test_attendance_removed_from_both_navigation_and_routes(self):
        self.assertNotIn('attendance',dict((k,l) for k,l,_ in NAV_ITEMS))
        self.assertNotIn('attendance',app_main.BUILDERS)
        for view in (build_sidebar('employees',lambda _:None),build_drawer('employees',lambda _:None)):
            self.assertNotIn('حضور و غیاب',text(view))

    def test_default_shift_and_changed_filter_compose_with_search_and_survive_rebuild(self):
        doc=[employee(1,'Morning worker','صبح'),employee(2,'Evening worker','عصر'),
             employee(3,'Night worker','شب'),employee(4,'Without shift',None),
             employee(5,'HSE worker','صبح','hse')]
        app=App()
        with patch.object(employees,'live_employees',return_value=doc):
            view=employees.employees_view(app)
            rows=tagged(view,'employees:list')
            self.assertIn('Morning worker',text(rows))
            self.assertNotIn('Evening worker',text(rows))
            shift=tagged(view,'employees:shift');shift.value='عصر';shift.on_select(SimpleNamespace(control=shift))
            self.assertIn('Evening worker',text(rows));self.assertNotIn('Morning worker',text(rows))
            rebuilt=employees.employees_view(app)
            self.assertEqual(tagged(rebuilt,'employees:shift').value,'عصر')
            shift=tagged(rebuilt,'employees:shift');shift.value='all';shift.on_select(SimpleNamespace(control=shift))
            search=tagged(rebuilt,'employees:search');search.value='Night';search.on_change(SimpleNamespace(control=search))
            self.assertIn('Night worker',text(tagged(rebuilt,'employees:list')))
            self.assertNotIn('Evening worker',text(tagged(rebuilt,'employees:list')))
            search.value='';search.on_change(SimpleNamespace(control=search))
            shift.value='unassigned';shift.on_select(SimpleNamespace(control=shift))
            self.assertEqual(sum(1 for c in tagged(rebuilt,'employees:list').controls),1)
            self.assertIn('Without shift',text(tagged(rebuilt,'employees:list')))

    def test_delete_visible_for_both_admins_and_hides_for_logged_out_user(self):
        for role in ('owner','viewer'):
            app=App(role)
            with patch.object(employees,'live_employees',return_value=[employee(1,'Test','صبح')]):
                view=employees.employees_view(app)
            button=tagged(view,'employee:delete:'+MAC)
            button.on_click(None)
            dialog=app.page.dialogs[-1]
            self.assertIn('غیرفعال',text(dialog))
            with patch.object(form,'delete_employee',return_value=(True,'')) as delete:
                tagged(dialog,'employee:confirm-delete').on_click(None)
                delete.assert_called_once_with(MAC,actor='admin@example.test')
        app=App(logged_in=False)
        with patch.object(employees,'live_employees',return_value=[employee(1,'Test','صبح')]):
            view=employees.employees_view(app)
        self.assertFalse(any(getattr(c,'data',None)=='employee:delete:'+MAC for c in walk(view)))

    def test_failed_delete_stays_open_and_stale_logout_does_not_delete(self):
        app=App()
        dlg=form.open_delete_confirm(app,employee(1,'Test','صبح'))
        with patch.object(form,'delete_employee',return_value=(False,'خطای آزمایشی')) as delete:
            tagged(dlg,'employee:confirm-delete').on_click(None)
            self.assertEqual(len(app.page.dialogs),1)
            self.assertIn('خطای آزمایشی',text(dlg))
            app.state['logged_in']=False
            tagged(dlg,'employee:confirm-delete').on_click(None)
            self.assertEqual(delete.call_count,1)

    def test_staff_group_options_saved_for_every_admin_without_changing_role(self):
        for role in ('owner','viewer'):
            for group in ('employee','hse','supervisor','shift_leader'):
                with self.subTest(role=role,group=group):
                    app=App(role)
                    dlg=form.open_employee_form(app,mac=MAC)
                    field=tagged(dlg,'employee:staff-group')
                    self.assertEqual({o.key for o in field.options},{'employee','hse','supervisor','shift_leader'})
                    field.value=group
                    next(c for c in walk(dlg) if getattr(c,'label',None)=='نام و نام خانوادگی').value='Test person'
                    with patch.object(form,'save_employee',return_value=(True,'')) as save, \
                            patch.object(form,'save_employee_monitoring',return_value=(True,'')):
                        dlg.actions[-1].on_click(None)
                        self.assertEqual(save.call_args.args[0]['staff_group'],group)
                    self.assertEqual(app.state['role'],role)
        dlg=form.open_employee_form(App(),emp=employee(1,'Existing','صبح','shift_leader'))
        self.assertEqual(tagged(dlg,'employee:staff-group').value,'shift_leader')

    def test_inactive_filter_uses_assignment_not_radio_reachability(self):
        doc=[{'mac':MAC,'label':'Assigned offline','employee_name':'Person','in_view':False,'registered':True},
             {'mac':'aa:bb:cc:dd:ee:02','label':'Released nearby','employee_name':None,'in_view':True,'registered':True}]
        with patch.object(bands,'live_bands',return_value=doc):
            view=bands.bands_view(App(view='bands'))
        field=tagged(view,'bands:assignment-filter');field.value='inactive';field.on_select(SimpleNamespace(control=field))
        shown=text(tagged(view,'bands:list'))
        self.assertIn('Released nearby',shown);self.assertNotIn('Assigned offline',shown)
        field.value='active';field.on_select(SimpleNamespace(control=field))
        shown=text(tagged(view,'bands:list'))
        self.assertIn('Assigned offline',shown);self.assertNotIn('Released nearby',shown)


class BandScanUiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = App('owner', view='bands')
        self.tasks = []
        self.gate = threading.Event()
        self.started = threading.Event()
        def schedule(handler):
            task = asyncio.create_task(handler())
            self.tasks.append(task)
            return task
        self.app.page.run_task = schedule
        self.dialog = bands.open_band_form(self.app)

    async def asyncTearDown(self):
        self.gate.set()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def scan_result(self, *, actor):
        self.started.set()
        if not self.gate.wait(3):
            raise RuntimeError('Test scan gate was not released')
        return True, [{'mac': MAC, 'name': 'Synthetic band', 'rssi': -50}]

    async def start_scan(self):
        tagged(self.dialog, 'ble:scan').on_click(None)
        self.assertTrue(await asyncio.to_thread(self.started.wait, 2))

    async def test_owner_scan_selects_mac_but_waits_for_explicit_save(self):
        with patch.object(bands, 'scan_local_ble', side_effect=self.scan_result) as scan, \
                patch.object(bands, 'save_band', return_value=(True, '')) as save:
            await self.start_scan()
            self.assertTrue(tagged(self.dialog, 'ble:scan').disabled)
            self.gate.set()
            await asyncio.gather(*self.tasks)
            scan.assert_called_once_with(actor='admin@example.test')
            select = tagged(self.dialog, 'ble:select:' + MAC)
            select.on_click(None)
            self.assertEqual(next(c for c in walk(self.dialog) if getattr(c, 'label', '') == 'مک مچ‌بند').value, MAC)
            save.assert_not_called()
            self.dialog.actions[-1].on_click(None)
            self.assertEqual(save.call_args.args[0]['mac'], MAC)

    async def test_duplicate_events_do_not_schedule_second_scan(self):
        with patch.object(bands, 'scan_local_ble', side_effect=self.scan_result) as scan:
            await self.start_scan()
            tagged(self.dialog, 'ble:scan').on_click(None)
            await asyncio.sleep(.02)
            self.assertEqual(scan.call_count, 1)

    async def test_closed_dialog_ignores_delayed_scan_completion(self):
        with patch.object(bands, 'scan_local_ble', side_effect=self.scan_result):
            await self.start_scan()
            self.dialog.actions[0].on_click(None)
            self.gate.set()
            await asyncio.gather(*self.tasks)
        self.assertFalse(any(str(getattr(c, 'data', '')).startswith('ble:result:') for c in walk(self.dialog)))

    async def test_secondary_admin_and_logged_out_owner_have_no_scan_control(self):
        for role, logged_in in (('viewer', True), ('owner', False)):
            dialog = bands.open_band_form(App(role, logged_in=logged_in))
            self.assertFalse(any(getattr(c, 'data', None) == 'ble:scan' for c in walk(dialog)))

    async def test_scan_error_is_visible_and_button_can_retry(self):
        with patch.object(bands, 'scan_local_ble', return_value=(False, 'خطای آزمایشی دانگل')):
            tagged(self.dialog, 'ble:scan').on_click(None)
            await asyncio.gather(*self.tasks)
        self.assertIn('خطای آزمایشی دانگل', text(self.dialog))
        self.assertFalse(tagged(self.dialog, 'ble:scan').disabled)


class DeletionClientTests(unittest.TestCase):
    def test_scan_request_is_signed_and_does_not_save_selected_devices(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ROZTASH_BRIDGE_AUTH_FILE': str(Path(tmp)/'key')}), \
                patch.object(live, 'MODE', 'auto'):
            def accept(request, timeout):
                path = urllib.parse.urlsplit(request.full_url).path
                self.assertEqual(request.get_method(), 'GET')
                self.assertEqual(path, '/api/bands/scan')
                self.assertEqual(verify_request('GET', path, b'', dict(request.header_items())), 'admin@example.test')
                return io.BytesIO(json.dumps({'ok': True, 'devices': [{'mac': MAC, 'name': 'Synthetic band', 'rssi': -40}]}).encode())
            with patch.object(live.urllib.request, 'urlopen', side_effect=accept) as fetch, \
                    patch.object(live, 'save_band') as save:
                ok, result = live.scan_local_ble(actor='admin@example.test')
            self.assertTrue(ok)
            self.assertEqual(result[0]['mac'], MAC)
            fetch.assert_called_once()
            save.assert_not_called()

    def test_scan_permission_network_error_and_disabled_mode_remain_distinct(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ROZTASH_BRIDGE_AUTH_FILE': str(Path(tmp)/'key')}), \
                patch.object(live, 'MODE', 'auto'):
            error = urllib.error.HTTPError('http://localhost/api/bands/scan', 403, 'Forbidden', {},
                                           io.BytesIO(b'{"ok":false,"error":"forbidden"}'))
            with patch.object(live.urllib.request, 'urlopen', side_effect=error):
                ok, message = live.scan_local_ble(actor='admin@example.test')
            self.assertFalse(ok)
            self.assertIn('ادمین اصلی', message)
            with patch.object(live.urllib.request, 'urlopen', side_effect=OSError('unreachable')):
                ok, message = live.scan_local_ble(actor='admin@example.test')
            self.assertFalse(ok)
            self.assertIn('پاسخ نداد', message)
            with patch.object(live, 'MODE', '0'), patch.object(live.urllib.request, 'urlopen') as fetch:
                ok, message = live.scan_local_ble(actor='admin@example.test')
            self.assertFalse(ok)
            fetch.assert_not_called()

    def test_delete_is_signed_and_permission_error_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'ROZTASH_BRIDGE_AUTH_FILE':str(Path(tmp)/'key')}), \
                patch.object(live,'MODE','auto'):
            def accept(request,timeout):
                parsed=urllib.parse.urlsplit(request.full_url);path=parsed.path+'?'+parsed.query
                self.assertEqual(verify_request('DELETE',path,b'',dict(request.header_items())),'admin@example.test')
                return io.BytesIO(b'{"ok":true}')
            with patch.object(live.urllib.request,'urlopen',side_effect=accept):
                self.assertEqual(live.delete_employee(MAC,actor='admin@example.test'),(True,''))
            error=urllib.error.HTTPError('http://localhost/api/employees',403,'Forbidden',{},
                                          io.BytesIO(b'{"ok":false,"error":"forbidden"}'))
            with patch.object(live.urllib.request,'urlopen',side_effect=error):
                ok,msg=live.delete_employee(MAC,actor='admin@example.test')
                self.assertFalse(ok);self.assertNotEqual(msg,'پل پاسخ نداد')


if __name__=='__main__':unittest.main()
