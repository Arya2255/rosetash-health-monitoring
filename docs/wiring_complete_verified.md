# نقشه اتصالات ESP32 + W5500 + DHT22 + منبع تغذیه

## منابع معتبر

1. **W5500:** GitHub - Teja-Tatimatla/esp32-w5500-driver
2. **DHT22:** Adafruit Learning System - DHT Sensors
3. **تغذیه:** Espressif ESP32-DevKitC V4 Documentation

---

## ۱. اتصال منبع تغذیه

```
منبع تغذیه 5V/2A:
  ├── سیم قرمز (مثبت) → ESP32 پایه 5V (گوشه راست-پایین)
  └── سیم سیاه (منفی) → ESP32 پایه GND (هر کدام)

⚠️ هشدار: هرگز USB و منبع خارجی را همزمان وصل نکنید!
منبع: Espressif ESP32-DevKitC V4 - خط ۱۳
```

---

## ۲. اتصال W5500 به ESP32

```
W5500 پایه    →    ESP32 پایه    →    توضیح
─────────────────────────────────────────────────
VCC          →    3.3V         →    ⚠️ نه 5V
GND          →    GND          →    مشترک
MOSI         →    GPIO23       →    SPI MOSI (VSPI)
RESET        →    GPIO22       →    ریست ماژول
CS           →    GPIO21       →    ⚠️ نه GPIO5!
MISO         →    GPIO19       →    SPI MISO (VSPI)
SCLK         →    GPIO18       →    SPI Clock (VSPI)
INT          →    GPIO4        →    اختیاری
```

**منبع:** GitHub - Teja-Tatimatla/esp32-w5500-driver  
**جدول Wiring:** خط ۱۹۱-۲۰۶

**نکته مهم:**
- GPIO5 یه strapping pin است و ممکنه در بوت مشکل ایجاد کنه
- GPIO21 بی‌خطرترین پایه برای CS هست

---

## ۳. اتصال DHT22 به ESP32

```
DHT22 پایه    →    رنگ سیم       →    ESP32 پایه
──────────────────────────────────────────────────
Pin 1 (VCC)   →    قرمز         →    3.3V
Pin 2 (DATA)  →    سفید/زرد     →    GPIO32
Pin 3 (NC)    →    -            →    بدون اتصال
Pin 4 (GND)   →    سیاه         →    GND
```

**منبع:** Adafruit Learning System - Connecting to a DHTxx Sensor  
**آدرس:** https://learn.adafruit.com/dht/connecting-to-a-dhtxx-sensor

**⚠️ نکته مهم:**
```
باید یک مقاومت 10kΩ بین VCC و DATA وصل کنی!
(Pull-up resistor)

مدار:
  VCC ─── 10kΩ ─── DATA
         │
         └─── به GPIO32
```

**از Adafruit:**
> "یک مقاومت 10kΩ بین VCC و DATA وصل کنید"
> "Arduino pull-up داخلی داره، ولی ضعیفه"
> "بعضی DHT22 ها مقاومت داخلی دارن، ولی اضافه کردن مشکلی نداره"

---

## ۴. تضاد پایه‌ها

✅ **بدون تضاد** با این پیکربندی:

```
ESP32 GPIO Assignment:
├─ SPI Bus (VSPI)
│  ├─ GPIO18: SCK (W5500)
│  ├─ GPIO19: MISO (W5500)
│  ├─ GPIO23: MOSI (W5500)
│  ├─ GPIO21: CS (W5500) ⚠️
│  └─ GPIO22: RESET (W5500)
│
├─ DHT22
│  └─ GPIO32: DATA + Pull-up 10kΩ
│
├─ Interrupt (اختیاری)
│  └─ GPIO4: INT (W5500)
│
└─ تغذیه
   ├─ 3.3V: DHT22, W5500
   └─ 5V: منبع تغذیه خارجی
```

---

## ۵. نکات ایمنی

⚠️ **تغذیه:**
- هرگز USB و منبع خارجی همزمان وصل نشه
- W5500 حتماً 3.3V (نه 5V)

⚠️ **Pull-up resistor:**
- DHT22 نیاز به 10kΩ بین VCC و DATA داره
- بدون مقاومت کار نمی‌کنه

⚠️ **پایه‌های ممنوعه:**
- GPIO6-11: Flash memory
- GPIO0, 2, 12: Strapping pins
- GPIO34-39: Input-only

---

## ۶. فایل‌های مرتبط

```
نقشه گرافیکی: /docs/wiring_diagram_verified.svg
تحقیق W5500: /home/alireza/esp32-w5500-dht22-connections.md
تحقیق تغذیه: /home/alireza/esp32-power-supply-research.md
```

---

## ۷. مراحل اجرا

1. ✅ همه GNDها رو مشترک کن
2. ✅ VCC رو به 3.3V وصل کن (نه 5V)
3. ✅ سیم‌های SPI رو کوتاه بکش (< 10cm)
4. ✅ Pull-up resistor 10kΩ بین VCC و DATA بذار
5. ✅ منبع تغذیه رو وصل کن (USB قطع!)
6. ✅ برنامه تست رو آپلود کن

---

**تاریخ:** 2026-10-13  
**تهیه شده با منابع معتبر** ✅
