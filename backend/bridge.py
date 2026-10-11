#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پل زندهٔ روزتاش — MQTT → SQLite → HTTP JSON API.

مصرف‌کننده‌ها:
  - src/data.py — حالت زندهٔ برنامهٔ فلت با GET /api/snapshot
  - ابزارهای دمو و عیب‌یابی با GET /health و /api/events
  - بخش «کارکنان» برنامه — دفتر کارکنان با GET/POST/DELETE /api/employees
    و ادغام زندهٔ آن‌ها در snapshot["employees"]
  - بخش «مچ‌بندها» برنامه — دفتر مچ‌بندها با GET/POST/DELETE /api/bands و
    فهرست ادغام‌شدهٔ مچ‌بندهای شناخته‌شده در snapshot["bands_known"]
  - بخش «تعاریف پایه» — GET/POST/DELETE /api/catalogs (شرکت، واحد، خط، سمت)
  - بخش «گیت‌وی‌ها» — دفتر گیت‌وی‌ها با GET/POST/DELETE /api/gateways و
    ادغامش با وضعیت زنده در snapshot["map_gateways"] (تعریف و چیدمان روی نقشه)
  - عکس پرسنلی کارکنان — GET /api/photo/<mac>؛ فایل‌ها در state/photos/
  - آماده‌سازی گیتوی — GET /api/netinfo: وای‌فای فعلی سیستم + پیشنهاد آدرس MQTT
    (include_pass=1 رمز وای‌فای را هم می‌دهد؛ فقط روی 127.0.0.1 سرو می‌شود)

