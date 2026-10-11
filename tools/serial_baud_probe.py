#!/usr/bin/env python3
"""کاوشگر بادریت سریال ESP32 — وقتی لاگ خروجی نامفهوم است.

چند نرخ بادریت رایج را امتحان می‌کند، برد را هر بار ریست می‌کند و
میزان خوانایی خروجی هر نرخ را نمره می‌دهد؛ بهترین را ذخیره می‌کند.

اجرا (دسترسی dialout لازم است):
    sg dialout -c ".venv/bin/python tools/serial_baud_probe.py [out_prefix]"

نکته: پایتون سیستم ممکن است pyserial نداشته باشد — از پایتون محیط پروژه
(.venv/bin/python) استفاده کنید. فریمور گیت‌وی روی 115200 لاگ می‌دهد؛
اگر 115200 نامفهوم بود و 74880 خوانا، یعنی برد در مرحلهٔ ROM مانده
(اپ بوت نشده یا در بوت‌لوپ است).
"""
import sys
import time

import serial

PORT = "/dev/ttyUSB0"
BAUDS = [115200, 74880, 230400, 460800, 921600, 57600, 9600]
OUT = sys.argv[1] if len(sys.argv) > 1 else "serial_probe"


def score(data: bytes) -> float:
    if not data:
        return 0.0
    good = sum(1 for b in data if 32 <= b < 127 or b in (10, 13, 9))
    return good / len(data)


results = {}
for baud in BAUDS:
    try:
        s = serial.Serial(PORT, baud, timeout=0.2)
    except Exception as e:
        print(f"baud {baud}: open failed: {e}")
        continue
    # ریست کلاسیک بردهای ESP32: RTS→EN، DTR→IO0
    s.dtr = False
    s.rts = True
    time.sleep(0.4)
    s.rts = False
    t0 = time.time()
    buf = b""
    while time.time() - t0 < 7:
        d = s.read(4096)
        if d:
            buf += d
    s.close()
    results[baud] = buf
    preview = (buf[:130].decode("utf-8", errors="replace")
               .replace("\r", "").replace("\n", " | "))
    print(f"baud {baud}: {len(buf)}B score={score(buf):.2f} :: {preview}")

if results:
    best = max(results, key=lambda b: score(results[b]))
    print("\nBEST:", best, "score", round(score(results[best]), 2))
    path = f"{OUT}_best_{best}.bin"
    with open(path, "wb") as f:
        f.write(results[best])
    print("saved:", path)
