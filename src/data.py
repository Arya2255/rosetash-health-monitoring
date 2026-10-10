# -*- coding: utf-8 -*-
"""لایهٔ داده — تنها نقطهٔ اتصال رابط کاربری به منبع داده.

رابط کاربری (views و components) هرگز مستقیم با سخت‌افزار یا بک‌اند حرف نمی‌زند؛
همهٔ داده از این ماژول می‌آید.

فاز ۱ — داده از mock_data می‌آید (نمایشی).
فاز ۲ — بدنهٔ همین ماژول به کلاینت واقعی بک‌اند وصل می‌شود
(WebSocket یا API) و **هیچ فایلی از views و components تغییر نمی‌کند**؛
فقط این یک فایل عوض می‌شود.
"""

from mock_data import (  # noqa: F401
    ALERTS_ACTIVE,
    ALERTS_HISTORY,
    EMPLOYEES,
    FACTORY_ZONES,
    INCIDENT_TIME,
    TRAFFIC_TODAY,
    WEEK_HOURS,
    ZONE_COLORS,
    ZONE_GW,
    ZONE_NAMES,
    attendance_summary,
    dept_summary,
    kpis,
    zone_usage,
)
