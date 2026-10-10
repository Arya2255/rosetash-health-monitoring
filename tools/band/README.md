# ابزارهای پروتکل مچ‌بند

اسکریپت‌های مرجع فاز ۲ — جریان کامل پروتکل در `docs/band-protocol.md`.

## نصب

```
python3 -m venv .venv
.venv/bin/pip install bleak
```

## استفاده

فرستندهٔ عمومی — هر فریم دلخواه:

```
.venv/bin/python fundo_send.py --address <MAC> --scan 15 --retry 3 \
    --cmd "02 70 01 01" --gap 25 --listen 60
```

خوانندهٔ پیوستهٔ ضربان — چند دور اندازه‌گیری + CSV:

```
.venv/bin/python hr_live.py --address <MAC> --rounds 3 --interval 30 --csv hr_log.csv
```

## نکات

- بلوتوث گوشی باید خاموش باشد — مچ‌بند هم‌زمان فقط یک اتصال می‌پذیرد و تا وقتی وصل است آگهی پخش نمی‌کند.
- روی لینوکس در صورت نیاز: `export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`
- مچ‌بند باید روی دست بسته باشد؛ وگرنه مچ‌بند پاسخ خطای پوشیده‌نبودن می‌دهد.
- نیاز به آداپتور BLE دارد — ماژول داخلی قدیمی کافی نیست.
