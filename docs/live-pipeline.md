# پل زندهٔ داده — از مچ‌بند تا برنامه

راهنمای معماری و اجرای فاز ۲. هدف: دادهٔ واقعی گیت‌وی بدون تغییر در لایهٔ رابط کاربری به برنامه برسد.

## مسیر داده

مچ‌بند BLE → گیت‌وی (اسکن و اندازه‌گیری) → MQTT روی `roztash/#` → پل محلی → SQLite + HTTP → لایهٔ دادهٔ برنامه → صفحهٔ «پایش زنده» و نوار زندهٔ داشبورد

## اجزا

- `backend/bridge.py` — اشتراک MQTT با زیرفرایند `mosquitto_sub`، ذخیره در SQLite، سرو HTTP محلی. فقط کتابخانهٔ استاندارد.
- `src/live.py` — کلاینت محلی برنامه؛ تنها نقطهٔ تماس برنامه با پل. هرگز استثنا بیرون نمی‌دهد.
- `src/data.py` — تنها لایهٔ مجاز برای views؛ توابع زنده را از `live.py` بازصادر می‌کند.
- `src/views/live.py` — صفحهٔ «پایش زنده»: کارت‌های شاخص، نمودار سیگنال، خوراک رویداد. هر ثانیه تازه می‌شود.
- `src/views/dashboard.py` — نوار زنده در بالای داشبورد.
- `src/main.py` — نشان اتصال نوار بالا؛ از وضعیت واقعی پل پر می‌شود.
- `tools/replay_events.py` — بازپخش رویدادهای ضبط‌شده برای دمو بدون مچ‌بند.

## اجرا

۱. بروکر تست محلی (پورت ۱۸۸۴):

    mosquitto -c tools/mosquitto/mosquitto.conf

۲. پل:

    python3 backend/bridge.py

۳. برنامه:

    uv run flet run

## نقاط HTTP پل

- `GET /health` — زنده بودن پل
- `GET /api/snapshot` — تصویر کامل: `gateways`, `bands`, `health`, `events`
- `GET /api/events` — آخرین رویدادها

## قواعد زمانی

- حضور مچ‌بند: ۶۰ ثانیه — هماهنگ با TTL فریمور گیت‌وی
- آخرین اندازه‌گیری سلامت: ۱۵ دقیقه
- آنلاین بودن گیت‌وی: ۱۸۰ ثانیه بدون پیام وضعیت

## متغیرهای محیطی

- `ROZTASH_MQTT_HOST` و `ROZTASH_MQTT_PORT` — پیش‌فرض `127.0.0.1:1884`
- `ROZTASH_BRIDGE_PORT` — پیش‌فرض `8726`
- `ROZTASH_BRIDGE_DB` — پیش‌فرض `backend/state/live.db`
- `ROZTASH_PRESENCE_TTL` / `ROZTASH_HEALTH_TTL` / `ROZTASH_GATEWAY_ONLINE_TTL`
- در برنامه: `ROZTASH_LIVE=auto|1|0` و `ROZTASH_BRIDGE=http://127.0.0.1:8726`

## تست

    python3 tests/test_bridge.py          # بدون شبکه: ingest، snapshot، TTL
    uv run python scripts/smoke_ui.py     # ساخت همهٔ صفحه‌ها بدون GUI — با و بدون پل
    ROSETASH_LIVE=0 uv run python scripts/smoke_ui.py

## دمو بدون مچ‌بند

    python3 tools/replay_events.py --demo --speed 1
    python3 tools/replay_events.py /path/to/events-20261011.jsonl --speed 4

رویدادهای خام شبانه در `~/.hermes/cache/scratch/roztash-overnight/` ضبط می‌شوند.

## عیب‌یابی

- «در دید نیست» یعنی پیام حضور تازه نرسیده — مچ‌بند را نزدیک گیت‌وی بیاور.
- نشان نوار بالا خاکستری است یعنی پل جواب نمی‌دهد؛ `curl 127.0.0.1:8726/health` را چک کن.
- تداخل پورت: `ss -ltn | grep 8726` — تنها یک نمونهٔ پل باید روی پورت باشد.
- بروکر خاموش: `pgrep -af mosquitto`.

## نکتهٔ صداقت دمو

کاشی‌های داشبورد هنوز دادهٔ نمایشی‌اند؛ فقط نوار زنده و صفحهٔ «پایش زنده» از گیت‌وی واقعی تغذیه می‌شوند. در ارائه این تفاوت را شفاف بگویید.
