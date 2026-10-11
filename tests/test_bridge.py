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

    # ── دفتر کارکنان — ثبت، ادغام زنده، وضعیت و حذف ──
    ok, err = bridge.upsert_employee({"mac": MAC.upper(), "name": "رضا محمدی",
                                      "company": "موتوسل", "dept": "تولید روغن",
                                      "line": "خط روغن ۲", "role": "اپراتور",
                                      "age": "34", "shift": "صبح", "note": "",
                                      "conditions": "فشار خون",
                                      "medications": "آملودیپین"})
    assert ok, err
    ok, err = bridge.upsert_employee({"mac": "aa-11-bb-22-cc-33", "name": "مهدی کریمی"})
    assert ok, err
    macs = sorted(e["mac"] for e in bridge.employees_list())
    assert macs == ["aa:11:bb:22:cc:33", MAC], f"یکسان‌سازی مک کار نکرد: {macs}"
    # ویرایش جزئی نباید بقیهٔ فیلدها را پاک کند
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی ۲"})
    assert ok, err
    row = next(r for r in bridge.employees_list() if r["mac"] == MAC)
    assert row["dept"] == "تولید روغن", f"ویرایش جزئی دپارتمان را پاک کرد: {row}"
    assert row["company"] == "موتوسل" and row["line"] == "خط روغن ۲"
    assert row["age"] == 34 and row["conditions"] == "فشار خون"
    assert row["medications"] == "آملودیپین"
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی"})
    assert ok, err
    ok, err = bridge.upsert_employee({"mac": "zz:zz:zz:zz:zz:zz", "name": "x"})
    assert not ok and err == "invalid mac", "مک نامعتبر باید رد شود"
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "   "})
    assert not ok and err == "name required", "نام خالی باید رد شود"
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی", "age": "200"})
    assert not ok and err == "invalid age", "سن خارج از بازه باید رد شود"
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی", "age": "abc"})
    assert not ok and err == "invalid age", "سن نامعتبر باید رد شود"

    # ── عکس پرسنلی — ذخیره، سرو، اعتبارسنجی و پاک‌کردن ──
    import base64 as _b64
    fake_jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    uri = "data:image/jpeg;base64," + _b64.b64encode(fake_jpg).decode()
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی", "photo": uri})
    assert ok, err
    got = bridge.get_photo(MAC)
    assert got is not None, "عکس ذخیره نشد"
    assert got[0] == fake_jpg and got[1] == "image/jpeg", got
    row = next(r for r in bridge.employees_list() if r["mac"] == MAC)
    assert row["photo"], "نام فایل عکس در رکورد ثبت نشد"
    e = {x["mac"]: x for x in bridge.snapshot(now=NOW)["employees"]}[MAC]
    assert e["photo"] and e["photo"].startswith("/api/photo/") and "?v=" in e["photo"]
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی",
                                      "photo": "data:application/pdf;base64,AAAA"})
    assert not ok and err == "bad photo", "فرمت غیرتصویری باید رد شود"
    big = b"\xff\xd8\xff" + b"\x00" * 2_000_000
    ok, err = bridge.upsert_employee(
        {"mac": MAC, "name": "رضا محمدی",
         "photo": "data:image/jpeg;base64," + _b64.b64encode(big).decode()})
    assert not ok and err == "photo too large", "عکس بزرگ باید رد شود"
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی", "photo": ""})
    assert ok and bridge.get_photo(MAC) is None, "پاک‌کردن عکس کار نکرد"
    ok, err = bridge.upsert_employee({"mac": MAC, "name": "رضا محمدی", "photo": uri})
    assert ok, err  # برای تست پاک‌شدن همراه حذف کارکن

    # ── دفتر مچ‌بندها ──
    ok, err = bridge.upsert_band({"mac": "aa-bb-cc-dd-ee-02", "label": "مچ‌بند انبار"})
    assert ok, err
    ok, err = bridge.upsert_band({"mac": MAC, "label": "مچ‌بند رضا"})
    assert ok, err
    ok, err = bridge.upsert_band({"mac": MAC, "note": "کنار خط"})
    assert ok, err
    b = {x["mac"]: x for x in bridge.bands_list()}[MAC]
    assert b["label"] == "مچ‌بند رضا" and b["note"] == "کنار خط", b
    ok, err = bridge.upsert_band({"mac": "bad", "label": "x"})
    assert not ok and err == "invalid mac"
    ok, err = bridge.remove_band(MAC)
    assert not ok and err == "assigned", "مچ‌بند تخصیص‌دار نباید حذف شود"

    # ── تعاریف پایه — شرکت (با زیرشرکت)، واحد، خط، سمت ──
    ok, err = bridge.upsert_catalog({"kind": "company", "name": "موتوسل"})
    assert ok, err
    cid = bridge.catalogs_list()["company"][0]["id"]
    ok, err = bridge.upsert_catalog({"kind": "company", "name": "روزتاش",
                                     "parent_id": cid})
    assert ok, err
    ok, err = bridge.upsert_catalog({"kind": "company", "name": "موتوسل"})
    assert not ok and err == "duplicate", "شرکت تکراری باید رد شود"
    ok, err = bridge.upsert_catalog({"kind": "unit", "name": "تولید روغن"})
    assert ok, err
    ok, err = bridge.upsert_catalog({"kind": "line", "name": "خط روغن ۲"})
    assert ok, err
    ok, err = bridge.upsert_catalog({"kind": "role", "name": "اپراتور"})
    assert ok, err
    ok, err = bridge.upsert_catalog({"kind": "bogus", "name": "x"})
    assert not ok and err == "invalid kind"
    ok, err = bridge.remove_catalog(cid)
    assert not ok and err == "has children", "والد دارای زیرشرکت نباید حذف شود"
    cats = bridge.catalogs_list()
    assert len(cats["company"]) == 2 and len(cats["unit"]) == 1
    assert len(cats["line"]) == 1 and len(cats["role"]) == 1

    # حضور تازه: مک اصلی با RSSI تازه + مچ‌بند دومِ ثبت‌نشده
    bridge.ingest(f"roztash/{GW}/presence", json.dumps({
        "gw": GW, "ts": 1020, "bands": [{"mac": MAC, "rssi": -70},
                                        {"mac": "aa:bb:cc:dd:ee:01", "rssi": -80}]}),
        recv_ts=NOW - 4)

    snap_e = bridge.snapshot(now=NOW)
    emps = {e["mac"]: e for e in snap_e["employees"]}
    assert set(emps) == {MAC, "aa:11:bb:22:cc:33", "aa:bb:cc:dd:ee:01"}, \
        f"ترکیب کارکنان غلط: {sorted(emps)}"
    e = emps[MAC]
    assert e["registered"] is True and e["name"] == "رضا محمدی"
    assert e["present"] is True and e["status"] == "ok", (e["status"], e["issues"])
    assert e["rssi"] == -70 and e["gw"] == GW and e["zone"] == "test"
    assert e["health"]["avg"] == 76.8 and e["health"]["n"] == 5
    assert e["vitals"]["battery"] == 90
    assert e["vitals"]["spo2_ack"] is True, "پُر شدن اکسیژن از پنجرهٔ قبل کار نکرد"
    assert e["vitals"]["spo2"] is None, "فریم با بایت صفر نباید قرائت معتبر بدهد"
    u = emps["aa:bb:cc:dd:ee:01"]
    assert u["registered"] is False and u["name"] is None and u["present"] is True
    n = emps["aa:11:bb:22:cc:33"]
    assert n["registered"] is True and n["present"] is False and n["status"] == "off"

    # فهرست ادغام‌شدهٔ مچ‌بندها — دفتر + در دید + تخصیص کارکنان
    bk = {b["mac"]: b for b in snap_e["bands_known"]}
    assert bk[MAC]["registered"] is True and bk[MAC]["in_view"] is True
    assert bk[MAC]["employee_name"] == "رضا محمدی"
    assert bk[MAC]["label"] == "مچ‌بند رضا"
    assert bk["aa:bb:cc:dd:ee:01"]["registered"] is False
    assert bk["aa:bb:cc:dd:ee:01"]["in_view"] is True
    assert bk["aa:bb:cc:dd:ee:01"]["employee_name"] is None
    assert bk["aa:bb:cc:dd:ee:02"]["registered"] is True
    assert bk["aa:bb:cc:dd:ee:02"]["in_view"] is False
    assert bk["aa:bb:cc:dd:ee:02"]["employee_name"] is None
    comp = {c["name"]: c for c in snap_e["catalogs"]["company"]}
    assert set(comp) == {"موتوسل", "روزتاش"}, comp
    assert comp["روزتاش"]["parent_id"] == comp["موتوسل"]["id"], comp

    # وضعیت اضطراری: ضربان ۱۳۰٫۵، اکسیژن ۸۵، باتری ۱۵
    bridge.ingest(f"roztash/{GW}/health", json.dumps({
        "gw": GW, "mac": MAC, "state": "done", "fail": "none", "wearing": True,
        "ended": True, "bpm": [128, 130, 132], "n": 3, "avg": 130.5}),
        recv_ts=NOW - 3)
    bridge.ingest(f"roztash/{GW}/vitals", json.dumps({
        "gw": GW, "mac": MAC, "battery": 15, "dev_fw": "2.0.2.3",
        "spo2_ack": True, "hrv_ack": False, "spo2_raw": ["0AB2:551A0A0B"],
        "hrv_raw": []}), recv_ts=NOW - 2)
    e = {x["mac"]: x for x in bridge.snapshot(now=NOW)["employees"]}[MAC]
    assert e["status"] == "danger", e["status"]
    assert "hr_high" in e["issues"] and "spo2_low" in e["issues"]
    assert "battery_low" in e["issues"]
    assert e["vitals"]["spo2"] == 85, e["vitals"]["spo2"]

    # حذف: مک در دید می‌ماند ولی «ثبت‌نشده» می‌شود
    ok, err = bridge.remove_employee(MAC)
    assert ok, err
    ok, err = bridge.remove_employee(MAC)
    assert not ok and err == "not found", "حذف دوم باید not found بدهد"
    e = {x["mac"]: x for x in bridge.snapshot(now=NOW)["employees"]}[MAC]
    assert e["registered"] is False and e["name"] is None and e["present"] is True
    assert bridge.get_photo(MAC) is None, "حذف کارکن باید عکسش را هم پاک کند"
    ok, err = bridge.remove_band(MAC)
    assert ok, err
    ok, err = bridge.remove_band(MAC)
    assert not ok and err == "not found", "حذف دوم مچ‌بند باید not found بدهد"

    # پس از پایان TTL حضور: ثبت‌شده‌های غایب می‌مانند، ثبت‌نشده‌های کهنه می‌روند
    stale = [x["mac"] for x in bridge.snapshot(now=NOW + 120)["employees"]]
    assert stale == ["aa:11:bb:22:cc:33"], f"هرَس کارکنان غلط: {stale}"

    print("bridge tests PASSED — ingest/snapshot/TTL/command/employees/"
          "bands/catalogs/photos")


if __name__ == "__main__":
    main()
