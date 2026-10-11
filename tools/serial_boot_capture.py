#!/usr/bin/env python3
"""گرفتن لاگ بوت برد گیت‌وی — ریست سخت‌افزاری + خواندن سریال.

درگاه /dev/ttyUSB0 را با 115200 باز می‌کند، برد را از طریق مدار ریستِ
خودکار (RTS→EN) ریست می‌کند و ۲۲ ثانیه سریال را با مهر زمانی ذخیره
می‌کند. نه تغییر باودی وسط کار، نه استاب esptool.

نیاز به pyserial دارد (روی پایتون سیستم نصب است).

اجرا:
    sg dialout -c "python3 tools/serial_boot_capture.py boot.log"

خروجی مفید داخل لاگ:
    [cfg] loaded: ... broker=...     ← کانفیگ واقعی روی برد
    [gw] wifi: <ip> | not connected  ← نتیجهٔ اتصال وای‌فای
    [mqtt] connected to ...          ← اتصال به بروکر
    E (....) wifi:sta is connecting  ← گیر کردن در اتصال (باند اشتباه؟)
"""
import sys
import time

import serial

PORT = "/dev/ttyUSB0"
OUT = sys.argv[1] if len(sys.argv) > 1 else "serial_boot.log"

s = serial.Serial(PORT, 115200, timeout=0.25)
# Hardware reset through the classic two-transistor auto-reset circuit:
# RTS asserted -> EN low (chip held in reset); release -> boots.
s.dtr = False          # keep IO0 high (normal boot, not download mode)
s.rts = True           # EN -> low
time.sleep(0.45)
s.rts = False          # EN -> high, chip boots
t0 = time.time()

with open(OUT, "wb") as f:
    while time.time() - t0 < 22:
        data = s.read(4096)
        if data:
            f.write(data)
            f.flush()
            print(f"[{time.time()-t0:5.2f}s] +{len(data)}B", flush=True)
s.close()
print("capture complete ->", OUT)
