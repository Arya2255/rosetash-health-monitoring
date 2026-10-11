#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پل زندهٔ روزتاش — MQTT → SQLite → HTTP JSON API.

مصرف‌کننده‌ها:
  - src/data.py — حالت زندهٔ برنامهٔ فلت با GET /api/snapshot
  - ابزارهای دمو و عیب‌یابی با GET /health و /api/events
  - بخش «کارکنان» برنامه — دفتر کارکنان با GET/POST/DELETE /api/employees
    و ادغام زندهٔ آن‌ها در snapshot["employees"]

قواعد طراحی:
  - فقط کتابخانهٔ استاندارد پایتون
  - اشتراک MQTT با mosquitto_sub به‌عنوان زیرفرایند و حلقهٔ بازاتصال
  - TTL حضور ۶۰ ثانیه — هماهنگ با فریمور گیتوی
  - TTL سلامت ۱۵ دقیقه — برای نمایش آخرین اندازه‌گیری
  - TTL حیاتی‌ها ۱ ساعت — باتری و اطلاعات دستگاه دیرتر کهنه می‌شوند
  - گیتوی آنلاین اگر status آن کمتر از ۱۸۰ ثانیه پیش رسیده باشد
  - دفتر کارکنان: نگاشت مک مچ‌بند ↔ کارکن (کلید = مک)؛ snapshot هر کارکن
    ثبت‌شده و هر مچ‌بند ثبت‌نشدهٔ در دید را با دادهٔ زنده ادغام می‌کند
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

