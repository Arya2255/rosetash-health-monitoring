#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""بازپخش رویدادهای ضبط‌شده روی بروکر — برای دمو بدون مچ‌بند.

دو حالت:

    python3 tools/replay_events.py /path/events-20261011.jsonl --speed 4
    python3 tools/replay_events.py --demo --speed 1

حالت فایل: خطوط ضبط‌شدهٔ «زمان ISO + تاپیک + payload» را با همان فاصله‌ها
و سرعت دلخواه دوباره منتشر می‌کند. حالت دمو یک اپیزود واقع‌نما می‌سازد:
حضور مچ‌بند با سیگنال متغیر و چند اندازه‌گیری ضربان.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime

DEMO_MAC = "f3:b6:d6:b7:47:d7"
DEMO_BPM = [79, 78, 77, 76, 74]


def publish(host: str, port: int, topic: str, payload: str) -> None:
    subprocess.run(
        ["mosquitto_pub", "-h", host, "-p", str(port), "-t", topic, "-m", payload],
        check=False,
    )


def parse_line(line: str):
    parts = line.strip().split(" ", 2)
    if len(parts) < 3:
        return None
    ts, topic, payload = parts
    try:
        at = datetime.fromisoformat(ts).timestamp()
    except Exception:
        at = None
    if not topic.startswith("roztash/"):
        return None
    return at, topic, payload


def replay_file(path: str, host: str, port: int, speed: float, loop: bool) -> int:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            row = parse_line(line)
            if row:
                rows.append(row)
    if not rows:
        print("هیچ رویداد قابل بازپخشی در فایل نیست")
        return 1

    sent = 0
    while True:
        prev = None
        for at, topic, payload in rows:
            if prev is not None and at is not None:
                gap = (at - prev) / max(speed, 0.1)
                if 0 < gap < 30:
                    time.sleep(gap)
            publish(host, port, topic, payload)
            sent += 1
            prev = at
        print(f"بازپخش یک دور کامل شد — {sent} پیام")
        if not loop:
            break
    return 0


def replay_demo(host: str, port: int, speed: float, rounds: int) -> int:
    """اپیزود چند دقیقه‌ای: ورود مچ‌بند، حضور، دو اندازه‌گیری، خروج."""
    gw = "gw-test-1"
    step = 10.0 / max(speed, 0.1)     # حضور هر ۱۰ ثانیه در فریمور
    uptime = 1500
    for r in range(rounds):
        print(f"اپیزود دمو {r + 1}")
        # ۹ بستهٔ حضور: سیگنال نزدیک می‌شود، می‌ماند، می‌رود
        rssis = [-88, -84, -80, -76, -73, -72, -74, -79, None]
        for rssi in rssis:
            uptime += 10
            bands = [] if rssi is None else [{"mac": DEMO_MAC, "rssi": rssi}]
            publish(host, port, f"roztash/{gw}/presence", json.dumps(
                {"gw": gw, "ts": uptime, "bands": bands, "n": len(bands)}))
            publish(host, port, f"roztash/{gw}/status", json.dumps(
                {"gw": gw, "zone": "test", "fw": "0.1.3-skeleton", "online": True,
                 "ip": "192.168.43.211", "rssi": -63, "uptime_s": uptime,
                 "bands_seen": 1, "adv_seen": 900 + uptime % 500}))
            time.sleep(step)
            if uptime % 30 == 0:
                publish(host, port, f"roztash/{gw}/health", json.dumps(
                    {"gw": gw, "mac": DEMO_MAC, "state": "done", "fail": "none",
                     "wearing": True, "ended": True, "bpm": DEMO_BPM,
                     "n": len(DEMO_BPM), "avg": round(sum(DEMO_BPM) / len(DEMO_BPM), 1)}))
        publish(host, port, f"roztash/{gw}/event", json.dumps(
            {"gw": gw, "type": "band_left", "mac": DEMO_MAC}))
    print("بازپخش دمو تمام شد")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="بازپخش رویدادها روی بروکر روزتاش")
    ap.add_argument("file", nargs="?", help="فایل jsonl ضبط‌شده")
    ap.add_argument("--demo", action="store_true", help="تولید اپیزود دموی واقع‌نما")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1884)
    ap.add_argument("--speed", type=float, default=1.0, help="ضریب سرعت، مثلاً 4")
    ap.add_argument("--loop", action="store_true", help="بازپخش فایل تا بی‌نهایت")
    ap.add_argument("--rounds", type=int, default=3, help="تعداد دور اپیزود دمو")
    args = ap.parse_args()

    if args.demo:
        return replay_demo(args.host, args.port, args.speed, args.rounds)
    if not args.file:
        ap.print_help()
        return 2
    return replay_file(args.file, args.host, args.port, args.speed, args.loop)


if __name__ == "__main__":
    sys.exit(main())
