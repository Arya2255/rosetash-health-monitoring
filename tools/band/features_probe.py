#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""کاوش قابلیت‌های دیگر مچ‌بند PDMB1062 — اکسیژن خون، HRV، قدم، باتری.

اجرا:

    .venv/bin/python features_probe.py --address F3:B6:D6:B7:47:D7

توالی کار:
  ۱. اتصال با اسکن طولانی و تلاش مجدد — مچ‌بند فقط وقتی آگهی می‌دهد که
     به میزبان دیگری وصل نباشد، پس اگر گیت‌وی مشغول باشد باید صبر کرد.
  ۲. فهرست سرویس‌ها و کاراکتریستیک‌های خواندنی + خواندن باتری استاندارد
  ۳. دست‌دادن (A7,1F) — همان که اپ پس از اتصال می‌فرستد
  ۴. اندازه‌گیری اکسیژن خون (02,70) با داده [01,02]
  ۵. اندازه‌گیری HRV (02,70) با داده [01,06]
  ۶. روشن کردن گزارش لحظه‌ای (A6,05) — قدم، باتری و ضربان لحظه‌ای

همهٔ فریم‌ها با مهر زمانی در فایل لاگ نوشته می‌شوند.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak در این محیط نصب نیست")

WRITE_UUID = "4cdabaa1-2cea-c0c1-b38d-a0481ae60a97"
NOTIFY_UUID = "4cdabaa2-2cea-c0c1-b38d-a0481ae60a97"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}"
    print(line, flush=True)
    LOG_LINES.append(line)


def crc16(data: bytes) -> int:
    i = 0xFFFF
    for b in data:
        x = ((((i << 8) & 0xFFFF) | ((i >> 8) & 0xFF)) ^ (b & 0xFF)) & 0xFFFF
        x ^= ((x & 0xFF) >> 4) & 0xFFFF
        x ^= (x << 12) & 0xFFFF
        i = (x ^ (((x & 0xFF) << 5) & 0xFFFF)) & 0xFFFF
    return i


def build(counter: int, cmd1: int, cmd2: int, payload: bytes = b"") -> bytes:
    inner = bytes([cmd1, 0x00, cmd2, (len(payload) >> 8) & 0xFF,
                   len(payload) & 0xFF]) + payload
    crc = crc16(inner)
    return bytes([0xBA, 0x21, (len(inner) >> 8) & 0xFF, len(inner) & 0xFF,
                  (crc >> 8) & 0xFF, crc & 0xFF,
                  (counter >> 8) & 0xFF, counter & 0xFF]) + inner


def decode(data: bytes) -> str:
    if len(data) < 8 or data[0] != 0xBA:
        return "(فریم فوندو نیست)"
    inner = data[8:]
    if len(inner) < 5:
        return "(بدنهٔ کوتاه)"
    c1, c2 = inner[0], inner[2]
    dlen = (inner[3] << 8) | inner[4]
    payload = inner[5:5 + dlen]
    crc_ok = crc16(inner) == ((data[4] << 8) | data[5])
    tag = f"cmd=({c1:02X},{c2:02X}) len={dlen} data={' '.join(f'{b:02X}' for b in payload)}"
    if (c1, c2) == (0x04, 0x41) and len(payload) >= 2:
        tag += f"  [باتری {payload[0]}% حالت {payload[1]}]"
    elif (c1, c2) == (0x0A, 0xAB) and payload:
        tag += f"  [ضربان لحظه‌ای {payload[0]}]"
    elif (c1, c2) == (0xA6, 0xAB) and payload:
        tag += f"  [ضربان گزارش لحظه‌ای {payload[0]}]"
    elif (c1, c2) == (0xA6, 0xAC) and len(payload) >= 3:
        tag += f"  [قدم {payload[0] | (payload[1] << 8) | (payload[2] << 16)}]"
    elif (c1, c2) in ((0x02, 0x71), (0x02, 0x72)):
        tag += f"  [{'قبول' if c1 == 2 and c2 == 0x71 else 'پایان'} نوع={list(payload)}]"
    return f"{tag}  crc={'OK' if crc_ok else 'BAD'}"