MQTT_HOST = os.environ.get("ROZTASH_MQTT_HOST", "127.0.0.1")
MQTT_PORT = os.environ.get("ROZTASH_MQTT_PORT", "1884")
MQTT_TOPIC = os.environ.get("ROZTASH_MQTT_TOPIC", "roztash/#")
HTTP_HOST = os.environ.get("ROZTASH_BRIDGE_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("ROZTASH_BRIDGE_PORT", "8726"))
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ROZTASH_BRIDGE_DB", os.path.join(HERE, "state", "live.db"))

PRESENCE_TTL = float(os.environ.get("ROZTASH_PRESENCE_TTL", "60"))
HEALTH_TTL = float(os.environ.get("ROZTASH_HEALTH_TTL", "900"))
VITALS_TTL = float(os.environ.get("ROZTASH_VITALS_TTL", "3600"))
GATEWAY_ONLINE_TTL = float(os.environ.get("ROZTASH_GATEWAY_ONLINE_TTL", "180"))
EVENTS_KEEP = 3000
HEALTH_KEEP = 5000
VITALS_KEEP = 2000

# آستانه‌های وضعیت کارکن — پیش‌فرض محافظه‌کارانه، در آینده قابل تنظیم
HR_WARN_HIGH = 105.0     # ضربان میانگین بالای این عدد → هشدار
HR_WARN_LOW = 50.0       # ضربان میانگین زیر این عدد → هشدار
HR_DANGER_HIGH = 120.0   # از این عدد به بعد → اضطراری
HR_DANGER_LOW = 45.0     # تا این عدد → اضطراری
SPO2_WARN = 94           # اکسیژن ≤ ۹۴ → هشدار
SPO2_DANGER = 92         # اکسیژن < ۹۲ → اضطراری
BATTERY_WARN = 20        # درصد باتری مچ‌بند ≤ این عدد → هشدار

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, gw TEXT, kind TEXT, mac TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS gateways(
  gw TEXT PRIMARY KEY, zone TEXT, fw TEXT, ip TEXT, rssi REAL,
  uptime_s REAL, bands_seen REAL, adv_seen REAL, last_seen REAL, payload TEXT);
CREATE TABLE IF NOT EXISTS bands(
  mac TEXT PRIMARY KEY, gw TEXT, rssi REAL, seen_at REAL);
CREATE TABLE IF NOT EXISTS health(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, gw TEXT, mac TEXT, state TEXT, fail TEXT, wearing INTEGER,
  ended INTEGER, bpm TEXT, n INTEGER, avg REAL, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health(ts);
CREATE TABLE IF NOT EXISTS vitals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL, gw TEXT, mac TEXT, battery INTEGER, dev_fw TEXT, dev_hw TEXT,
  dev_maker TEXT, spo2_ack INTEGER, hrv_ack INTEGER, steps INTEGER,
  spo2_raw TEXT, hrv_raw TEXT, payload TEXT);
CREATE INDEX IF NOT EXISTS idx_vitals_ts ON vitals(ts);
CREATE TABLE IF NOT EXISTS employees(
  mac TEXT PRIMARY KEY, name TEXT NOT NULL, dept TEXT, role TEXT, shift TEXT,
  note TEXT, created_at REAL, updated_at REAL);
"""

_lock = threading.Lock()
_db: sqlite3.Connection | None = None
_started_at = time.time()


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[bridge {ts}] {msg}", flush=True)


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.executescript(SCHEMA)
        _db.commit()
    return _db


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


# ───────────────────────────── ingest ─────────────────────────────

def ingest(topic: str, payload: str, recv_ts: float | None = None) -> None:
    """یک پیام MQTT را در پایگاه داده ثبت می‌کند.

    recv_ts برای تست قابل تزریق است؛ در اجرای واقعی زمان دریافت پیام است
    که عملاً با زمان انتشار فرق محسوسی ندارد.
    """
    ts = recv_ts if recv_ts is not None else time.time()
    parts = topic.split("/")
    gw = parts[1] if len(parts) > 1 else "?"
    leaf = parts[-1] if parts else "?"
    try:
        doc = json.loads(payload)
    except Exception:
        doc = {}

    with _lock:
        c = db()
        if leaf == "presence":
            for b in (doc.get("bands") or []):
                c.execute(
                    "INSERT INTO bands(mac,gw,rssi,seen_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(mac) DO UPDATE SET gw=excluded.gw, rssi=excluded.rssi, "
                    "seen_at=excluded.seen_at",
                    (b.get("mac", "?"), gw, b.get("rssi"), ts))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "presence", None, payload))
        elif leaf == "status":
            # پیام LWT (آفلاین) نه فیلدها را بازنویسی می‌کند نه تازگی می‌سازد —
            # وگرنه بازپخش retained بعد از ری‌استارت پل، گیت‌وی را آنلاین جلوه می‌دهد.
            if doc.get("online") is False:
                c.execute(
                    "INSERT INTO gateways(gw,last_seen) VALUES(?,0.0) "
                    "ON CONFLICT(gw) DO UPDATE SET last_seen=0.0", (gw,))
            else:
                c.execute(
                    "INSERT INTO gateways(gw,zone,fw,ip,rssi,uptime_s,bands_seen,adv_seen,last_seen,payload) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(gw) DO UPDATE SET zone=excluded.zone, fw=excluded.fw, "
                    "ip=excluded.ip, rssi=excluded.rssi, uptime_s=excluded.uptime_s, "
                    "bands_seen=excluded.bands_seen, adv_seen=excluded.adv_seen, "
                    "last_seen=excluded.last_seen, payload=excluded.payload",
                    (gw, doc.get("zone"), doc.get("fw"), doc.get("ip"), doc.get("rssi"),
                     doc.get("uptime_s"), doc.get("bands_seen"), doc.get("adv_seen"), ts, payload))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "status", None, payload))
        elif leaf == "health":
            c.execute(
                "INSERT INTO health(ts,gw,mac,state,fail,wearing,ended,bpm,n,avg,payload) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (ts, gw, doc.get("mac"), doc.get("state"), doc.get("fail"),
                 1 if doc.get("wearing") else 0, 1 if doc.get("ended") else 0,
                 json.dumps(doc.get("bpm") or []), doc.get("n"), doc.get("avg"), payload))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "health", doc.get("mac"), payload))
        elif leaf == "vitals":
            c.execute(
                "INSERT INTO vitals(ts,gw,mac,battery,dev_fw,dev_hw,dev_maker,"
                "spo2_ack,hrv_ack,steps,spo2_raw,hrv_raw,payload) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, gw, doc.get("mac"), doc.get("battery"), doc.get("dev_fw"),
                 doc.get("dev_hw"), doc.get("dev_maker"),
                 1 if doc.get("spo2_ack") else 0, 1 if doc.get("hrv_ack") else 0,
                 doc.get("steps"), json.dumps(doc.get("spo2_raw") or []),
                 json.dumps(doc.get("hrv_raw") or []), payload))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "vitals", doc.get("mac"), payload))
        else:
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, doc.get("type", leaf), doc.get("mac"), payload))
        # هرس سبک
        c.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (EVENTS_KEEP,))
        c.execute("DELETE FROM health WHERE id <= (SELECT MAX(id) FROM health) - ?", (HEALTH_KEEP,))
        c.execute("DELETE FROM vitals WHERE id <= (SELECT MAX(id) FROM vitals) - ?", (VITALS_KEEP,))
        c.commit()


# ─────────────────── دفتر کارکنان — نگاشت مک مچ‌بند ↔ کارکن ───────────────────
# رابطهٔ هر مچ‌بند با صاحبش این‌جاست: کلید = مک مچ‌بند. ثبت، ویرایش و حذف
# از برنامه (بخش «کارکنان») یا با curl انجام می‌شود؛ snapshot دفتر را با
# دادهٔ زنده ادغام می‌کند تا بخش کارکنان برنامه از دادهٔ نمایشی جدا شود.

_MAC_HEX = set("0123456789abcdef")


def _norm_mac(raw) -> str:
    """یکسان‌سازی مک — حروف کوچک، شش بایت با جداکنندهٔ دونقطه."""
    s = str(raw or "").strip().lower().replace("-", ":").replace(" ", "")
    if ":" not in s and len(s) == 12:  # f3b6d6b747d7 → f3:b6:…
        s = ":".join(s[i:i + 2] for i in range(0, 12, 2))
    return s


def _valid_mac(s: str) -> bool:
    parts = s.split(":")
    return (len(parts) == 6 and
            all(len(p) == 2 and all(ch in _MAC_HEX for ch in p) for p in parts))


def upsert_employee(doc: dict) -> tuple[bool, str]:
    """ثبت یا ویرایش کارکن — کلید، مک مچ‌بند است؛ فقط نام الزامی است.

    ویرایش جزئی است: هر فیلدی که در درخواست نیامده باشد مقدار قبلی‌اش
    می‌ماند؛ فرستادن رشتهٔ خالی یعنی پاک‌کردن همان فیلد.
    """
    doc = dict(doc or {})
    mac = _norm_mac(doc.get("mac"))
    name = str(doc.get("name") or "").strip()
    if not _valid_mac(mac):
        return False, "invalid mac"
    if not name:
        return False, "name required"
    now = time.time()
    with _lock:
        c = db()
        row = c.execute("SELECT * FROM employees WHERE mac=?", (mac,)).fetchone()

        def pick(key: str) -> str:
            if key in doc:
                return str(doc.get(key) or "").strip()
            return str((row[key] if row is not None else "") or "").strip()

        c.execute(
            "INSERT INTO employees(mac,name,dept,role,shift,note,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(mac) DO UPDATE SET name=excluded.name, dept=excluded.dept, "
            "role=excluded.role, shift=excluded.shift, note=excluded.note, "
            "updated_at=excluded.updated_at",
            (mac, name, pick("dept"), pick("role"), pick("shift"), pick("note"),
             now, now))
        c.commit()
    log(f"employee saved mac={mac} name={name!r}")
    return True, ""


def remove_employee(mac) -> tuple[bool, str]:
    """حذف کارکن از دفتر — مچ‌بندش اگر در دید باشد به «ثبت‌نشده» برمی‌گردد."""
    mac = _norm_mac(mac)
    if not _valid_mac(mac):
        return False, "invalid mac"
    with _lock:
        c = db()
        cur = c.execute("DELETE FROM employees WHERE mac=?", (mac,))
        c.commit()
    if cur.rowcount == 0:
        return False, "not found"
    log(f"employee removed mac={mac}")
    return True, ""


def employees_list() -> list[dict]:
    """دفتر خام کارکنان — بدون ادغام دادهٔ زنده (برای API)."""
    with _lock:
        rows = db().execute("SELECT * FROM employees ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def _decode_spo2(spo2_raw) -> int | None:
    """اکسیژن خون از نخستین بایت فریم خام (0A,B2) — همان قاعدهٔ SDK خود اپ."""
    for raw in spo2_raw or []:
        try:
            first = int(str(raw).split(":", 1)[1][0:2], 16)
        except Exception:
            continue
        if 70 <= first <= 100:
            return first
    return None


def _employee_status(present: bool, health: dict | None, vitals: dict | None):
    """وضعیت کارکن از دادهٔ واقعی — (status، فهرست کدهای مشکل).

    off = مچ‌بند در دید هیچ گیت‌ویی نیست؛ warn/danger از ضربان، اکسیژن،
    باتری و وضعیت اندازه‌گیری می‌آید. «قرمز فقط برای وضعیت اضطراری».
    """
    if not present:
        return "off", []
    issues: list[str] = []
    avg = None
    if health and health.get("state") == "done" and health.get("n"):
        raw_avg = health.get("avg")
        if raw_avg is not None:
            try:
                avg = float(raw_avg)
            except (TypeError, ValueError):
                avg = None
    spo2 = (vitals or {}).get("spo2")
    battery = (vitals or {}).get("battery")
    if avg is not None and avg >= HR_WARN_HIGH:
        issues.append("hr_high")
    if avg is not None and avg <= HR_WARN_LOW:
        issues.append("hr_low")
    if spo2 is not None and spo2 <= SPO2_WARN:
        issues.append("spo2_low")
    if battery is not None and battery <= BATTERY_WARN:
        issues.append("battery_low")
    if (health and health.get("state") == "done"
            and health.get("wearing") is False):
        issues.append("not_wearing")
    if (health and health.get("state") != "done"
            and str(health.get("fail") or "none") != "none"):
        issues.append("measure_fail")
    danger = ((spo2 is not None and spo2 < SPO2_DANGER)
              or (avg is not None and avg >= HR_DANGER_HIGH)
              or (avg is not None and avg <= HR_DANGER_LOW))
    if danger:
        return "danger", issues
    return ("warn" if issues else "ok"), issues


def _employee_vitals(c: sqlite3.Connection, v, now: float) -> dict | None:
    """حیاتی‌های آخرین پنجرهٔ مچ‌بند — با پُر کردن اکسیژن/HRV از پنجرهٔ قبل.

    مثل بخش vitals در snapshot: پنجره‌های بدون مرحله نباید قرائت قبلی را
    پاک کنند.
    """
    if v is None:
        return None
    spo2_raw = json.loads(v["spo2_raw"] or "[]")
    hrv_raw = json.loads(v["hrv_raw"] or "[]")
    spo2_ack, hrv_ack = bool(v["spo2_ack"]), bool(v["hrv_ack"])
    readings_ts = v["ts"]
    if not (spo2_raw or hrv_raw or spo2_ack or hrv_ack):
        back = c.execute(
            "SELECT * FROM vitals WHERE gw=? AND mac=? AND "
            "(spo2_ack=1 OR hrv_ack=1 OR spo2_raw != '[]' OR hrv_raw != '[]') "
            "ORDER BY ts DESC LIMIT 1", (v["gw"], v["mac"])).fetchone()
        if back:
            spo2_ack, hrv_ack = bool(back["spo2_ack"]), bool(back["hrv_ack"])
            spo2_raw = json.loads(back["spo2_raw"] or "[]")
            hrv_raw = json.loads(back["hrv_raw"] or "[]")
            readings_ts = back["ts"]
    return {
        "battery": v["battery"], "dev_fw": v["dev_fw"],
        "spo2": _decode_spo2(spo2_raw), "spo2_ack": spo2_ack,
        "hrv_ack": hrv_ack, "hrv_frames": len(hrv_raw),
        "ts": _iso(v["ts"]), "age_s": round(now - v["ts"], 1),
        "readings_age_s": round(now - readings_ts, 1),
    }


def _employees_view(c: sqlite3.Connection, now: float) -> list[dict]:
    """ادغام دفتر کارکنان با دادهٔ زنده — خوراک بخش «کارکنان» برنامه.

    مبنای فهرست: همهٔ کارکنان ثبت‌شده + مچ‌بندهای ثبت‌نشدهٔ در دید.
    """
    reg = {r["mac"]: r for r in c.execute("SELECT * FROM employees")}
    seen = {r["mac"]: r for r in c.execute("SELECT * FROM bands")}
    zones = {r["gw"]: r["zone"] for r in c.execute("SELECT gw, zone FROM gateways")}
    health_latest = {}
    for r in c.execute("SELECT * FROM health WHERE ts >= ? ORDER BY ts DESC",
                       (now - HEALTH_TTL,)):
        health_latest.setdefault(r["mac"], r)
    vitals_latest = {}
    for r in c.execute("SELECT * FROM vitals WHERE ts >= ? ORDER BY ts DESC",
                       (now - VITALS_TTL,)):
        vitals_latest.setdefault(r["mac"], r)

    fresh = {m for m, b in seen.items() if b["seen_at"] >= now - PRESENCE_TTL}
    rows = []
    for mac in sorted(set(reg) | fresh):
        e = reg.get(mac)
        b = seen.get(mac)
        present = mac in fresh
        h = health_latest.get(mac)
        health = None
        if h:
            health = {
                "state": h["state"], "fail": h["fail"],
                "wearing": bool(h["wearing"]), "ended": bool(h["ended"]),
                "bpm": json.loads(h["bpm"] or "[]"), "n": h["n"], "avg": h["avg"],
                "ts": _iso(h["ts"]), "age_s": round(now - h["ts"], 1),
            }
        vitals = _employee_vitals(c, vitals_latest.get(mac), now)
        status, issues = _employee_status(present, health, vitals)
        rows.append({
            "mac": mac,
            "registered": e is not None,
            "name": e["name"] if e else None,
            "dept": e["dept"] if e else None,
            "role": e["role"] if e else None,
            "shift": e["shift"] if e else None,
            "note": e["note"] if e else None,
            "present": present,
            "rssi": b["rssi"] if b else None,
            "gw": b["gw"] if b else None,
            "zone": zones.get(b["gw"]) if b else None,
            "last_seen": _iso(b["seen_at"]) if b else None,
            "last_seen_age_s": round(now - b["seen_at"], 1) if b else None,
            "health": health,
            "vitals": vitals,
            "status": status,
            "issues": issues,
        })
    return rows


# ───────────────────────────── snapshot ─────────────────────────────

def snapshot(now: float | None = None) -> dict:
    """تصویر کامل وضعیت زنده برای لایهٔ دادهٔ برنامه."""
    now = now if now is not None else time.time()
    with _lock:
        c = db()
        gws = []
        for r in c.execute("SELECT * FROM gateways ORDER BY gw"):
            age = (now - r["last_seen"]) if r["last_seen"] else None
            gws.append({
                "gw": r["gw"], "zone": r["zone"], "fw": r["fw"], "ip": r["ip"],
                "rssi": r["rssi"], "uptime_s": r["uptime_s"], "adv_seen": r["adv_seen"],
                "online": bool(age is not None and age <= GATEWAY_ONLINE_TTL),
                "last_seen": _iso(r["last_seen"]), "age_s": round(age, 1) if age is not None else None,
            })
        bands = [{
            "mac": r["mac"], "gw": r["gw"], "rssi": r["rssi"], "seen_at": _iso(r["seen_at"]),
            "age_s": round(now - r["seen_at"], 1),
        } for r in c.execute("SELECT * FROM bands WHERE seen_at >= ? ORDER BY seen_at DESC",
                             (now - PRESENCE_TTL,))]
        health = []
        seen_pairs = set()
        for r in c.execute("SELECT * FROM health WHERE ts >= ? ORDER BY ts DESC",
                           (now - HEALTH_TTL,)):
            key = (r["gw"], r["mac"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            health.append({
                "gw": r["gw"], "mac": r["mac"], "state": r["state"], "fail": r["fail"],
                "wearing": bool(r["wearing"]), "ended": bool(r["ended"]),
                "bpm": json.loads(r["bpm"] or "[]"), "n": r["n"], "avg": r["avg"],
                "ts": _iso(r["ts"]), "age_s": round(now - r["ts"], 1),
            })
        events = [{
            "ts": _iso(r["ts"]), "gw": r["gw"], "kind": r["kind"], "mac": r["mac"],
        } for r in c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 50")]
        vitals = []
        seen_pairs = set()
        for r in c.execute("SELECT * FROM vitals WHERE ts >= ? ORDER BY ts DESC",
                           (now - VITALS_TTL,)):
            key = (r["gw"], r["mac"])
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            v = {
                "gw": r["gw"], "mac": r["mac"], "battery": r["battery"],
                "dev_fw": r["dev_fw"], "dev_hw": r["dev_hw"], "dev_maker": r["dev_maker"],
                "spo2_ack": bool(r["spo2_ack"]), "hrv_ack": bool(r["hrv_ack"]),
                "steps": r["steps"],
                "spo2_raw": json.loads(r["spo2_raw"] or "[]"),
                "hrv_raw": json.loads(r["hrv_raw"] or "[]"),
                "ts": _iso(r["ts"]), "age_s": round(now - r["ts"], 1),
            }
            # مراحل اکسیژن و HRV هر چند پنجره یک‌بار اجرا می‌شوند؛ پنجره‌های بدون آن‌ها
            # نباید وضعیت را پاک کنند — از تازه‌ترین ردیفی که قرائت داشته پر می‌شود.
            if not (v["spo2_raw"] or v["hrv_raw"] or v["spo2_ack"] or v["hrv_ack"]):
                back = c.execute(
                    "SELECT * FROM vitals WHERE gw=? AND mac=? AND "
                    "(spo2_ack=1 OR hrv_ack=1 OR spo2_raw != '[]' OR hrv_raw != '[]') "
                    "ORDER BY ts DESC LIMIT 1", (r["gw"], r["mac"])).fetchone()
                if back:
                    v["spo2_ack"] = bool(back["spo2_ack"])
                    v["hrv_ack"] = bool(back["hrv_ack"])
                    v["spo2_raw"] = json.loads(back["spo2_raw"] or "[]")
                    v["hrv_raw"] = json.loads(back["hrv_raw"] or "[]")
                    v["vitals_ts"] = _iso(back["ts"])
                    v["vitals_age_s"] = round(now - back["ts"], 1)
            vitals.append(v)
        employees = _employees_view(c, now)
    return {
        "ok": True, "fetched_at": _iso(now), "now": now,
        "presence_ttl": PRESENCE_TTL, "health_ttl": HEALTH_TTL,
        "vitals_ttl": VITALS_TTL,
        "gateways": gws, "bands": bands, "health": health, "vitals": vitals,
        "employees": employees,
        "events": events,
    }


# ───────────────────────────── MQTT ─────────────────────────────

def subscriber_loop() -> None:
    cmd = ["mosquitto_sub", "-h", MQTT_HOST, "-p", str(MQTT_PORT),
           "-t", MQTT_TOPIC, "-F", "%t %p"]
    while True:
        p = None
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1)
            log(f"subscribed {MQTT_TOPIC} on {MQTT_HOST}:{MQTT_PORT}")
            for line in p.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\n")
                if not line:
                    continue
                topic, _, payload = line.partition(" ")
                try:
                    ingest(topic, payload)
                except Exception as exc:  # یک پیام بد، بقیه را نخواباند
                    log(f"ingest error on {topic}: {exc!r}")
        except FileNotFoundError:
            log("mosquitto_sub not found — retry in 30s")
            time.sleep(30)
            continue
        except Exception as exc:
            log(f"subscriber error: {exc!r}")
        finally:
            if p is not None:
                p.kill()
        time.sleep(2)


# ──────────────────────── فرمان‌های خروجی (vibrate) ────────────────────────

ACTIONS = {"vibrate"}


def publish(topic: str, payload: str) -> tuple[bool, str]:
    """انتشار یک پیام روی بروکر — برای فرمان‌های خروجی مثل لرزاندن مچ‌بند."""
    try:
        p = subprocess.run(
            ["mosquitto_pub", "-h", MQTT_HOST, "-p", str(MQTT_PORT),
             "-t", topic, "-m", payload],
            capture_output=True, text=True, timeout=5)
        if p.returncode == 0:
            return True, "sent"
        return False, (p.stderr or p.stdout or "mosquitto_pub failed").strip()[:200]
    except Exception as exc:  # noqa: BLE001 — هر خطای اجرا به پاسخ برمی‌گردد
        return False, repr(exc)[:200]


def command(doc: dict) -> tuple[bool, str, dict]:
    """فرمان را روی roztash/<gw>/cmd منتشر می‌کند؛ گیت‌وی همان مچ‌بند را می‌فرستد.

    برمی‌گرداند: (ok، متن خطا، اطلاعات مسیر). مچ‌بند ناشناس باشد، سراغ
    تازه‌ترین گیت‌وی می‌رود.
    """
    action = str((doc or {}).get("action") or "").strip()
    mac = str((doc or {}).get("mac") or "").strip().lower()
    gw = str((doc or {}).get("gw") or "").strip()
    if action not in ACTIONS:
        return False, "unknown action", {}
    with _lock:
        if not gw:
            row = db().execute("SELECT gw FROM bands WHERE mac = ?",
                               (mac,)).fetchone()
            if row:
                gw = row["gw"]
        if not gw:
            row = db().execute(
                "SELECT gw FROM gateways ORDER BY last_seen DESC LIMIT 1"
            ).fetchone()
            if row:
                gw = row["gw"]
    if not gw:
        return False, "no gateway known yet", {}
    topic = f"roztash/{gw}/cmd"
    payload = json.dumps({"action": action, "mac": mac}, ensure_ascii=False)
    ok, detail = publish(topic, payload)
    log(f"command {action} mac={mac or '-'} gw={gw}: {detail}")
    return ok, ("" if ok else detail), {"gw": gw, "topic": topic, "payload": payload}


# ───────────────────────────── HTTP ─────────────────────────────

class Server(ThreadingHTTPServer):
    """سرور HTTP — خطای قطع ناگهانی کلاینت را یک‌خطی لاگ می‌کند.

    مرورگر وقتی تب را می‌بندد وسط پاسخ سوکت را قطع می‌کند؛ بدون این،
    هر بار یک traceback کامل وارد لاگ می‌شود.
    """

    def handle_error(self, request, client_address) -> None:  # noqa: N802 — امضای والد
        exc = sys.exc_info()[1]
        log(f"client error from {client_address[0]}: {type(exc).__name__}: {exc}")


class Handler(BaseHTTPRequestHandler):
    server_version = "roztash-bridge/0.2"

    def _send(self, code: int, doc: dict) -> None:
        body = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/health":
            self._send(200, {"ok": True, "db": DB_PATH,
                             "uptime_s": round(time.time() - _started_at, 1)})
        elif path == "/api/snapshot":
            self._send(200, snapshot())
        elif path == "/api/events":
            snap = snapshot()
            self._send(200, {"ok": True, "events": snap["events"]})
        elif path == "/api/employees":
            self._send(200, {"ok": True, "employees": employees_list()})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/api/command", "/api/employees"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            doc = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"ok": False, "error": "bad json body"})
            return
        if path == "/api/command":
            ok, err, info = command(doc)
            self._send(200 if ok else 400,
                       {"ok": ok, "info": info, "error": err or None})
        else:
            ok, err = upsert_employee(doc)
            self._send(200 if ok else 400, {"ok": ok, "error": err or None})

    def do_DELETE(self) -> None:  # noqa: N802
        # دو سبک پذیرفته می‌شود: /api/employees?mac=… و /api/employees/<mac>
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/employees/"):
            mac = unquote(path[len("/api/employees/"):])
        elif path == "/api/employees":
            qs = parse_qs(urlparse(self.path).query)
            mac = (qs.get("mac") or [""])[0]
        else:
            self._send(404, {"ok": False, "error": "not found"})
            return
        ok, err = remove_employee(mac)
        code = 200 if ok else (400 if err == "invalid mac" else 404)
        self._send(code, {"ok": ok, "error": err or None})

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — امضای والد
        return


def main() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    threading.Thread(target=subscriber_loop, daemon=True).start()
    srv = Server((HTTP_HOST, HTTP_PORT), Handler)
    log(f"http on http://{HTTP_HOST}:{HTTP_PORT}  db={DB_PATH}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("bye")


if __name__ == "__main__":
    main()
