#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست لایهٔ پل زنده — بدون شبکه و بدون MQTT.

با python3 ساده اجرا می‌شود؛ فقط کتابخانهٔ استاندارد لازم است:

    python3 tests/test_bridge.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import bridge  # noqa: E402

NOW = 1_700_000_000.0
GW = "gw-test-1"
MAC = "f3:b6:d6:b7:47:d7"


def main() -> None:
    bridge.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="bridge-test-"), "live.db")

    bridge.ingest(f"roztash/{GW}/status", json.dumps({
        "gw": GW, "zone": "test", "fw": "0.1.3-skeleton", "online": True,
        "ip": "192.168.43.211", "rssi": -61, "uptime_s": 1200,
        "bands_seen": 1, "adv_seen": 1670}), recv_ts=NOW - 5)
    bridge.ingest(f"roztash/{GW}/presence", json.dumps({
        "gw": GW, "ts": 1000, "bands": [{"mac": MAC, "rssi": -72}], "n": 1}),
        recv_ts=NOW - 10)
    bridge.ingest(f"roztash/{GW}/presence", json.dumps({
        "gw": GW, "ts": 1010, "bands": [], "n": 0}), recv_ts=NOW - 9)
    bridge.ingest(f"roztash/{GW}/health", json.dumps({
        "gw": GW, "mac": MAC, "state": "done", "fail": "none", "wearing": True,
        "ended": True, "bpm": [79, 78, 77, 76, 74], "n": 5, "avg": 76.8}),
        recv_ts=NOW - 30)
    bridge.ingest(f"roztash/{GW}/event", json.dumps({
        "gw": GW, "type": "measure_ok", "mac": MAC}), recv_ts=NOW - 30)

    snap = bridge.snapshot(now=NOW)
    assert snap["ok"] is True
    assert len(snap["gateways"]) == 1 and snap["gateways"][0]["online"] is True
    assert snap["gateways"][0]["fw"] == "0.1.3-skeleton"
    assert len(snap["bands"]) == 1 and snap["bands"][0]["mac"] == MAC
    assert snap["bands"][0]["rssi"] == -72
    assert len(snap["health"]) == 1 and snap["health"][0]["avg"] == 76.8
    assert snap["health"][0]["bpm"][0] == 79 and snap["health"][0]["wearing"] is True
    kinds = {e["kind"] for e in snap["events"]}
    assert {"status", "presence", "health", "measure_ok"} <= kinds

    # TTL حضور: ۶۰ ثانیه — بعد از ۱۲۰ ثانیه باید خالی شود
    snap2 = bridge.snapshot(now=NOW + 120)
    assert snap2["bands"] == [], "presence TTL کار نکرد"
    assert snap2["gateways"][0]["online"] is True, "گیتوی تا ۱۸۰ ثانیه باید آنلاین بماند"
    assert snap2["health"][0]["avg"] == 76.8, "TTL سلامت نباید ۱۵ دقیقه‌ای پاک شود"

    snap2b = bridge.snapshot(now=NOW + 220)
    assert snap2b["gateways"][0]["online"] is False, "آستانهٔ آنلاین گیتوی کار نکرد"

    # TTL سلامت: ۱۵ دقیقه
    snap3 = bridge.snapshot(now=NOW + 1000)
    assert snap3["health"] == [], "health TTL کار نکرد"

    print("bridge tests PASSED — ingest/snapshot/TTL")


if __name__ == "__main__":
    main()