async def find(client_addr: str, scan_secs: float, tries: int):
    for n in range(1, tries + 1):
        log(f"اسکن {scan_secs:.0f} ثانیه‌ای — تلاش {n}/{tries}")
        dev = await BleakScanner.find_device_by_address(client_addr, timeout=scan_secs)
        if dev:
            log(f"پیدا شد: {dev.address} {dev.name}")
            return dev
        log("پیدا نشد — شاید گیت‌وی در همان لحظه وصل است")
    return None


async def connect_with_retry(addr: str, scan_secs: float, tries: int):
    dev = await find(addr, scan_secs, tries)
    if dev is None:
        return None
    client = BleakClient(dev, timeout=30.0)
    for attempt in range(1, 4):
        try:
            log(f"اتصال — تلاش {attempt}/3")
            await client.connect()
            log("متصل شد")
            return client
        except Exception as exc:  # noqa: BLE001
            log(f"اتصال نشد: {exc}")
            await asyncio.sleep(4)
    return None


async def enumerate_services(client: BleakClient) -> None:
    log("— سرویس‌ها و کاراکتریستیک‌ها —")
    for service in client.services:
        log(f"سرویس {service.uuid}  {service.description}")
        for ch in service.characteristics:
            props = ",".join(ch.properties)
            val = ""
            if "read" in ch.properties:
                try:
                    raw = await client.read_gatt_char(ch)
                    val = " = " + " ".join(f"{b:02X}" for b in raw)
                    if ch.uuid.lower() == BATTERY_UUID:
                        val += f"  [{raw[0]}%]"
                except Exception as exc:  # noqa: BLE001
                    val = f"  (خواندن نشد: {exc})"
            log(f"  {ch.uuid}  [{props}]{val}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default="F3:B6:D6:B7:47:D7")
    ap.add_argument("--scan", type=float, default=25.0)
    ap.add_argument("--tries", type=int, default=6)
    ap.add_argument("--spo2-secs", type=float, default=35.0)
    ap.add_argument("--hrv-secs", type=float, default=30.0)
    ap.add_argument("--realtime-secs", type=float, default=25.0)
    ap.add_argument("--log", default="")
    args = ap.parse_args()

    client = await connect_with_retry(args.address, args.scan, args.tries)
    if client is None:
        log("اتصال برقرار نشد — مچ‌بند در دسترس نبود")
        return 1

    frames: list[bytes] = []

    def on_notify(_ch, data: bytearray) -> None:
        d = bytes(data)
        frames.append(d)
        log(f"RX {' '.join(f'{b:02X}' for b in d)}   {decode(d)}")

    try:
        await enumerate_services(client)
        await client.start_notify(NOTIFY_UUID, on_notify)
        log(f"اشتراک فعال شد: {NOTIFY_UUID}")

        counter = 10
        for c1, c2, payload, note in [
            (0xA7, 0x1F, b"", "دست‌دادن پس از اتصال"),
            (0x02, 0x70, bytes([0x01, 0x02]), "شروع اندازه‌گیری اکسیژن خون"),
        ]:
            frame = build(counter, c1, c2, payload)
            counter += 1
            log(f"TX {' '.join(f'{b:02X}' for b in frame)}   <= ({c1:02X},{c2:02X}) {note}")
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
            await asyncio.sleep(1.0)

        log(f"— جمع‌آوری اکسیژن {args.spo2_secs:.0f} ثانیه —")
        await asyncio.sleep(args.spo2_secs)

        frame = build(counter, 0x02, 0x70, bytes([0x01, 0x06]))
        counter += 1
        log(f"TX {' '.join(f'{b:02X}' for b in frame)}   <= (02,70) شروع HRV")
        await client.write_gatt_char(WRITE_UUID, frame, response=False)
        log(f"— جمع‌آوری HRV {args.hrv_secs:.0f} ثانیه —")
        await asyncio.sleep(args.hrv_secs)

        frame = build(counter, 0xA6, 0x05)
        counter += 1
        log(f"TX {' '.join(f'{b:02X}' for b in frame)}   <= (A6,05) گزارش لحظه‌ای")
        await client.write_gatt_char(WRITE_UUID, frame, response=False)
        log(f"— جمع‌آوری گزارش لحظه‌ای {args.realtime_secs:.0f} ثانیه —")
        await asyncio.sleep(args.realtime_secs)
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    out = Path(args.log or f"features_probe_{datetime.now().strftime('%Y%m%d_%H%M')}.log")
    out.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    log(f"لاگ نوشته شد: {out}  —  {len(frames)} فریم")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
