"""Persistent in-app low-battery panel; delivery is not confused with confirmation."""
import flet as ft

from theme import FONT, FONT_B, INK, TEXT_MUTED, WARN, fa_num, txt
from components.common import card

_ERRORS = {
    'gateway_update_required': 'برای ویبرهٔ خودکار، فریمور گیتوی باید به‌روزرسانی شود',
    'gateway_unavailable': 'گیتوی در دسترس نیست؛ ویبره هنوز تأیید نشده',
    'band_unavailable': 'مچ‌بند در دسترس نیست؛ ویبره هنوز تأیید نشده',
    'policy_unavailable': 'در انتظار مجوز فعال پایش گیتوی',
    'publish_failed': 'ارسال فرمان ناموفق بود؛ هشدار شارژ همچنان فعال است',
    'command_rejected': 'گیتوی فرمان را رد کرد؛ ویبره تأیید نشده',
    'vibration_failed': 'اجرای ویبره ناموفق بود',
    'ack_not_received': 'پاسخ تأیید ویبره دریافت نشد',
}


def battery_delivery_text(alert):
    state = alert.get('vibration_status')
    if state == 'confirmed' and alert.get('confirmed_at') is not None:
        return 'ویبره تأیید شد — لطفاً مچ‌بند شارژ شود'
    error = alert.get('last_error')
    if error in _ERRORS:
        return _ERRORS[error]
    return {
        'pending': 'در صف ارسال ویبرهٔ هشدار',
        'dispatching': 'در حال ارسال فرمان ویبره',
        'awaiting_ack': 'فرمان ارسال شد — در انتظار تأیید ویبره',
        'unconfirmed': 'پاسخ تأیید ویبره دریافت نشد',
        'failed': 'ویبره تأیید نشده؛ وضعیت مچ‌بند را بررسی کنید',
    }.get(state, 'ویبره هنوز تأیید نشده است')


def battery_alert_panel(alerts):
    rows=[]
    for alert in alerts or []:
        name=alert.get('employee_name') or alert.get('mac') or 'کارکن'
        level=alert.get('battery')
        rows.append(ft.Row([
            ft.Icon(ft.Icons.BATTERY_ALERT, size=22, color=WARN),
            ft.Column([
                txt(f'{name} — شارژ مچ‌بند {fa_num(level)}٪', size=14, font=FONT_B, color=INK),
                txt(battery_delivery_text(alert), size=12, font=FONT, color=TEXT_MUTED),
            ], spacing=4, expand=True),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START))
    return card(ft.Column([
        txt('هشدار شارژ کم مچ‌بند', size=15, font=FONT_B, color=INK),
        *rows,
    ], spacing=12), bg='#FCF0DC', pad=16, visible=bool(rows))
