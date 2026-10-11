# -*- coding: utf-8 -*-
"""لایهٔ داده — تنها نقطهٔ اتصال رابط کاربری به منبع داده.

رابط کاربری (views و components) هرگز مستقیم با سخت‌افزار یا بک‌اند حرف نمی‌زند؛
همهٔ داده از این ماژول می‌آید.

فاز ۱ — داده از mock_data می‌آید (نمایشی).
فاز ۲ (شروع‌شده) — حالت زنده: پل محلی دادهٔ واقعی گیت‌وی را سرو می‌کند و
views فقط از همین ماژول می‌پرسند. اگر پل در دسترس نباشد، برنامه بدون خطا
به دادهٔ نمایشی برمی‌گردد. هیچ فایلی از views و components عوض نشد؛
فقط نوار زندهٔ داشبورد اضافه شد.
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
from live import live_available, live_status, live_summary, send_vibrate  # noqa: E402,F401

# ── نقشهٔ کارخانه — تصویر پایه و موقعیت نشانگرها ──
from map_data import (  # noqa: E402,F401
    MAP_ENTRANCE, MAP_GATEWAYS, MAP_IMAGE, MAP_IMAGE_H, MAP_IMAGE_W,
)
