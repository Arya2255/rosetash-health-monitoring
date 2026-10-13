# سامانه پایش سلامت کارکنان — کارخانه روزتاش

نمونهٔ اولیهٔ رابط کاربری (UI/UX) — فاز ۱ طراحی.

پایش لحظه‌ای ضربان قلب، اکسیژن خون، موقعیت و تشخیص سقوط کارکنان از طریق مچ‌بند BLE،
همراه با ثبت تردد، حضور و غیاب، ساعات کار، تاریخچهٔ مکان، هشدار و آژیر اورژانسی
و گزارش‌گیری ساعتی تا سالیانه.

## اجرا

اجرای دسکتاپ:

    uv run flet run

اجرای نسخهٔ وب:

    uv run flet run --web --port 8550

باز کردن مستقیم روی نمای پایش زنده (مناسب نمایشگر کنار خط تولید):

    ROZTASH_VIEW=live uv run flet run

## ساختار

    src/
      main.py            پوستهٔ برنامه، مسیریابی و ساعت زنده
      theme.py           سیستم طراحی (برند موتوسل، وزیرمتن، تاریخ شمسی)
      data.py            لایهٔ داده — تنها نقطهٔ اتصال رابط کاربری به داده
      mock_data.py       دادهٔ نمایشی — ۲۴ کارکن، حضور و غیاب، تاریخچهٔ مکان
      components/        کامپوننت‌های مشترک (نوار کناری، کارت کارکن، …)
      views/             هشت صفحه: داشبورد، کارکنان، حضور و غیاب، پروفایل، هشدارها، گزارش‌ها، مدیریت، تنظیمات
    assets/              لوگوی موتوسل و فونت وزیرمتن
    DESIGN.md            مستندات UI/UX و سیستم طراحی
    docs/band-protocol.md   پروتکل BLE مچ‌بند — خروجی مهندسی معکوس
    docs/gateway-design.md  طراحی گیتوی ESP32 — فاز ۲
    firmware/gateway/       اسکلت فریمور گیتوی ESP32 (Arduino + NimBLE)
    firmware/test/          تست طلایی لایهٔ پروتکل روی لپ‌تاپ
    tools/band/             ابزارهای مرجع پروتکل مچ‌بند (فاز ۲)

## جدایی رابط کاربری از بک‌اند

- `views/` و `components/` هیچ‌وقت مستقیم به داده وصل نمی‌شوند؛ همهٔ داده از `data.py` می‌آید.
- در فاز ۲ فقط بدنهٔ `data.py` به کلاینت واقعی بک‌اند (WebSocket یا API) وصل می‌شود
  و هیچ فایلی از رابط کاربری تغییر نمی‌کند.

## اسکرین‌شات خودکار (حالت توسعه)

تور خودکار همهٔ صفحه‌ها:

    ROSETASH_SHOT_DIR=/tmp/shots uv run flet run

برای تصویر تمام‌صفحه در نمایشگر بلندتر (Xvfb):

    ROSETASH_SHOT_DIR=/tmp/shots ROSETASH_SHOT_H=2750 \
      xvfb-run -a -s "-screen 0 1440x2900x24" uv run flet run

## تست‌ها

    python3 tests/test_bridge.py         # پل زنده: ورود داده، تصویر، TTL
    bash firmware/test/run_host_test.sh  # لایهٔ پروتکل مچ‌بند (تست طلایی)
    uv run python scripts/smoke_ui.py    # ساخت همهٔ صفحه‌ها بدون رابط گرافیکی

## وضعیت

- فاز ۲ شروع شده: پل زندهٔ گیت‌وی فعال است و صفحهٔ «پایش زنده» دادهٔ واقعی مچ‌بند را نشان می‌دهد
- فِرمویر گیت‌وی ۰٫۱٫۴: باتری، اطلاعات دستگاه، اکسیژن خون و HRV به گیت‌وی اضافه شده‌اند؛
  مرحله‌های اکسیژن و HRV هر پنج پنجرهٔ سلامت یک‌بار اجرا می‌شوند (باتری هر پنجره خوانده می‌شود)
- کاشی‌های داشبورد هنوز دادهٔ نمایشی‌اند؛ مسیر دادهٔ زنده در `docs/live-pipeline.md` توضیح داده شده
- طراحی کامل در `DESIGN.md` مستند شده است
- اسکرین‌شات‌های تأییدشدهٔ همهٔ صفحه‌ها در پوشهٔ `screenshots/` — تازه‌ترین تور در `screenshots/live/`

## نصب و اجرای آنلاین (دسترسی از اینترنت)

برای اینکه اپ از هر جایی با آدرس اینترنتی در دسترس باشد، این ۴ مرحله لازم است:

### ۱. نصب پیش‌نیازها

```bash
# flet — اگر نصب نیست
pip install flet

# cloudflare tunnel — دانلود از github.com/cloudflare/cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
```

### ۲. تنظیم توکن API کلادفلر

فایل `.cloudflared/rosetash-cf-api-token` را از این پروژه کپی کن:

```bash
mkdir -p ~/.cloudflared
# توکن را در این فایل ذخیره کن
nano ~/.cloudflared/rosetash-cf-api-token
```

### ۳. اجرای اپ به عنوان وب‌سرور

```bash
# با virtualenv پروژه
cd rosetash-health-monitoring
source .venv/bin/activate  # یا: uv run

flet run -r --web --port 8550 src/main.py
```

### ۴. راه‌اندازی تونل کلادفلر

```bash
# اگر فایل توکن تونل نداری، از inside برنامه بساز
# ویا دستی:
source ~/.cloudflared/rosetash-tunnel.env
cloudflared tunnel run
```

پس از اجرای این ۴ مرحله، اپ در آدرس `https://panel.rosetash-moe.ir` آنلاین می‌شود.

---

### عیب‌یابی

- **سایت باز نمی‌شود:** مطمئن شو اپ روی پورت 8550 در حال اجراست → `curl http://127.0.0.1:8550`
- **تونل وصل نیست:** لاگ رو چک کن → `tail ~/.cloudflared/rosetash-tunnel.log`
- **DNS خطا می‌دهد:** DNS را روی Google DNS تنظیم کن → `8.8.8.8`

#تگ‌ها #پروژه #روزتاش #Flet