قواعد طراحی:
  - فقط کتابخانهٔ استاندارد پایتون
  - اشتراک MQTT با mosquitto_sub به‌عنوان زیرفرایند و حلقهٔ بازاتصال
  - TTL حضور ۶۰ ثانیه — هماهنگ با فریمور گیت‌وی
  - TTL سلامت ۱۵ دقیقه — برای نمایش آخرین اندازه‌گیری
  - TTL حیاتی‌ها ۱ ساعت — باتری و اطلاعات دستگاه دیرتر کهنه می‌شوند
  - گیتوی آنلاین اگر status آن کمتر از ۱۸۰ ثانیه پیش رسیده باشد
  - دفتر کارکنان: نگاشت مک مچ‌بند ↔ کارکن (کلید = مک)؛ snapshot هر کارکن
    ثبت‌شده و هر مچ‌بند ثبت‌نشدهٔ در دید را با دادهٔ زنده ادغام می‌کند
  - فیلدهای پروندهٔ پزشکی و عکس پرسنلی اختیاری‌اند؛ عکس فقط JPG/PNG/WebP
    تا سقف PHOTO_MAX_BYTES و در پوشهٔ کنار پایگاه داده ذخیره می‌شود
  - دفتر گیت‌وی‌ها: نگاشت گیت‌وی فیزیکی ↔ نقطهٔ نقشه (کلید = شناسهٔ gw، همان
    که در config.json برد و موضوع MQTT می‌آید)؛ موقعیت x/y نسبی ۰..۱ است و
    نبودشان یعنی «هنوز روی نقشه چیده نشده»
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
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
PHOTOS_DIR = os.path.join(os.path.dirname(DB_PATH), "photos")
PHOTO_MAX_BYTES = 1_600_000  # سقف فایل عکس پرسنلی — بزرگ‌تر از این رد می‌شود
CATALOG_KINDS = ("company", "unit", "line", "role")

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
  note TEXT, conditions TEXT, medications TEXT, photo TEXT,
  company TEXT, line TEXT, age INTEGER, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS band_registry(
  mac TEXT PRIMARY KEY, label TEXT, note TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS catalogs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, name TEXT NOT NULL, parent_id INTEGER,
  created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS gateway_registry(
  gw TEXT PRIMARY KEY, label TEXT, zone TEXT, kind TEXT,
  x REAL, y REAL, note TEXT, mac TEXT, created_at REAL, updated_at REAL);
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
        # مهاجرت نرم — ستون‌های تازهٔ کارکنان روی دیتابیس‌های موجود
        cols = {r[1] for r in _db.execute("PRAGMA table_info(employees)")}
        for col, coltype in (("conditions", "TEXT"), ("medications", "TEXT"),
                             ("photo", "TEXT"), ("company", "TEXT"),
                             ("line", "TEXT"), ("age", "INTEGER")):
            if col not in cols:
                _db.execute(f"ALTER TABLE employees ADD COLUMN {col} {coltype}")
        gcols = {r[1] for r in _db.execute("PRAGMA table_info(gateway_registry)")}
        if "mac" not in gcols:
            # مک برد گیت‌وی — برای تشخیص «برد اشتباه» در آماده‌سازی
            _db.execute("ALTER TABLE gateway_registry ADD COLUMN mac TEXT")
        _db.commit()
        os.makedirs(PHOTOS_DIR, exist_ok=True)
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
    می‌ماند؛ فرستادن رشتهٔ خالی یعنی پاک‌کردن همان فیلد. فیلدهای پروندهٔ
    پزشکی و عکس پرسنلی اختیاری‌اند.
    """
    doc = dict(doc or {})
    mac = _norm_mac(doc.get("mac"))
    name = str(doc.get("name") or "").strip()
    if not _valid_mac(mac):
        return False, "invalid mac"
    if not name:
        return False, "name required"

    # عکس پرسنلی: data URI → ذخیرهٔ فایل؛ "" → پاک‌کردن؛ غایب → دست‌نخورده
    photo_new = None  # None یعنی «دست نزن»
    if "photo" in doc:
        raw_photo = str(doc.get("photo") or "")
        if not raw_photo:
            photo_new = ""
        else:
            ok_photo, res = _store_photo(mac, raw_photo)
            if not ok_photo:
                return False, res
            photo_new = res

    # سن: عدد ۱ تا ۱۲۰؛ "" → پاک‌کردن؛ غایب → دست‌نخورده
    age_new = None  # None یعنی «دست نزن»
    if "age" in doc:
        raw_age = str(doc.get("age") or "").strip()
        if not raw_age:
            age_new = 0
        else:
            try:
                age_new = int(float(raw_age))
            except (TypeError, ValueError):
                return False, "invalid age"
            if not 1 <= age_new <= 120:
                return False, "invalid age"

    now = time.time()
    with _lock:
        c = db()
        row = c.execute("SELECT * FROM employees WHERE mac=?", (mac,)).fetchone()

        def pick(key: str) -> str:
            if key in doc:
                return str(doc.get(key) or "").strip()
            return str((row[key] if row is not None else "") or "").strip()

        if photo_new is None:
            photo_val = str((row["photo"] if row is not None else "") or "")
        else:
            photo_val = photo_new
            if photo_new == "":
                _delete_photos(mac)
        if age_new is None:
            age_val = int((row["age"] if row is not None else 0) or 0)
        else:
            age_val = age_new
        c.execute(
            "INSERT INTO employees(mac,name,dept,role,shift,note,conditions,"
            "medications,photo,company,line,age,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(mac) DO UPDATE SET name=excluded.name, "
            "dept=excluded.dept, role=excluded.role, shift=excluded.shift, "
            "note=excluded.note, conditions=excluded.conditions, "
            "medications=excluded.medications, photo=excluded.photo, "
            "company=excluded.company, line=excluded.line, age=excluded.age, "
            "updated_at=excluded.updated_at",
            (mac, name, pick("dept"), pick("role"), pick("shift"), pick("note"),
             pick("conditions"), pick("medications"), photo_val,
             pick("company"), pick("line"), age_val, now, now))
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
    _delete_photos(mac)
    log(f"employee removed mac={mac}")
    return True, ""


def employees_list() -> list[dict]:
    """دفتر خام کارکنان — بدون ادغام دادهٔ زنده (برای API)."""
    with _lock:
        rows = db().execute("SELECT * FROM employees ORDER BY name").fetchall()
    return [dict(r) for r in rows]


# ─────────────────── عکس پرسنلی — ذخیره روی دیسک، سرو با HTTP ───────────────────

_PHOTO_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_PHOTO_MAGIC = {
    "jpg": lambda b: b[:3] == b"\xff\xd8\xff",
    "png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n",
    "webp": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP",
}


def _photo_stem(mac: str) -> str:
    return mac.replace(":", "-")


def _delete_photos(mac: str) -> None:
    """همهٔ فایل‌های عکس یک مچ‌بند را از پوشهٔ عکس‌ها پاک می‌کند."""
    stem = _photo_stem(mac)
    try:
        for name in os.listdir(PHOTOS_DIR):
            if name.rsplit(".", 1)[0] == stem:
                try:
                    os.remove(os.path.join(PHOTOS_DIR, name))
                except OSError:
                    pass
    except OSError:
        pass


def _store_photo(mac: str, data_uri: str) -> tuple[bool, str]:
    """ذخیرهٔ عکس از data URI — (ok، خطا یا نام فایل ذخیره‌شده)."""
    try:
        head, _, b64 = data_uri.partition(",")
        mime = head.split(";", 1)[0][len("data:"):].strip().lower()
        ext = _PHOTO_MIME.get(mime)
        if not ext or not b64:
            return False, "bad photo"
        raw = base64.b64decode(b64.strip(), validate=True)
    except Exception:
        return False, "bad photo"
    if len(raw) > PHOTO_MAX_BYTES:
        return False, "photo too large"
    if not _PHOTO_MAGIC[ext](raw):
        return False, "bad photo"
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    fname = f"{_photo_stem(mac)}.{ext}"
    _delete_photos(mac)  # فرمت قبلی (مثلاً png) جا نماند
    try:
        with open(os.path.join(PHOTOS_DIR, fname), "wb") as fh:
            fh.write(raw)
    except OSError:
        return False, "photo save failed"
    return True, fname


def get_photo(mac) -> tuple[bytes, str] | None:
    """عکس پرسنلی کارکن — (بایت، نوع محتوا) یا None اگر عکسی نیست."""
    mac = _norm_mac(mac)
    with _lock:
        row = db().execute("SELECT photo FROM employees WHERE mac=?",
                           (mac,)).fetchone()
    fname = str((row["photo"] if row is not None else "") or "")
    if not fname:
        return None
    # نام فایل فقط از رکورد پایگاه داده می‌آید — نه از ورودی کاربر
    path = os.path.join(PHOTOS_DIR, os.path.basename(fname))
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    ext = fname.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "png": "image/png",
            "webp": "image/webp"}.get(ext, "application/octet-stream")
    return data, mime


# ─────────────────── دفتر مچ‌بندها — برچسب و یادداشت هر مچ‌بند ───────────────────
# مک هر مچ‌بند می‌تواند پیش از تخصیص به کارکن اینجا ثبت شود (برچسب و یادداشت)؛
# فهرست ادغام‌شدهٔ «مچ‌بندهای شناخته‌شده» (دفتر + در دید + تخصیص کارکنان)
# خوراک بخش «مچ‌بندها» و فهرست انتخاب فرم کارکن است.


def upsert_band(doc: dict) -> tuple[bool, str]:
    """ثبت/ویرایش مچ‌بند در دفتر — ویرایش جزئی مثل کارکنان."""
    doc = dict(doc or {})
    mac = _norm_mac(doc.get("mac"))
    if not _valid_mac(mac):
        return False, "invalid mac"
    now = time.time()
    with _lock:
        c = db()
        row = c.execute("SELECT * FROM band_registry WHERE mac=?",
                        (mac,)).fetchone()

        def pick(key: str) -> str:
            if key in doc:
                return str(doc.get(key) or "").strip()
            return str((row[key] if row is not None else "") or "").strip()

        label, note = pick("label"), pick("note")
        c.execute(
            "INSERT INTO band_registry(mac,label,note,created_at,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(mac) DO UPDATE SET "
            "label=excluded.label, note=excluded.note, "
            "updated_at=excluded.updated_at",
            (mac, label, note, now, now))
        c.commit()
    log(f"band saved mac={mac} label={label!r}")
    return True, ""


def remove_band(mac) -> tuple[bool, str]:
    """حذف مچ‌بند از دفتر — اگر به کارکنی تخصیص دارد، رد می‌شود."""
    mac = _norm_mac(mac)
    if not _valid_mac(mac):
        return False, "invalid mac"
    with _lock:
        c = db()
        emp = c.execute("SELECT name FROM employees WHERE mac=?",
                        (mac,)).fetchone()
        if emp is not None:
            return False, "assigned"
        cur = c.execute("DELETE FROM band_registry WHERE mac=?", (mac,))
        c.commit()
    if cur.rowcount == 0:
        return False, "not found"
    log(f"band removed mac={mac}")
    return True, ""


def bands_list() -> list[dict]:
    """دفتر خام مچ‌بندها — بدون ادغام دادهٔ زنده (برای API)."""
    with _lock:
        rows = db().execute(
            "SELECT * FROM band_registry ORDER BY label, mac").fetchall()
    return [dict(r) for r in rows]


# ─────────────── تعاریف پایه — شرکت (با زیرشرکت)، واحد، خط، سمت ───────────────
# فهرست‌های پیش‌تعریف برای فرم کارکن. مقدار ذخیره‌شده روی کارکن متن است؛
# اینجا فقط گزینه‌های پیشنهادی نگهداری می‌شوند. شرکت می‌تواند والد داشته
# باشد (زیرشرکت‌ها زیر همان والد گروه می‌شوند).


def upsert_catalog(doc: dict) -> tuple[bool, str]:
    """افزودن/ویرایش یک تعریف پایه — id برای ویرایش، نبودش برای افزودن."""
    doc = dict(doc or {})
    kind = str(doc.get("kind") or "").strip()
    name = str(doc.get("name") or "").strip()
    if kind not in CATALOG_KINDS:
        return False, "invalid kind"
    if not name:
        return False, "name required"
    parent_id = None
    if doc.get("parent_id") not in (None, "", 0, "0"):
        try:
            parent_id = int(str(doc.get("parent_id")))
        except (TypeError, ValueError):
            return False, "invalid parent"
    now = time.time()
    with _lock:
        c = db()
        cid = doc.get("id")
        if cid in (None, "", 0, "0"):
            dup = c.execute(
                "SELECT id FROM catalogs WHERE kind=? AND name=? AND "
                "COALESCE(parent_id,0)=COALESCE(?,0)",
                (kind, name, parent_id)).fetchone()
            if dup:
                return False, "duplicate"
            cur = c.execute(
                "INSERT INTO catalogs(kind,name,parent_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?)", (kind, name, parent_id, now, now))
            c.commit()
            new_id = cur.lastrowid
        else:
            try:
                cid = int(cid)
            except (TypeError, ValueError):
                return False, "invalid id"
            row = c.execute("SELECT * FROM catalogs WHERE id=?",
                            (cid,)).fetchone()
            if row is None:
                return False, "not found"
            if parent_id == cid:
                return False, "invalid parent"
            dup = c.execute(
                "SELECT id FROM catalogs WHERE kind=? AND name=? AND id!=? AND "
                "COALESCE(parent_id,0)=COALESCE(?,0)",
                (kind, name, cid, parent_id)).fetchone()
            if dup:
                return False, "duplicate"
            c.execute("UPDATE catalogs SET name=?, parent_id=?, updated_at=? "
                      "WHERE id=?", (name, parent_id, now, cid))
            c.commit()
            new_id = cid
    log(f"catalog saved kind={kind} id={new_id} name={name!r}")
    return True, ""


def remove_catalog(cid) -> tuple[bool, str]:
    """حذف یک تعریف پایه — والدی که زیرمجموعه دارد حذف نمی‌شود."""
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return False, "invalid id"
    with _lock:
        c = db()
        row = c.execute("SELECT * FROM catalogs WHERE id=?", (cid,)).fetchone()
        if row is None:
            return False, "not found"
        kids = c.execute("SELECT COUNT(*) FROM catalogs WHERE parent_id=?",
                         (cid,)).fetchone()[0]
        if kids:
            return False, "has children"
        c.execute("DELETE FROM catalogs WHERE id=?", (cid,))
        c.commit()
    log(f"catalog removed id={cid}")
    return True, ""


def catalogs_list() -> dict:
    """تعاریف پایه به تفکیک نوع — خوراک فرم کارکن و بخش «تعاریف پایه»."""
    with _lock:
        rows = db().execute(
            "SELECT * FROM catalogs ORDER BY kind, name").fetchall()
    out = {kind: [] for kind in CATALOG_KINDS}
    for r in rows:
        out.setdefault(r["kind"], []).append(dict(r))
    return out


# ─────────────── دفتر گیت‌وی‌ها — تعریف، منطقه و چیدمان روی نقشه ───────────────
# نگاشت گیت‌وی فیزیکی ↔ نقطهٔ نقشه: کلید = شناسهٔ گیت‌وی (همان که در
# config.json برد می‌آید و در موضوع MQTT می‌نشیند؛ نمونه: gw-test-1). نقاط
# پیشنهادی هنوز برد ندارند ولی از الان شناسه و موقعیت می‌گیرند تا بعد از نصب،
# دادهٔ زنده خودکار به همان نقطه بچسبد. موقعیت x/y نسبی است — ۰..۱ از
# چپ/بالا؛ نبودشان یعنی «هنوز روی نقشه چیده نشده».

_GW_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
GW_KINDS = ("proposed", "installed")
_POS_UNSET = object()  # نگهبان «دست نزن» برای x/y


def _norm_gw(raw) -> str:
    """یکسان‌سازی شناسهٔ گیت‌وی — حروف کوچک، فاصله → خط تیره."""
    return str(raw or "").strip().lower().replace(" ", "-")


def _valid_gw(s: str) -> bool:
    return bool(_GW_RE.match(s))


def _next_gw_id(c: sqlite3.Connection) -> str:
    """شناسهٔ تازهٔ خودکار gw-۱، gw-۲… — کوچک‌ترین شمارهٔ بلااستفاده."""
    used = {r[0] for r in c.execute("SELECT gw FROM gateway_registry")}
    n = 1
    while f"gw-{n}" in used:
        n += 1
    return f"gw-{n}"


def _pos_of(doc: dict, key: str):
    """x/y از درخواست — _POS_UNSET یعنی دست نزن؛ None یعنی پاک کن؛ عدد ۰..۱."""
    if key not in doc:
        return _POS_UNSET
    raw = doc.get(key)
    if raw in ("", None):
        return None
    val = float(raw)  # TypeError/ValueError بالادست به «موقعیت نامعتبر» تبدیل می‌شود
    if not (0.0 <= val <= 1.0):
        raise ValueError("position range")
    return val


def upsert_gateway(doc: dict) -> tuple[bool, str]:
    """ثبت/ویرایش گیت‌وی در دفتر — ویرایش جزئی مثل بقیهٔ دفترها.

    شناسهٔ خالی = ساخت خودکار (gw-۱، gw-۲…). x/y نسبی ۰..۱ ذخیره می‌شوند؛
    رشتهٔ خالی برای x/y یعنی «برداشتن از نقشه»، نبودنشان یعنی دست‌نزدن.
    """
    doc = dict(doc or {})
    try:
        x_new, y_new = _pos_of(doc, "x"), _pos_of(doc, "y")
    except (TypeError, ValueError):
        return False, "invalid position"
    kind_new = None  # None یعنی دست نزن
    if "kind" in doc:
        kind_new = str(doc.get("kind") or "").strip() or "proposed"
        if kind_new not in GW_KINDS:
            return False, "invalid kind"

    now = time.time()
    with _lock:
        c = db()
        gw = _norm_gw(doc.get("gw"))
        row = None
        if gw:
            if not _valid_gw(gw):
                return False, "invalid gw"
            row = c.execute("SELECT * FROM gateway_registry WHERE gw=?",
                            (gw,)).fetchone()
        else:
            gw = _next_gw_id(c)

        def pick(key: str) -> str:
            if key in doc:
                return str(doc.get(key) or "").strip()
            return str((row[key] if row is not None else "") or "").strip()

        label = pick("label") or gw  # نام خالی = خود شناسه
        kind = kind_new or str((row["kind"] if row is not None else "") or "") or "proposed"
        x_val = (row["x"] if row is not None else None) if x_new is _POS_UNSET else x_new
        y_val = (row["y"] if row is not None else None) if y_new is _POS_UNSET else y_new
        mac = pick("mac").lower()
        c.execute(
            "INSERT INTO gateway_registry(gw,label,zone,kind,x,y,note,mac,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(gw) DO UPDATE SET label=excluded.label, "
            "zone=excluded.zone, kind=excluded.kind, x=excluded.x, y=excluded.y, "
            "note=excluded.note, mac=excluded.mac, updated_at=excluded.updated_at",
            (gw, label, pick("zone"), kind, x_val, y_val, pick("note"), mac, now, now))
        c.commit()
    log(f"gateway saved gw={gw} label={label!r}")
    return True, ""


def remove_gateway(gw) -> tuple[bool, str]:
    """حذف گیت‌وی از دفتر — اگر دوباره در شبکه دیده شود، «تعریف‌نشده» می‌ماند."""
    gw = _norm_gw(gw)
    if not _valid_gw(gw):
        return False, "invalid gw"
    with _lock:
        c = db()
        cur = c.execute("DELETE FROM gateway_registry WHERE gw=?", (gw,))
        c.commit()
    if cur.rowcount == 0:
        return False, "not found"
    log(f"gateway removed gw={gw}")
    return True, ""


def gateways_registry_list() -> list[dict]:
    """دفتر خام گیت‌وی‌ها — بدون ادغام وضعیت زنده (برای API)."""
    with _lock:
        rows = db().execute(
            "SELECT * FROM gateway_registry ORDER BY created_at, gw").fetchall()
    return [dict(r) for r in rows]


def _gateways_view(c: sqlite3.Connection, now: float) -> list[dict]:
    """ادغام دفتر گیت‌وی‌ها با وضعیت زنده — خوراک بخش «گیت‌وی‌ها» و نقشه.

    ردیف‌های دفتر با وضعیت زنده (آنلاین، نسخهٔ فریم‌ور، آخرین تماس، IP)
    غنی می‌شوند و گیت‌وی‌هایی که در شبکه دیده شده‌اند ولی هنوز تعریف نشده‌اند
    هم با registered=false به فهرست می‌آیند تا کاربر تعریفشان کند.
    """
    live = {r["gw"]: r for r in c.execute("SELECT * FROM gateways")}
    reg = c.execute(
        "SELECT * FROM gateway_registry ORDER BY created_at, gw").fetchall()
    rows = []
    for r in reg:
        gw = r["gw"]
        lv = live.pop(gw, None)
        age = (now - lv["last_seen"]) if (lv is not None and lv["last_seen"]) else None
        rows.append({
            "gw": gw, "label": r["label"], "zone": r["zone"], "kind": r["kind"],
            "mac": r["mac"], "x": r["x"], "y": r["y"], "note": r["note"],
            "registered": True,
            "live": lv is not None,
            "online": bool(lv is not None and age is not None
                           and age <= GATEWAY_ONLINE_TTL),
            "fw": lv["fw"] if lv is not None else None,
            "ip": lv["ip"] if lv is not None else None,
            "adv_seen": lv["adv_seen"] if lv is not None else None,
            "last_seen": _iso(lv["last_seen"]) if lv is not None else None,
            "age_s": round(age, 1) if age is not None else None,
        })
    for gw, lv in sorted(live.items()):
        age = (now - lv["last_seen"]) if lv["last_seen"] else None
        rows.append({
            "gw": gw, "label": None, "zone": lv["zone"], "kind": "installed",
            "mac": None, "x": None, "y": None, "note": None,
            "registered": False,
            "live": True,
            "online": bool(age is not None and age <= GATEWAY_ONLINE_TTL),
            "fw": lv["fw"], "ip": lv["ip"], "adv_seen": lv["adv_seen"],
            "last_seen": _iso(lv["last_seen"]),
            "age_s": round(age, 1) if age is not None else None,
        })
    return rows


# ───────── آمادهسازی گیتوی — وایفای و آدرس سیستم ─────────
# خوراک صفحهٔ «آمادهسازی گیتوی»: ssid (و اختیاری رمز) وایفای همین سیستم +
# پیشنهاد آدرس MQTT که گیتوی تازه باید بشناسد. همه‌چیز «بهترین تلاش» است —
# نبود ابزار سیستمی یعنی رشتهٔ خالی، نه خطا.


def _run_cmd(args: list[str], timeout: float = 8.0) -> str | None:
    """اجرای یک فرمان سیستمی کوتاه — متن یا None؛ هرگز استثنا نمی‌دهد."""
    try:
        res = subprocess.run(args, capture_output=True, timeout=timeout)
        return (res.stdout or b"").decode("utf-8", errors="replace")
    except Exception:
        return None


def _current_wifi() -> dict:
    """ssid/رمز وایفای فعال سیستم — nmcli روی لینوکس، netsh روی ویندوز."""
    ssid, psk, source = "", "", ""
    if sys.platform.startswith("win"):
        out = _run_cmd(["netsh", "wlan", "show", "interfaces"])
        if out:
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("SSID") and not line.startswith("BSSID") \
                        and ":" in line:
                    ssid = line.split(":", 1)[1].strip()
                    break
        if ssid:
            source = "netsh"
            prof = _run_cmd(["netsh", "wlan", "show", "profile",
                             f"name={ssid}", "key=clear"])
            if prof:
                for line in prof.splitlines():
                    line = line.strip()
                    if line.startswith("Key Content") and ":" in line:
                        psk = line.split(":", 1)[1].strip()
                        break
    else:
        act = _run_cmd(["nmcli", "-t", "-f", "ACTIVE,SSID,DEVICE",
                        "dev", "wifi"])
        if act:
            for line in act.splitlines():
                if not line.startswith("yes:"):
                    continue
                ssid = line.split(":", 1)[1].rsplit(":", 1)[0]
                break
        if ssid:
            source = "nmcli"
            conn = _run_cmd(["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE",
                             "connection", "show", "--active"])
            name = ""
            if conn:
                for line in conn.splitlines():
                    if ":802-11-wireless:yes" in line:
                        name = line.split(":", 1)[0]
                        break
            if name:
                psk = (_run_cmd(["nmcli", "-s", "-g",
                                 "802-11-wireless-security.psk",
                                 "connection", "show", name]) or "").strip()
    return {"ssid": ssid, "pass": psk, "source": source}


def _host_ip_candidates() -> list[dict]:
    """آدرس‌های IPv4 محلی این سیستم — حدس آدرس وصل‌شدن گیتوی‌ها."""
    cands: list[dict] = []
    out = _run_cmd(["ip", "-o", "-4", "addr", "show"])
    if out:
        for line in out.splitlines():
            parts = line.split()
            try:
                iface = parts[1].rstrip(":")
                addr = parts[3]
                ip, prefix = addr.split("/", 1)
            except (IndexError, ValueError):
                continue
            if iface == "lo" or ip.startswith("127."):
                continue
            cands.append({"iface": iface, "ip": ip, "prefix": prefix})
    # مسیر پیش‌فرض — کارساز روی همهٔ OSها (از جمله ویندوز)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127.") and all(c["ip"] != ip for c in cands):
            cands.append({"iface": "default", "ip": ip, "prefix": ""})
    except Exception:
        pass
    return cands


def _suggest_mqtt_host(cands: list[dict]) -> str:
    """آدرسی که این سیستم از دید گیتوی دارد — هم‌سابنتِ گیتوی‌های زندهٔ اخیر."""
    try:
        with _lock:
            rows = db().execute(
                "SELECT ip FROM gateways WHERE ip IS NOT NULL AND last_seen > ? "
                "ORDER BY last_seen DESC LIMIT 5",
                (time.time() - 3600,)).fetchall()
    except Exception:
        rows = []
    for r in rows:
        gw_ip = str(r["ip"] or "")
        if gw_ip.count(".") != 3:
            continue
        net = gw_ip.rsplit(".", 1)[0]
        for c in cands:
            if c["ip"].rsplit(".", 1)[0] == net:
                return c["ip"]
    for c in cands:
        if c.get("iface") == "default":
            return c["ip"]
    return cands[0]["ip"] if cands else ""


def netinfo(include_pass: bool = False) -> dict:
    """وای‌فای سیستم + پیشنهاد آدرس MQTT برای صفحهٔ آماده‌سازی گیتوی."""
    wifi = _current_wifi()
    cands = _host_ip_candidates()
    doc = {
        "ok": True,
        "hostname": socket.gethostname(),
        "ssid": wifi["ssid"],
        "wifi_source": wifi["source"],
        "mqtt_host": _suggest_mqtt_host(cands),
        "mqtt_port": MQTT_PORT,
        "candidates": cands,
    }
    if include_pass:
        doc["pass"] = wifi["pass"]
    return doc


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
    breg = {r["mac"]: r for r in c.execute("SELECT mac, label FROM band_registry")}
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
            "company": e["company"] if e else None,
            "line": e["line"] if e else None,
            "age": (e["age"] if (e is not None and e["age"]) else None),
            "conditions": e["conditions"] if e else None,
            "medications": e["medications"] if e else None,
            "band_label": ((breg[mac]["label"] or None)
                           if (mac in breg and breg[mac]["label"]) else None),
            "photo": (f"/api/photo/{mac}?v={int(e['updated_at'] or 0)}"
                      if (e is not None and e["photo"]) else None),
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


def _bands_known_view(c: sqlite3.Connection, now: float) -> list[dict]:
    """فهرست ادغام‌شدهٔ مچ‌بندهای شناخته‌شده — خوراک بخش «مچ‌بندها».

    اجتماع سه منبع: دفتر مچ‌بندها، مچ‌بندهای در دید گیتوی‌ها، و مچ‌بندهای
    تخصیص‌داده‌شده به کارکنان. هر ردیف وضعیت دید و صاحبش را دارد.
    """
    reg = {r["mac"]: r for r in c.execute("SELECT * FROM band_registry")}
    seen = {r["mac"]: r for r in c.execute("SELECT * FROM bands")}
    zones = {r["gw"]: r["zone"] for r in c.execute("SELECT gw, zone FROM gateways")}
    emp = {r["mac"]: r["name"] for r in c.execute("SELECT mac, name FROM employees")}
    rows = []
    for mac in sorted(set(reg) | set(seen) | set(emp)):
        b = seen.get(mac)
        in_view = bool(b is not None and b["seen_at"] >= now - PRESENCE_TTL)
        entry = reg.get(mac)
        rows.append({
            "mac": mac,
            "label": (entry["label"] or None) if entry is not None else None,
            "note": (entry["note"] or None) if entry is not None else None,
            "registered": entry is not None,
            "in_view": in_view,
            "rssi": b["rssi"] if (b is not None and in_view) else None,
            "gw": b["gw"] if (b is not None and in_view) else None,
            "zone": zones.get(b["gw"]) if (b is not None and in_view) else None,
            "last_seen": _iso(b["seen_at"]) if b is not None else None,
            "last_seen_age_s": (round(now - b["seen_at"], 1)
                                if b is not None else None),
            "employee_name": emp.get(mac),
        })
    # ترتیب: تخصیص‌دار، در دید، ثبت‌شده، بی‌دید — سپس برچسب/مک
    rows.sort(key=lambda r: (r["employee_name"] is None, not r["in_view"],
                             not r["registered"], r["label"] or "\uffff",
                             r["mac"]))
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
        bands_known = _bands_known_view(c, now)
        map_gateways = _gateways_view(c, now)
        catalogs = {kind: [] for kind in CATALOG_KINDS}
        for r in c.execute("SELECT * FROM catalogs ORDER BY kind, name"):
            catalogs.setdefault(r["kind"], []).append(dict(r))
    return {
        "ok": True, "fetched_at": _iso(now), "now": now,
        "presence_ttl": PRESENCE_TTL, "health_ttl": HEALTH_TTL,
        "vitals_ttl": VITALS_TTL,
        "gateways": gws, "bands": bands, "health": health, "vitals": vitals,
        "employees": employees, "bands_known": bands_known,
        "catalogs": catalogs, "map_gateways": map_gateways,
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
        elif path == "/api/bands":
            self._send(200, {"ok": True, "bands": bands_list()})
        elif path == "/api/catalogs":
            self._send(200, {"ok": True, "catalogs": catalogs_list()})
        elif path == "/api/gateways":
            self._send(200, {"ok": True, "gateways": gateways_registry_list()})
        elif path == "/api/netinfo":
            qs = parse_qs(urlparse(self.path).query)
            self._send(200, netinfo(include_pass=qs.get(
                "include_pass", ["0"])[0] == "1"))
        elif path.startswith("/api/photo/"):
            self._send_photo(unquote(path[len("/api/photo/"):]))
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def _send_photo(self, mac: str) -> None:
        got = get_photo(mac)
        if got is None:
            self._send(404, {"ok": False, "error": "no photo"})
            return
        data, mime = got
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in ("/api/command", "/api/employees", "/api/bands",
                        "/api/catalogs", "/api/gateways"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 8_000_000:  # عکس پرسنلی base64 هم جا می‌شود
                self._send(413, {"ok": False, "error": "body too large"})
                return
            doc = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send(400, {"ok": False, "error": "bad json body"})
            return
        if path == "/api/command":
            ok, err, info = command(doc)
            self._send(200 if ok else 400,
                       {"ok": ok, "info": info, "error": err or None})
        elif path == "/api/bands":
            ok, err = upsert_band(doc)
            self._send(200 if ok else 400, {"ok": ok, "error": err or None})
        elif path == "/api/catalogs":
            ok, err = upsert_catalog(doc)
            self._send(200 if ok else 400, {"ok": ok, "error": err or None})
        elif path == "/api/gateways":
            ok, err = upsert_gateway(doc)
            self._send(200 if ok else 400, {"ok": ok, "error": err or None})
        else:
            ok, err = upsert_employee(doc)
            self._send(200 if ok else 400, {"ok": ok, "error": err or None})

    def do_DELETE(self) -> None:  # noqa: N802
        # دو سبک پذیرفته می‌شود: ?کلید=… و /<کلید> — برای کارکن، مچ‌بند،
        # تعاریف پایه و گیت‌وی‌ها
        path = self.path.split("?", 1)[0]
        qs = parse_qs(urlparse(self.path).query)
        if path.startswith("/api/employees/"):
            key, kind = unquote(path[len("/api/employees/"):]), "employees"
        elif path.startswith("/api/bands/"):
            key, kind = unquote(path[len("/api/bands/"):]), "bands"
        elif path.startswith("/api/catalogs/"):
            key, kind = unquote(path[len("/api/catalogs/"):]), "catalogs"
        elif path.startswith("/api/gateways/"):
            key, kind = unquote(path[len("/api/gateways/"):]), "gateways"
        elif path in ("/api/employees", "/api/bands"):
            key, kind = (qs.get("mac") or [""])[0], path.rsplit("/", 1)[1]
        elif path == "/api/catalogs":
            key, kind = (qs.get("id") or [""])[0], "catalogs"
        elif path == "/api/gateways":
            key, kind = (qs.get("gw") or [""])[0], "gateways"
        else:
            self._send(404, {"ok": False, "error": "not found"})
            return
        if kind == "employees":
            ok, err = remove_employee(key)
            code = 200 if ok else (400 if err == "invalid mac" else 404)
        elif kind == "bands":
            ok, err = remove_band(key)
            code = 200 if ok else (
                400 if err == "invalid mac" else
                409 if err == "assigned" else 404)
        elif kind == "gateways":
            ok, err = remove_gateway(key)
            code = 200 if ok else (400 if err == "invalid gw" else 404)
        else:
            ok, err = remove_catalog(key)
            code = 200 if ok else (
                400 if err == "invalid id" else
                409 if err == "has children" else 404)
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
