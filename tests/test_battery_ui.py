"""Low-battery warnings rendered with real Flet controls and synthetic data."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import components.battery_alerts as ui
import views.live as live_view
import views.alerts as alerts_view


def texts(control):
    if getattr(control,'visible',True) is False:
        return []
    out=[]
    value=getattr(control,'value',None)
    if isinstance(value,str):out.append(value)
    content=getattr(control,'content',None)
    if isinstance(content,str):out.append(content)
    elif content is not None:out.extend(texts(content))
    for child in getattr(control,'controls',[]) or []:out.extend(texts(child))
    return out


ALERT={'mac':'aa:bb:cc:dd:ee:01','employee_name':'کارکن آزمایشی','battery':12,
       'vibration_status':'awaiting_ack','confirmed_at':None,'last_error':None,'age_s':5}


class BatteryUiTests(unittest.TestCase):
    def test_warning_contains_employee_percentage_and_does_not_claim_undelivered_vibration(self):
        content='\n'.join(texts(ui.battery_alert_panel([ALERT])))
        self.assertIn('کارکن آزمایشی',content)
        self.assertIn('۱۲',content)
        self.assertIn('در انتظار تأیید',content)
        self.assertNotIn('ویبره تأیید شد',content)
        confirmed='\n'.join(texts(ui.battery_alert_panel([{**ALERT,'vibration_status':'confirmed','confirmed_at':1}])))
        self.assertIn('ویبره تأیید شد',confirmed)

    def test_unavailable_gateway_does_not_hide_software_warning(self):
        content='\n'.join(texts(ui.battery_alert_panel([{**ALERT,'last_error':'gateway_update_required','vibration_status':'pending'}])))
        self.assertIn('شارژ',content)
        self.assertIn('به‌روزرسانی',content)
        self.assertEqual(texts(ui.battery_alert_panel([])),[])

    def test_both_live_and_alerts_pages_show_the_warning(self):
        doc={'ok':True,'battery_alerts':[ALERT]}
        app=SimpleNamespace(state={'view':'live'},page=SimpleNamespace(width=390,height=800,update=lambda:None),
                            siren_on=False,alerts_active=[],snack=lambda _:None,
                            set_siren=lambda _:None,close_alert=lambda _:None)
        for module,builder in ((live_view,live_view.live_view),(alerts_view,alerts_view.alerts_view)):
            with self.subTest(module=module.__name__),patch.object(module,'live_status',return_value=doc):
                content='\n'.join(texts(builder(app)))
                self.assertIn('کارکن آزمایشی',content)
                self.assertIn('در انتظار تأیید',content)


if __name__=='__main__':
    unittest.main()
