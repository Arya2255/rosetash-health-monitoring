#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تست دفتر گیت‌وی‌ها در پل — ثبت، ویرایش جزئی، اعتبارسنجی و ادغام زنده.

بدون شبکه و بدون MQTT؛ فقط کتابخانهٔ استاندارد پایتون:

    python3 tests/test_gateway_registry.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import bridge  # noqa: E402

NOW = 1_700_000_000.0


def main() -> None:
    bridge.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="gw-test-"), "live.db")

    # ── ثبت گیت‌وی با شناسهٔ دستی + موقعیت ──
    ok, err = bridge.upsert_gateway({
        "gw": "gw-filter-2", "label": "سالن فیلتر ۲", "zone": "فیلتر",
        "kind": "proposed", "x": 0.3, "y": 0.4})
    assert ok and err == "", (ok, err)
    row = bridge.gateways_registry_list()[0]
    assert row["gw"] == "gw-filter-2" and row["label"] == "سالن فیلتر ۲"
    assert abs(row["x"] - 0.3) < 1e-9 and row["kind"] == "proposed"

    # ── ویرایش جزئی: فقط y عوض شود، بقیه بماند ──
    ok, _ = bridge.upsert_gateway({"gw": "gw-filter-2", "y": 0.5})
    assert ok
    row = [r for r in bridge.gateways_registry_list() if r["gw"] == "gw-filter-2"][0]
    assert row["label"] == "سالن فیلتر ۲" and abs(row["x"] - 0.3) < 1e-9
    assert abs(row["y"] - 0.5) < 1e-9 and row["kind"] == "proposed"

    # ── اعتبارسنجی‌ها ──
    assert bridge.upsert_gateway({"gw": "bad gw!", "label": "x"}) == (False, "invalid gw")
    assert bridge.upsert_gateway({"gw": "gw-ok", "x": 1.5}) == (False, "invalid position")
    assert bridge.upsert_gateway({"gw": "gw-ok", "x": "banana"}) == (False, "invalid position")
    assert bridge.upsert_gateway({"gw": "gw-ok", "kind": "weird"}) == (False, "invalid kind")

    # ── شناسهٔ خودکار: gw-۱ ──
    ok, _ = bridge.upsert_gateway({"label": "نقطهٔ تازه", "zone": "محوطه"})
    assert ok
    gws = {r["gw"] for r in bridge.gateways_registry_list()}
    assert "gw-1" in gws, gws

    # ── برداشتن از نقشه: x/y خالی → NULL ──
    ok, _ = bridge.upsert_gateway({"gw": "gw-filter-2", "x": "", "y": ""})
    assert ok
    row = [r for r in bridge.gateways_registry_list() if r["gw"] == "gw-filter-2"][0]
    assert row["x"] is None and row["y"] is None

    # ── ادغام با وضعیت زنده ──
    bridge.ingest("roztash/gw-test-1/status", json.dumps({
        "gw": "gw-test-1", "zone": "فیلتر", "fw": "0.1.5-vibrate", "online": True,
        "ip": "192.168.43.211", "rssi": -61, "uptime_s": 1200,
        "bands_seen": 1, "adv_seen": 1670}), recv_ts=NOW - 5)
    ok, _ = bridge.upsert_gateway({
        "gw": "gw-test-1", "label": "سالن فیلتر ۱", "kind": "installed",
        "x": 0.28, "y": 0.25})
    assert ok
    snap = bridge.snapshot(now=NOW)
    mg = {r["gw"]: r for r in snap["map_gateways"]}
    assert mg["gw-test-1"]["registered"] is True
    assert mg["gw-test-1"]["online"] is True and mg["gw-test-1"]["fw"] == "0.1.5-vibrate"
    assert mg["gw-filter-2"]["registered"] is True and mg["gw-filter-2"]["online"] is False
    assert mg["gw-filter-2"]["x"] is None

    # ── گیت‌وی ناشناسِ شبکه خودش به فهرست می‌آید (تعریف‌نشده) ──
    bridge.ingest("roztash/gw-anbar-9/status", json.dumps({
        "gw": "gw-anbar-9", "zone": "انبار", "online": True}), recv_ts=NOW - 3)
    snap = bridge.snapshot(now=NOW)
    mg = {r["gw"]: r for r in snap["map_gateways"]}
    assert mg["gw-anbar-9"]["registered"] is False
    assert mg["gw-anbar-9"]["online"] is True
    assert mg["gw-anbar-9"]["x"] is None

    # ── کهنگی: بعد از ۱۸۰ ثانیه آفلاین ──
    snap2 = bridge.snapshot(now=NOW + 220)
    mg2 = {r["gw"]: r for r in snap2["map_gateways"]}
    assert mg2["gw-anbar-9"]["online"] is False

    # ── حذف ──
    ok, _ = bridge.remove_gateway("gw-filter-2")
    assert ok
    assert bridge.remove_gateway("gw-filter-2") == (False, "not found")
    assert bridge.remove_gateway("bad!!") == (False, "invalid gw")
    snap3 = bridge.snapshot(now=NOW)
    assert "gw-filter-2" not in {r["gw"] for r in snap3["map_gateways"]}

    print("OK — همهٔ بررسی‌های دفتر گیت‌وی‌ها پاس شد")


if __name__ == "__main__":
    main()