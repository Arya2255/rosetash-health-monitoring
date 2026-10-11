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
    bridge.ingest(f"roztash/{GW}/vitals", json.dumps({
        "gw": GW, "mac": MAC, "battery": 90, "dev_fw": "2.0.2.3",
        "dev_hw": "1.0.0.0", "dev_maker": "Beijing OnMicro Electronics Co., Ltd.",
        "spo2_ack": False, "hrv_ack": False, "spo2_raw": [], "hrv_raw": []}),
        recv_ts=NOW - 28)
    # پنجرهٔ حیاتی‌ها: اکسیژن و HRV پذیرفته شد
    bridge.ingest(f"roztash/{GW}/vitals", json.dumps({
        "gw": GW, "mac": MAC, "battery": 89, "dev_fw": "2.0.2.3",
        "spo2_ack": True, "hrv_ack": True, "spo2_raw": ["0AB2:001A0A0B022C2D"],
        "hrv_raw": []}), recv_ts=NOW - 26)
    # پنجرهٔ بعدی بدون مرحلهٔ حیاتی‌ها — نباید وضعیت را پاک کند
    bridge.ingest(f"roztash/{GW}/vitals", json.dumps({
        "gw": GW, "mac": MAC, "battery": 90, "dev_fw": "2.0.2.3",
        "spo2_ack": False, "hrv_ack": False, "spo2_raw": [], "hrv_raw": []}),
        recv_ts=NOW - 24)

    snap = bridge.snapshot(now=NOW)
    assert snap["ok"] is True
    assert len(snap["gateways"]) == 1 and snap["gateways"][0]["online"] is True
    assert snap["gateways"][0]["fw"] == "0.1.3-skeleton"
    assert len(snap["bands"]) == 1 and snap["bands"][0]["mac"] == MAC
    assert snap["bands"][0]["rssi"] == -72
    assert len(snap["health"]) == 1 and snap["health"][0]["avg"] == 76.8
    assert snap["health"][0]["bpm"][0] == 79 and snap["health"][0]["wearing"] is True
    assert len(snap["vitals"]) == 1 and snap["vitals"][0]["battery"] == 90
    assert snap["vitals"][0]["dev_fw"] == "2.0.2.3"
    assert snap["vitals"][0]["mac"] == MAC
    # آخرین پنجره دادهٔ اکسیژن نداشت — از پنجرهٔ قبل پر می‌شود
    assert snap["vitals"][0]["spo2_ack"] is True, "وضعیت اکسیژن باید از پنجرهٔ قبل بیاید"
    assert snap["vitals"][0]["spo2_raw"][0].startswith("0AB2:")
    assert snap["vitals"][0]["vitals_age_s"] >= 25
    kinds = {e["kind"] for e in snap["events"]}
    assert {"status", "presence", "health", "vitals", "measure_ok"} <= kinds

    # TTL حضور: ۶۰ ثانیه — بعد از ۱۲۰ ثانیه باید خالی شود
    snap2 = bridge.snapshot(now=NOW + 120)
    assert snap2["bands"] == [], "presence TTL کار نکرد"
    assert snap2["gateways"][0]["online"] is True, "گیتوی تا ۱۸۰ ثانیه باید آنلاین بماند"
    assert snap2["health"][0]["avg"] == 76.8, "TTL سلامت نباید ۱۵ دقیقه‌ای پاک شود"

    snap2b = bridge.snapshot(now=NOW + 220)
    assert snap2b["gateways"][0]["online"] is False, "آستانهٔ آنلاین گیت‌وی کار نکرد"

    # پیام LWT (آفلاین) — بازپخش retained بعد از ری‌استارت پل نباید آنلاین بسازد
    bridge.ingest(f"roztash/{GW}/status", json.dumps({"gw": GW, "online": False}),
                  recv_ts=NOW + 230)
    snap_lwt = bridge.snapshot(now=NOW + 231)
    assert snap_lwt["gateways"][0]["online"] is False, "LWT نباید وضعیت آنلاین بسازد"
    assert snap_lwt["gateways"][0]["fw"] == "0.1.3-skeleton", "LWT نباید فیلدهای گیت‌وی را پاک کند"

    # TTL سلامت: ۱۵ دقیقه
    snap3 = bridge.snapshot(now=NOW + 1000)
    assert snap3["health"] == [], "health TTL کار نکرد"
    assert snap3["vitals"][0]["battery"] == 90, "TTL حیاتی‌ها باید یک ساعت باشد"

    # TTL حیاتی‌ها: ۱ ساعت
    snap4 = bridge.snapshot(now=NOW + 4000)
    assert snap4["vitals"] == [], "vitals TTL کار نکرد"

    # ── فرمان خروجی: لرزاندن مچ‌بند ──
    sent: list[tuple[str, str]] = []

    def fake_publish(topic: str, payload: str) -> tuple[bool, str]:
        sent.append((topic, payload))
        return True, "sent"

    bridge.publish = fake_publish  # type: ignore[assignment]

    ok, err, info = bridge.command({"action": "vibrate", "mac": MAC.upper()})
    assert ok and err == "", "فرمان لرزاندن باید بپذیرد"
    assert info["topic"] == f"roztash/{GW}/cmd"
    assert json.loads(info["payload"]) == {"action": "vibrate", "mac": MAC}
    assert sent[-1][0] == f"roztash/{GW}/cmd", "موضوع انتشار باید cmd باشد"

    ok, err, _ = bridge.command({"action": "selfdestruct"})
    assert not ok and err == "unknown action", "فرمان ناشناس باید رد شود"

    ok, err, info = bridge.command({"action": "vibrate", "mac": "aa:bb:cc:dd:ee:ff"})
    assert ok and info["gw"] == GW, "مچ‌بند ناشناس باید سراغ تازه‌ترین گیت‌وی برود"

    print("bridge tests PASSED — ingest/snapshot/TTL/command")


if __name__ == "__main__":
    main()
