# ساختار اپلیکیشن روزتاش

> نقشهٔ درختی پروژه، لایه‌های نرم‌افزار و مسیر ارتباط ماژول‌ها. نسخهٔ تعاملی: `docs/app-architecture.html`

## درخت پروژه

```
rosetash-health-monitoring/
├── main.py
├── src/
│   ├── main.py
│   ├── theme.py
│   ├── layout.py
│   ├── data.py
│   ├── live.py
│   ├── mock_data.py
│   ├── map_data.py
│   ├── remote.py
│   ├── admin_roles.py
│   ├── applog.py
│   ├── email_otp.py
│   ├── provisioner.py
│   ├── components/
│   │   ├── sidebar.py
│   │   ├── common.py
│   │   ├── employee_card.py
│   │   ├── alert_banner.py
│   │   ├── employee_form.py
│   │   └── gateway_form.py
│   ├── views/
│   │   ├── login.py
│   │   ├── map.py
│   │   ├── gateways.py
│   │   ├── provisioning.py
│   │   ├── dashboard.py
│   │   ├── live.py
│   │   ├── bands.py
│   │   ├── employees.py
│   │   ├── employee_detail.py
│   │   ├── attendance.py
│   │   ├── definitions.py
│   │   ├── alerts.py
│   │   ├── reports.py
│   │   ├── management.py
│   │   ├── settings.py
│   │   └── logs.py
│   └── assets/
│       ├── fonts/
│       ├── factory-map.jpg
│       ├── logo-colored.png
│       └── logo-white.png
├── backend/
│   ├── bridge.py
│   └── state/
│       ├── live.db
│       └── photos/
├── firmware/gateway/
│   ├── gateway.ino
│   ├── ble_central.h/.cpp
│   ├── protocol.h/.cpp
│   ├── mqtt_link.h/.cpp
│   ├── config.h/.cpp
│   ├── discovery.h/.cpp
│   ├── setup_portal.h/.cpp
│   └── data/config.json
├── tools/
│   ├── band/
│   ├── band_rssi_monitor.py
│   ├── gateway_monitor.py
│   ├── replay_events.py
│   ├── discovery_udp.py
│   └── mosquitto/
├── tests/
├── distribution/gateway-provisioner/
│   └── esptool
├── docs/
└── logs/
```

## لایه‌ها

| لایه | رنگ | نقش |
| --- | --- | --- |
| رابط کاربری (Flet) | `#38bdf8` | ui |
| لایهٔ داده | `#34d399` | data |
| سرویس‌های اتصال | `#fbbf24` | integration |
| پل بک‌اند | `#a78bfa` | backend |
| فریمور گیت‌وی | `#fb7185` | firmware |
| سخت‌افزار | `#94a3b8` | hardware |
| سرویس بیرونی | `#22d3ee` | external |

## ماژول‌ها و وابستگی‌ها

