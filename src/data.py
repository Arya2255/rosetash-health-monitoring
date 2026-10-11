# -*- coding: utf-8 -*-
"""لایهٔ داده — تنها نقطهٔ اتصال رابط کاربری به منبع داده.

رابط کاربری (views و components) هرگز مستقیم با سخت‌افزار یا بک‌اند حرف نمی‌زند؛
همهٔ داده از این ماژول می‌آید.

فاز ۱ — داده از mock_data می‌آید (نمایشی).
فاز ۲ (شروع‌شده) — حالت زنده: پل محلی دادهٔ واقعی گیت‌وی را سرو می‌کند و
views فقط از همین ماژول می‌پرسند. اگر پل در دسترس نباشد، برنامه بدون خطا
به دادهٔ نمایشی برمی‌گردد.

بخش «کارکنان» از فاز ۲ واقعی شده است: live_employees دفتر واقعی کارکنان را
از پل می‌آورد و save_employee/delete_employee ثبت و حذف می‌کنند؛ فهرست
نمونه فقط وقتی جای آن را می‌گیرد که پل در دسترس نباشد. بخش «مچ‌بندها»
(live_bands/save_band/delete_band)، «تعاریف پایه» (live_catalogs/save_catalog/
delete_catalog) و عکس پرسنلی (photo_src) هم از همین لایه می‌آیند.
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

# ── فاز ۲: دادهٔ زندهٔ گیت‌وی از طریق پل محلی ──
# views هرگز مستقیم به live نباید وصل شوند؛ اگر به دادهٔ زندهٔ بیشتری
# نیاز باشد، تابع تازه‌ای همین‌جا ساخته می‌شود.
from live import (  # noqa: E402,F401
    delete_band,
    delete_catalog,
    delete_employee,
    live_available,
    live_bands,
    live_catalogs,
    live_employees,
    live_status,
    live_summary,
    photo_src,
    save_band,
    save_catalog,
    save_employee,
    send_vibrate,
)

# ── نقشهٔ کارخانه — تصویر پایه و موقعیت نشانگرها ──
from map_data import (  # noqa: E402,F401
    MAP_ENTRANCE, MAP_GATEWAYS, MAP_IMAGE, MAP_IMAGE_H, MAP_IMAGE_W,
)