| ماژول | مسیر | لایه | وابسته به |
| --- | --- | --- | --- |
| main.py | `main.py` | رابط کاربری (Flet) | src/main.py |
| src/main.py | `src/main.py` | رابط کاربری (Flet) | theme.py، data.py، applog.py، layout.py، sidebar.py، login.py، map.py، gateways.py، provisioning.py، dashboard.py، live.py، bands.py، employees.py، employee_detail.py، attendance.py، definitions.py، alerts.py، reports.py، management.py، settings.py، logs.py |
| theme.py | `src/theme.py` | رابط کاربری (Flet) | — |
| layout.py | `src/layout.py` | رابط کاربری (Flet) | — |
| sidebar.py | `src/components/sidebar.py` | رابط کاربری (Flet) | theme.py |
| common.py | `src/components/common.py` | رابط کاربری (Flet) | theme.py، data.py |
| employee_card.py | `src/components/employee_card.py` | رابط کاربری (Flet) | theme.py، common.py |
| alert_banner.py | `src/components/alert_banner.py` | رابط کاربری (Flet) | theme.py |
| employee_form.py | `src/components/employee_form.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py |
| gateway_form.py | `src/components/gateway_form.py` | رابط کاربری (Flet) | theme.py، data.py |
| login.py | `src/views/login.py` | رابط کاربری (Flet) | theme.py، remote.py، email_otp.py |
| map.py | `src/views/map.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py، gateway_form.py |
| gateways.py | `src/views/gateways.py` | رابط کاربری (Flet) | theme.py، data.py، common.py، gateway_form.py |
| provisioning.py | `src/views/provisioning.py` | رابط کاربری (Flet) | theme.py، data.py، provisioner.py، common.py، layout.py |
| dashboard.py | `src/views/dashboard.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py، employee_card.py، alert_banner.py |
| live.py | `src/views/live.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py |
| bands.py | `src/views/bands.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py، employee_form.py |
| employees.py | `src/views/employees.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py، employee_card.py، employee_form.py |
| employee_detail.py | `src/views/employee_detail.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py، employee_form.py |
| attendance.py | `src/views/attendance.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py |
| definitions.py | `src/views/definitions.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py |
| alerts.py | `src/views/alerts.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py |
| reports.py | `src/views/reports.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py |
| management.py | `src/views/management.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py |
| settings.py | `src/views/settings.py` | رابط کاربری (Flet) | theme.py، data.py، layout.py، common.py، applog.py، logs.py، admin_roles.py |
| logs.py | `src/views/logs.py` | رابط کاربری (Flet) | theme.py، applog.py، common.py، layout.py |
| data.py | `src/data.py` | لایهٔ داده | mock_data.py، live.py، map_data.py، remote.py، admin_roles.py |
| mock_data.py | `src/mock_data.py` | لایهٔ داده | — |
| map_data.py | `src/map_data.py` | لایهٔ داده | — |
| live.py | `src/live.py` | سرویس‌های اتصال | applog.py، bridge.py |
| remote.py | `src/remote.py` | سرویس‌های اتصال | applog.py، Cloudflare |
| admin_roles.py | `src/admin_roles.py` | سرویس‌های اتصال | applog.py |
| applog.py | `src/applog.py` | سرویس‌های اتصال | — |
| email_otp.py | `src/email_otp.py` | سرویس‌های اتصال | remote.py، SMTP |
| provisioner.py | `src/provisioner.py` | سرویس‌های اتصال | esptool + mklittlefs |
| bridge.py | `backend/bridge.py` | پل بک‌اند | live.db، mosquitto، UDP discovery |
| live.db | `backend/state/live.db` | پل بک‌اند | — |
| mosquitto | `tools/mosquitto/mosquitto.conf` | پل بک‌اند | — |
| UDP discovery | `tools/discovery_udp.py` | پل بک‌اند | — |
| gateway.ino | `firmware/gateway/gateway.ino` | فریمور گیت‌وی | ble_central.*، protocol.*، mqtt_link.*، config.*، discovery.*، setup_portal.* |
| ble_central.* | `firmware/gateway/ble_central.cpp` | فریمور گیت‌وی | protocol.*، مچ‌بند PDMB1062 |
| protocol.* | `firmware/gateway/protocol.cpp` | فریمور گیت‌وی | مچ‌بند PDMB1062 |
| mqtt_link.* | `firmware/gateway/mqtt_link.cpp` | فریمور گیت‌وی | mosquitto |
| config.* | `firmware/gateway/config.cpp` | فریمور گیت‌وی | — |
| discovery.* | `firmware/gateway/discovery.cpp` | فریمور گیت‌وی | UDP discovery |
| setup_portal.* | `firmware/gateway/setup_portal.cpp` | فریمور گیت‌وی | config.* |
| مچ‌بند PDMB1062 | `Porodo PDMB1062` | سخت‌افزار | ESP32 + W5500 |
| ESP32 + W5500 | `firmware/gateway` | سخت‌افزار | mosquitto |
| Cloudflare | `~/.cloudflared` | سرویس بیرونی | — |
| SMTP | `~/.cloudflared/rosetash-remote.json` | سرویس بیرونی | — |
| esptool + mklittlefs | `distribution/gateway-provisioner` | سرویس بیرونی | — |

## جریان داده

```
Band PDMB1062  --BLE-->  ESP32 gateway  --MQTT-->  mosquitto :1884
      -->  backend/bridge.py  -->  SQLite live.db
      -->  HTTP :8726/api/snapshot  -->  src/live.py  -->  src/data.py  -->  views
```

## شبکهٔ اختصاصی (تصمیم‌شده)

- رنج شبکه: `192.168.50.0/24`؛ broadcast: `192.168.50.255`.
- توپولوژی: گیتوی‌ها به سوئیچ بخش خود (فیلتر یا انبار) وصل می‌شوند؛ سوئیچ‌ها زنجیره‌ای به سوئیچ اتاق HSE وصل‌اند. یک شبکه، بدون حلقه.
- DHCP: روی کامپیوتر HSE. گیتوی‌ها IP را از آن می‌گیرند و به IP ثابت نیاز ندارند.
- بروکر MQTT (mosquitto) و پل روی کامپیوتر HSE؛ پورت MQTT: ۱۸۸۴.
- کشف خودکار (UDP): broadcast روی `192.168.50.255`.

### وضعیت مهاجرت

- فریمور فعال از ESP32-S3 و W5500 با DHCP استفاده می‌کند؛ پورتال وای‌فای حذف شده است.
- کشف بروکر در فریمور از broadcast زیرشبکهٔ واقعی و آدرس فرستندهٔ پاسخ استفاده می‌کند. سرویس Python روی رایانه به درخواست‌ها پاسخ می‌دهد.
- نشانی جایگزین بروکر در کد `192.168.50.1` است و پورت از تنظیمات خوانده می‌شود؛ پیش‌فرض ۱۸۸۴ است.
- بستهٔ جدید کامپایل شده؛ آزمون فلش و شبکهٔ نهایی و استقرار سرویس DHCP روی رایانهٔ HSE باقی است. مرجع جزئیات: `docs/ethernet-verification.md`.

## قاعدهٔ اتصال

- `views/` و `components/` فقط از `data.py` داده می‌گیرند؛ هیچ‌کدام `live.py` یا `bridge.py` را import نمی‌کنند.
- `data.py` خودش منطق ندارد و فقط بازصادر می‌کند؛ به همین دلیل جایگزینی mock با live فقط در یک فایل انجام می‌شود.
- `live.py` هرگز استثنا نمی‌دهد؛ در نبود پل `None` برمی‌گرداند و UI به دادهٔ نمایشی برمی‌گردد.
- `bridge.py` فقط کتابخانهٔ استاندارد است و قراردادش HTTP JSON روی پورت ۸۷۲۶ است.
- فریمور فقط از طریق MQTT با پل حرف می‌زند؛ قراردادش موضوع‌های `roztash/<gw>/...` و فایل `config.json` است.
