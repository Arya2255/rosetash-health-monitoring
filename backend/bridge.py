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
import asyncio
import json
import math
import os
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

# Auto-discovery for zero-config networking
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
import applog
from tools import gateway_discovery
from tools.discovery_udp import DISCOVERY_PORT, DiscoveryServer
if __package__:
    from . import battery_alerts as battery_policy
    from . import staff_alerts as staff_alert_policy
    from . import manual_measurements as measurement_policy
    from . import operational_alerts as operational_alert_policy
    from . import gateway_diagnostics as diagnostic_policy
else:  # Direct script execution and legacy ``import bridge`` callers.
    import battery_alerts as battery_policy
    import staff_alerts as staff_alert_policy
    import manual_measurements as measurement_policy
    import operational_alerts as operational_alert_policy
    import gateway_diagnostics as diagnostic_policy

claim_battery = battery_policy.claim
observe_battery = battery_policy.observe
pending_battery_rows = battery_policy.pending_rows
record_battery_publish = battery_policy.record_publish
record_battery_result = battery_policy.record_result
visible_battery_alerts = battery_policy.visible_alerts
from admin_roles import (can_manage_employee_scanning, can_manage_gateways,
                         can_manage_employee_schedules, can_delete_employees, get_role)
from personnel import STAFF_GROUP_LABELS
from alert_contacts import alert_recipients
from employee_schedule import (DAY_KEYS, MAX_ACTIVE_MACS, TEHRAN, active_employee_macs,
                               eligible_employee, is_scheduled,
                               next_schedule_transition, normalize_schedule)
from bridge_auth import verify_request

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
GATEWAY_DISCOVERY_TTL = 120.0
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
  mac TEXT PRIMARY KEY, gw TEXT, rssi REAL, seen_at REAL, address_type INTEGER);
CREATE TABLE IF NOT EXISTS band_observations(
  mac TEXT NOT NULL, gw TEXT NOT NULL, rssi REAL NOT NULL, seen_at REAL NOT NULL,
  address_type INTEGER, PRIMARY KEY(mac,gw));
CREATE INDEX IF NOT EXISTS idx_band_observations_seen ON band_observations(seen_at);
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
  staff_group TEXT NOT NULL DEFAULT 'employee',
  note TEXT, conditions TEXT, medications TEXT, photo TEXT,
  company TEXT, line TEXT, age INTEGER, weekly_schedule TEXT NOT NULL DEFAULT '{}',
  scan_paused INTEGER NOT NULL DEFAULT 0, scan_pause_by TEXT, scan_pause_at REAL,
  scan_resume_at REAL,
  schedule_updated_by TEXT, schedule_updated_at REAL, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS monitoring_settings(
  key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_by TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS band_registry(
  mac TEXT PRIMARY KEY, label TEXT, note TEXT, created_at REAL, updated_at REAL,
  inactive_since REAL);
CREATE TABLE IF NOT EXISTS catalogs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, name TEXT NOT NULL, parent_id INTEGER,
  created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS gateway_registry(
  gw TEXT PRIMARY KEY, label TEXT, zone TEXT, kind TEXT,
  x REAL, y REAL, note TEXT, mac TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS network_gateway_observations(
  gw TEXT PRIMARY KEY, mac TEXT NOT NULL, fw TEXT NOT NULL, ip TEXT NOT NULL,
  transport TEXT NOT NULL, mqtt_connected INTEGER NOT NULL, seen_at REAL NOT NULL);
"""

_lock = threading.Lock()
_db: sqlite3.Connection | None = None
_started_at = time.time()


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[bridge {ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # A frozen Windows worker can inherit a legacy redirected stdout codec.
        # Logging occurs after DB commits and must never abort the HTTP response.
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        try:
            print(line.encode(encoding, "backslashreplace").decode(encoding), flush=True)
        except (OSError, ValueError):
            pass
    except (OSError, ValueError):
        pass


def db() -> sqlite3.Connection:
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute("PRAGMA journal_mode=WAL")
        _db.executescript(SCHEMA)
        battery_policy.ensure_schema(_db)
        staff_alert_policy.ensure_schema(_db)
        measurement_policy.ensure_schema(_db)
        operational_alert_policy.ensure_schema(_db)
        diagnostic_policy.ensure_schema(_db)
        # Backfill real prior sightings for upgrades where a retained LWT had
        # already reset gateways.last_seen before alert tracking existed.
        _db.execute(
            "INSERT INTO operational_gateway_state(gw,ever_seen,last_seen) "
            "SELECT gw,1,last_seen FROM gateways WHERE last_seen>0 "
            "ON CONFLICT(gw) DO UPDATE SET ever_seen=1,"
            "last_seen=max(COALESCE(operational_gateway_state.last_seen,0),excluded.last_seen)"
        )
        for event in _db.execute("SELECT gw,ts,payload FROM events WHERE kind='status'").fetchall():
            try:
                status = json.loads(event["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            if isinstance(status, dict) and status.get("online") is not False:
                operational_alert_policy.note_gateway_seen(_db, event["gw"], event["ts"])
        # مهاجرت نرم — ستون‌های تازهٔ کارکنان روی دیتابیس‌های موجود
        cols = {r[1] for r in _db.execute("PRAGMA table_info(employees)")}
        for col, coltype in (("conditions", "TEXT"), ("medications", "TEXT"),
                             ("staff_group", "TEXT NOT NULL DEFAULT 'employee'"),
                             ("photo", "TEXT"), ("company", "TEXT"),
                             ("line", "TEXT"), ("age", "INTEGER"),
                             ("weekly_schedule", "TEXT NOT NULL DEFAULT '{}'"),
                             ("scan_paused", "INTEGER NOT NULL DEFAULT 0"),
                             ("scan_pause_by", "TEXT"), ("scan_pause_at", "REAL"),
                             ("scan_resume_at", "REAL"),
                             ("schedule_updated_by", "TEXT"),
                             ("schedule_updated_at", "REAL")):
            if col not in cols:
                _db.execute(f"ALTER TABLE employees ADD COLUMN {col} {coltype}")
        gcols = {r[1] for r in _db.execute("PRAGMA table_info(gateway_registry)")}
        if "inactive_since" not in {r[1] for r in _db.execute("PRAGMA table_info(band_registry)")}:
            _db.execute("ALTER TABLE band_registry ADD COLUMN inactive_since REAL")
        if "address_type" not in {r[1] for r in _db.execute("PRAGMA table_info(bands)")}:
            _db.execute("ALTER TABLE bands ADD COLUMN address_type INTEGER")
        if "mac" not in gcols:
            # مک برد گیت‌وی — برای تشخیص «برد اشتباه» در آماده‌سازی
            _db.execute("ALTER TABLE gateway_registry ADD COLUMN mac TEXT")
        _db.execute(
            "INSERT OR IGNORE INTO band_observations(mac,gw,rssi,seen_at,address_type) "
            "SELECT mac,gw,rssi,seen_at,address_type FROM bands "
            "WHERE gw IS NOT NULL AND seen_at IS NOT NULL AND rssi >= -127 AND rssi < 0")
        _db.execute(
            "INSERT OR IGNORE INTO monitoring_settings(key,value) VALUES(?,?)",
            ("health_interval_s", "600"))
        _db.commit()
        os.makedirs(PHOTOS_DIR, exist_ok=True)
    return _db


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


# ───────────────────────────── ingest ─────────────────────────────

def _mac_scan_eligible(c: sqlite3.Connection, mac: str, now: float) -> bool:
    """Unknown bands remain discoverable; assigned bands obey shift and pause."""
    row = c.execute("SELECT * FROM employees WHERE mac=?",
                    (_norm_mac(mac),)).fetchone()
    if row is None:
        return not _released_band(c, mac)
    if row["staff_group"] == "hse":
        return True
    return _monitoring_state(row, now)["scan_allowed"]


def _schedule_window_start(schedule: dict, now_dt: datetime) -> datetime | None:
    """Start of the currently effective Tehran interval, if any."""
    try:
        schedule = normalize_schedule(schedule)
    except (TypeError, ValueError):
        return None
    now_dt = now_dt.astimezone(TEHRAN) if now_dt.tzinfo else now_dt.replace(tzinfo=TEHRAN)
    intervals = []
    index = (now_dt.date().weekday() + 2) % 7
    for offset in range(-8, 1):
        date = now_dt.date() + timedelta(days=offset)
        day = DAY_KEYS[(index + offset) % 7]
        for item in schedule.get(day, []):
            start = datetime.combine(date, datetime.strptime(item["start"], "%H:%M").time(), TEHRAN)
            end = datetime.combine(date, datetime.strptime(item["end"], "%H:%M").time(), TEHRAN)
            if end <= start:
                end += timedelta(days=1)
            intervals.append((start, end))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return next((start for start, end in merged if start <= now_dt < end), None)


def _monitoring_state(row, now: float) -> dict:
    """Return effective schedule state and the freshness floor for live data."""
    try:
        schedule = normalize_schedule(json.loads(row["weekly_schedule"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        schedule = {}
    now_dt = datetime.fromtimestamp(now, TEHRAN)
    scheduled = bool(schedule) and is_scheduled(schedule, now_dt)
    if not schedule:
        reason = "unconfigured"
    elif bool(row["scan_paused"]):
        reason = "paused"
    elif not scheduled:
        reason = "outside_shift"
    else:
        reason = "active"
    allowed = reason == "active"
    floor = None
    if allowed:
        starts = [_schedule_window_start(schedule, now_dt)]
        for key in ("schedule_updated_at", "scan_resume_at"):
            value = row[key] if key in row.keys() else None
            if value is not None:
                starts.append(datetime.fromtimestamp(float(value), TEHRAN))
        floor = max(value.timestamp() for value in starts if value is not None)
    return {"weekly_schedule": schedule, "scheduled_now": scheduled,
            "scan_paused": bool(row["scan_paused"]), "scan_allowed": allowed,
            "monitoring_reason": reason, "data_floor": floor}


def _released_band(c: sqlite3.Connection, mac: str) -> bool:
    return c.execute("SELECT 1 FROM band_registry WHERE mac=? AND inactive_since IS NOT NULL",
                     (_norm_mac(mac),)).fetchone() is not None


def _monitoring_state_for_mac(c: sqlite3.Connection, mac: str, now: float) -> dict:
    row = c.execute("SELECT * FROM employees WHERE mac=?", (_norm_mac(mac),)).fetchone()
    if row is None:
        released = _released_band(c, mac)
        return {"weekly_schedule": {}, "scheduled_now": False, "scan_paused": False,
                "scan_allowed": not released,
                "monitoring_reason": "inactive" if released else "unconfigured",
                "data_floor": None}
    return _monitoring_state(row, now)


def _mac_data_visible(c: sqlite3.Connection, mac: str, data_ts: float, now: float,
                      *, presence: bool = False) -> bool:
    state = _monitoring_state_for_mac(c, mac, now)
    emergency = False
    if presence:
        row = c.execute("SELECT staff_group FROM employees WHERE mac=?",
                        (_norm_mac(mac),)).fetchone()
        emergency = row is not None and row["staff_group"] == "hse"
    return bool(data_ts <= now and (state["scan_allowed"] or emergency) and
                (state["data_floor"] is None or data_ts >= state["data_floor"]))


def _valid_rssi(value) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and -127 <= value < 0)


def _fresh_bands(c: sqlite3.Connection, now: float, *, installed_only=False) -> dict:
    """Strongest fresh observation per band; lexical gateway ID breaks ties.

    Registered installed gateways take precedence over discovery-only receivers.
    The latter can still expose unassigned bands, but cannot supply a map point.
    """
    rows = c.execute(
        "SELECT b.*,g.zone,g.x,g.y,g.kind FROM band_observations b "
        "LEFT JOIN gateway_registry g ON g.gw=b.gw "
        "WHERE b.seen_at >= ? AND b.seen_at <= ? "
        "ORDER BY CASE WHEN g.kind='installed' THEN 0 ELSE 1 END,b.rssi DESC,b.gw",
        (now - PRESENCE_TTL, now))
    winners = {}
    for row in rows:
        if (installed_only and row["kind"] != "installed") or not _valid_rssi(row["rssi"]):
            continue
        if _mac_data_visible(c, row["mac"], row["seen_at"], now, presence=True):
            winners.setdefault(row["mac"], dict(row))
    return winners


def _band_location(b) -> dict | None:
    if not b or b.get("kind") != "installed" or b["x"] is None or b["y"] is None:
        return None
    return {"gw": b["gw"], "zone": b["zone"], "x": b["x"], "y": b["y"],
            "rssi": b["rssi"], "seen_at": _iso(b["seen_at"])}


def ingest(topic: str, payload: str, recv_ts: float | None = None) -> None:
    """یک پیام MQTT را در پایگاه داده ثبت می‌کند.

    recv_ts برای تست قابل تزریق است؛ در اجرای واقعی زمان دریافت پیام است
    که عملاً با زمان انتشار فرق محسوسی ندارد.
    """
    ts = recv_ts if recv_ts is not None else time.time()
    parts = topic.split("/")
    gw = parts[1] if len(parts) > 1 else "?"
    leaf = parts[-1] if parts else "?"
    if leaf in ("scan-policy", "cmd"):
        return
    try:
        doc = json.loads(payload)
    except Exception:
        doc = {}
    if not isinstance(doc, dict):
        return

    with _lock:
        c = db()
        if doc.get("replayed") is True and leaf in ("health", "vitals", "event"):
            # Arrival time cannot be used as measurement time after an offline queue.
            mac = _norm_mac(doc.get("mac"))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "offline_replay", mac or None, payload))
            c.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (EVENTS_KEEP,))
            c.commit()
            return
        if leaf == "diagnostic":
            # Owner-only diagnostics are correlated responses, never employee
            # presence, health or vitals observations. Results are not replayed.
            diagnostic_policy.record_result(c, gw, doc, ts)
            return
        if leaf == "presence":
            accepted = []
            for b in (doc.get("bands") or []):
                if not isinstance(b, dict):
                    continue
                mac = _norm_mac(b.get("mac"))
                if (not _valid_mac(mac) or not _valid_rssi(b.get("rssi"))
                        or not _mac_scan_eligible(c, mac, ts)):
                    continue
                age_ms = b.get("age_ms", 0)
                if type(age_ms) is not int or not 0 <= age_ms <= PRESENCE_TTL * 1000:
                    continue
                observed_at = ts - age_ms / 1000.0
                if not _mac_data_visible(c, mac, observed_at, ts, presence=True):
                    continue
                old = c.execute("SELECT seen_at FROM band_observations WHERE mac=? AND gw=?",
                                (mac, gw)).fetchone()
                if old is not None and old["seen_at"] > observed_at:
                    continue
                accepted.append({"mac": mac, "rssi": b.get("rssi"), "age_ms": age_ms})
                c.execute(
                    "INSERT INTO band_observations(mac,gw,rssi,seen_at,address_type) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(mac,gw) DO UPDATE SET rssi=excluded.rssi, "
                    "seen_at=excluded.seen_at,address_type=excluded.address_type",
                    (mac, gw, b["rssi"], observed_at, b.get("address_type")))
                c.execute(
                    "INSERT INTO bands(mac,gw,rssi,seen_at,address_type) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(mac) DO UPDATE SET gw=excluded.gw, rssi=excluded.rssi, "
                    "seen_at=excluded.seen_at, address_type=excluded.address_type "
                    "WHERE excluded.seen_at >= bands.seen_at",
                    (mac, gw, b.get("rssi"), observed_at, b.get("address_type")))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "presence", None,
                       json.dumps({"bands": accepted}, ensure_ascii=False)))
        elif leaf == "status":
            # پیام LWT (آفلاین) نه فیلدها را بازنویسی می‌کند نه تازگی می‌سازد —
            # وگرنه بازپخش retained بعد از ری‌استارت پل، گیت‌وی را آنلاین جلوه می‌دهد.
            if doc.get("online") is False:
                c.execute(
                    "INSERT INTO gateways(gw,last_seen) VALUES(?,0.0) "
                    "ON CONFLICT(gw) DO UPDATE SET last_seen=0.0", (gw,))
            else:
                operational_alert_policy.note_gateway_seen(c, gw, ts)
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
            mac = _norm_mac(doc.get("mac"))
            if not _valid_mac(mac) or not _mac_data_visible(c, mac, ts, ts):
                return
            if "request_id" in doc and not measurement_policy.record_health(
                    c, gw, {**doc, "mac": mac}, ts):
                return
            c.execute(
                "INSERT INTO health(ts,gw,mac,state,fail,wearing,ended,bpm,n,avg,payload) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (ts, gw, mac, doc.get("state"), doc.get("fail"),
                 1 if doc.get("wearing") else 0, 1 if doc.get("ended") else 0,
                 json.dumps(doc.get("bpm") or []), doc.get("n"), doc.get("avg"), payload))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "health", mac, payload))
        elif leaf == "vitals":
            mac = _norm_mac(doc.get("mac"))
            if not _valid_mac(mac) or not _mac_data_visible(c, mac, ts, ts):
                return
            if "request_id" in doc and not measurement_policy.matching_request(
                    c, gw, {**doc, "mac": mac}, ts):
                return
            level = doc.get("battery")
            if not battery_policy.valid_percent(level):
                level = None
            if c.execute("SELECT mac FROM employees WHERE mac=?", (mac,)).fetchone():
                observe_battery(c, mac, gw, level, ts)
            c.execute(
                "INSERT INTO vitals(ts,gw,mac,battery,dev_fw,dev_hw,dev_maker,"
                "spo2_ack,hrv_ack,steps,spo2_raw,hrv_raw,payload) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, gw, mac, level, doc.get("dev_fw"),
                 doc.get("dev_hw"), doc.get("dev_maker"),
                 1 if doc.get("spo2_ack") else 0, 1 if doc.get("hrv_ack") else 0,
                 doc.get("steps"), json.dumps(doc.get("spo2_raw") or []),
                 json.dumps(doc.get("hrv_raw") or []), payload))
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, "vitals", mac, payload))
        else:
            mac = _norm_mac(doc.get("mac"))
            if mac and not _valid_mac(mac):
                return
            if mac and not _mac_data_visible(c, mac, ts, ts):
                if leaf != "event" or not staff_alert_policy.accepts_result(c, gw, {**doc, "mac": mac}):
                    return
            if leaf == "event":
                record_battery_result(c, gw, {**doc, "mac": mac}, ts)
                staff_alert_policy.record_result(c, gw, {**doc, "mac": mac}, ts)
                measurement_policy.record_result(c, gw, {**doc, "mac": mac}, ts)
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, doc.get("type", leaf), mac or None, payload))
        # هرس سبک
        c.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (EVENTS_KEEP,))
        c.execute("DELETE FROM health WHERE id <= (SELECT MAX(id) FROM health) - ?", (HEALTH_KEEP,))
        c.execute("DELETE FROM vitals WHERE id <= (SELECT MAX(id) FROM vitals) - ?", (VITALS_KEEP,))
        c.commit()
    if leaf in ("status", "presence", "health", "vitals", "event"):
        _scan_policy_wake.set()


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
    if "name" in doc and not name:
        return False, "name required"
    if "staff_group" in doc and doc["staff_group"] not in STAFF_GROUP_LABELS:
        return False, "invalid staff group"

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
        if "name" not in doc:
            name = str(row["name"] or "") if row is not None else ""
        if not name:
            return False, "name required"

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
        schedule_val = str((row["weekly_schedule"] if row is not None else "{}") or "{}")
        paused = int(row["scan_paused"] if row is not None else 0)
        pause_by = row["scan_pause_by"] if row is not None else None
        pause_at = row["scan_pause_at"] if row is not None else None
        resume_at = row["scan_resume_at"] if row is not None else now
        schedule_by = row["schedule_updated_by"] if row is not None else None
        schedule_at = row["schedule_updated_at"] if row is not None else None
        c.execute(
            "INSERT INTO employees(mac,name,dept,role,shift,note,conditions,"
            "medications,photo,company,line,age,weekly_schedule,scan_paused,"
            "scan_pause_by,scan_pause_at,scan_resume_at,schedule_updated_by,schedule_updated_at,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(mac) DO UPDATE SET name=excluded.name, "
            "dept=excluded.dept, role=excluded.role, shift=excluded.shift, "
            "note=excluded.note, conditions=excluded.conditions, "
            "medications=excluded.medications, photo=excluded.photo, "
            "company=excluded.company, line=excluded.line, age=excluded.age, "
            "updated_at=excluded.updated_at",
            (mac, name, pick("dept"), pick("role"), pick("shift"), pick("note"),
             pick("conditions"), pick("medications"), photo_val,
             pick("company"), pick("line"), age_val, schedule_val, paused,
             pause_by, pause_at, resume_at, schedule_by, schedule_at, now, now))
        if "staff_group" in doc:
            c.execute("UPDATE employees SET staff_group=? WHERE mac=?", (doc["staff_group"], mac))
        c.execute("UPDATE band_registry SET inactive_since=NULL WHERE mac=?", (mac,))
        c.commit()
    log(f"employee saved mac={mac} name={name!r}")
    _scan_policy_wake.set()
    return True, ""


def _monitoring_settings(c: sqlite3.Connection) -> dict:
    row = c.execute("SELECT * FROM monitoring_settings WHERE key='health_interval_s'").fetchone()
    return {"health_interval_s": int(row["value"]), "updated_by": row["updated_by"],
            "updated_at": row["updated_at"]}


def monitoring_settings() -> dict:
    with _lock:
        settings = _monitoring_settings(db())
        settings["policy_delivery"] = {gw: dict(value) for gw, value in _scan_policy_last.items()}
    return {"ok": True, **settings}


def set_monitoring_settings(doc: dict) -> tuple[bool, str]:
    actor = str(doc.get("actor") or "").strip().lower()
    if not can_manage_employee_scanning(get_role(actor) if actor else ""):
        return False, "forbidden"
    interval = doc.get("health_interval_s")
    if type(interval) is not int or not 60 <= interval <= 86400:
        return False, "invalid health interval"
    with _lock:
        c = db()
        c.execute("UPDATE monitoring_settings SET value=?,updated_by=?,updated_at=? "
                  "WHERE key='health_interval_s'", (str(interval), actor, time.time()))
        c.commit()
    _scan_policy_wake.set()
    return True, ""


def employee_scan_policy(now: float | None = None) -> dict:
    """Fail closed on overflow; assign each expected health scan to one receiver."""
    now = now if now is not None else time.time()
    now_dt = datetime.fromtimestamp(now, TEHRAN)
    with _lock:
        c = db()
        employees = []
        transitions = []
        for row in c.execute("SELECT * FROM employees ORDER BY mac"):
            state = _monitoring_state(row, now)
            employees.append({**dict(row), "weekly_schedule": state["weekly_schedule"]})
            transition = next_schedule_transition(state["weekly_schedule"], now_dt)
            if transition:
                transitions.append(transition.timestamp())
        error = None
        emergency_macs = sorted({r["mac"] for r in c.execute(
            "SELECT mac FROM employees WHERE staff_group='hse' AND mac IS NOT NULL")})
        try:
            health_active = sorted(active_employee_macs(employees, now_dt, limit=MAX_ACTIVE_MACS))
            # The gateway sees the union for presence, but only on-duty bands
            # belong in the ordinary-command list shared by all gateways.
            active = health_active
            if len(set(health_active) | set(emergency_macs)) > MAX_ACTIVE_MACS:
                raise ValueError("too many active employee wristbands")
        except ValueError as exc:
            active, health_active, emergency_macs, error = [], [], [], str(exc)
        transition = min(transitions) if transitions else None
        remaining = transition - now if transition is not None else 90
        lease = max(1, min(90, math.floor(remaining)))
        # Whole-second firmware leases cannot safely cross a fractional boundary.
        if remaining < 1:
            active, health_active = [], []
        installed = [r["gw"] for r in c.execute(
            "SELECT gw FROM gateway_registry WHERE kind='installed' ORDER BY gw")]
        health_by_gateway = {gw: [] for gw in installed}
        winners = _fresh_bands(c, now, installed_only=True)
        capable_fresh = {}
        for observation in c.execute(
                "SELECT b.mac,b.gw,g.last_seen,g.payload,b.rssi FROM band_observations b "
                "JOIN gateway_registry r ON r.gw=b.gw AND r.kind='installed' "
                "JOIN gateways g ON g.gw=b.gw "
                "WHERE b.seen_at BETWEEN ? AND ? "
                "AND g.last_seen BETWEEN ? AND ? "
                "ORDER BY b.mac,b.rssi DESC,b.gw",
                (now - PRESENCE_TTL, now, now - GATEWAY_ONLINE_TTL, now)):
            try:
                capabilities = json.loads(observation["payload"] or "{}")
            except (TypeError, ValueError):
                capabilities = {}
            if (isinstance(capabilities, dict)
                    and capabilities.get("manual_measurement") is True):
                capable_fresh.setdefault(observation["mac"], observation["gw"])
        last_seen = {}
        for row in c.execute(
                "SELECT b.mac,b.gw FROM band_observations b JOIN gateway_registry g ON g.gw=b.gw "
                "WHERE g.kind='installed' AND b.seen_at<=? ORDER BY b.seen_at DESC,b.rssi DESC,b.gw", (now,)):
            last_seen.setdefault(row["mac"], row["gw"])
        for mac in health_active:
            gw = (capable_fresh.get(mac) or winners.get(mac, {}).get("gw")
                  or last_seen.get(mac))
            if gw is None and installed:
                gw = installed[0]
            if gw in health_by_gateway:
                health_by_gateway[gw].append(mac)
        interval = _monitoring_settings(c)["health_interval_s"]
    return {"v": 1, "active_macs": active, "health_macs": health_active,
            "health_by_gateway": health_by_gateway,
            "emergency_macs": emergency_macs,
            "health_interval_s": interval, "generated_at": now, "lease_s": lease,
            "next_transition_at": transition, "error": error, "allow_unassigned": False}


def set_employee_monitoring(doc: dict) -> tuple[bool, str]:
    """Update an employee scan schedule or explicit pause, with role checks."""
    doc = dict(doc or {})
    mac = _norm_mac(doc.get("mac"))
    actor = str(doc.get("actor") or "").strip().lower()
    if not _valid_mac(mac):
        return False, "invalid mac"
    role = get_role(actor) if actor else ""
    if not can_manage_employee_scanning(role):
        return False, "forbidden"
    if "weekly_schedule" in doc and not can_manage_employee_schedules(role):
        return False, "forbidden"
    has_schedule = "weekly_schedule" in doc
    has_pause = "scan_paused" in doc
    if not has_schedule and not has_pause:
        return False, "no monitoring changes"
    try:
        schedule_json = (json.dumps(normalize_schedule(doc["weekly_schedule"]),
                                    ensure_ascii=False) if has_schedule else None)
    except (TypeError, ValueError):
        return False, "invalid schedule"
    if has_pause and type(doc["scan_paused"]) is not bool:
        return False, "invalid scan state"
    now = time.time()
    with _lock:
        c = db()
        row = c.execute("SELECT mac,scan_paused FROM employees WHERE mac=?", (mac,)).fetchone()
        if row is None:
            return False, "not found"
        assignments, values = [], []
        if has_schedule:
            assignments.extend(("weekly_schedule=?", "schedule_updated_by=?",
                                "schedule_updated_at=?"))
            values.extend((schedule_json, actor, now))
        if has_pause:
            paused = int(bool(doc["scan_paused"]))
            assignments.extend(("scan_paused=?", "scan_pause_by=?", "scan_pause_at=?"))
            values.extend((paused, actor if paused else None, now if paused else None))
            if not paused and row["scan_paused"]:
                assignments.append("scan_resume_at=?")
                values.append(now)
        assignments.append("updated_at=?")
        values.extend((now, mac))
        c.execute("UPDATE employees SET " + ",".join(assignments) + " WHERE mac=?", values)
        c.commit()
    _scan_policy_wake.set()
    applog.info("پایش کارکن تغییر کرد — فیلدهای %s، نقش %s",
                ",".join(k for k in ("weekly_schedule" if has_schedule else None,
                                     "scan_paused" if has_pause else None) if k), role)
    return True, ""


def remove_employee(mac) -> tuple[bool, str]:
    """Remove the employee and release its band atomically into inactive stock."""
    mac = _norm_mac(mac)
    if not _valid_mac(mac):
        return False, "invalid mac"
    with _lock:
        c = db()
        if c.execute("SELECT 1 FROM employees WHERE mac=?", (mac,)).fetchone() is None:
            return False, "not found"
        now = time.time()
        with c:
            c.execute("INSERT INTO band_registry(mac,label,note,created_at,updated_at,inactive_since) "
                      "VALUES(?, '', '', ?, ?, ?) ON CONFLICT(mac) DO UPDATE SET "
                      "inactive_since=excluded.inactive_since,updated_at=excluded.updated_at",
                      (mac, now, now, now))
            c.execute("DELETE FROM employees WHERE mac=?", (mac,))
            # MAC is the current assignment key; do not relabel an old person's
            # health/observation records as the next wearer of this band.
            for table in ("battery_alert_state", "health", "vitals", "events",
                          "bands", "band_observations", "manual_measurements"):
                c.execute("DELETE FROM " + table + " WHERE mac=?", (mac,))
    _delete_photos(mac)
    log(f"employee removed mac={mac}")
    _scan_policy_wake.set()
    return True, ""


_ble_discovery_lock = threading.Lock()


def discover_bands_for_admin(actor: str) -> list[dict]:
    """Run a short local-adapter scan, never for a secondary administrator."""
    if not actor or get_role(actor) != "owner":
        raise PermissionError("forbidden")
    if not _ble_discovery_lock.acquire(blocking=False):
        raise RuntimeError("جست‌وجوی بلوتوث دیگری در حال اجراست؛ چند لحظه صبر کنید")
    try:
        from ble_discovery import discover_nearby
        return asyncio.run(discover_nearby())
    finally:
        _ble_discovery_lock.release()


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
    _scan_policy_wake.set()
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
    _scan_policy_wake.set()
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
    network = {r["gw"]: r for r in c.execute(
        "SELECT * FROM network_gateway_observations WHERE seen_at BETWEEN ? AND ?",
        (now - GATEWAY_DISCOVERY_TTL, now))}
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
                           and 0 <= age <= GATEWAY_ONLINE_TTL),
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
            "online": bool(age is not None and 0 <= age <= GATEWAY_ONLINE_TTL),
            "fw": lv["fw"], "ip": lv["ip"], "adv_seen": lv["adv_seen"],
            "last_seen": _iso(lv["last_seen"]),
            "age_s": round(age, 1) if age is not None else None,
        })
    for row in rows:
        observation = network.pop(row["gw"], None)
        if observation is not None:
            row.update(_gateway_network_fields(observation))
    for gw, observation in sorted(network.items()):
        rows.append({"gw": gw, "label": None, "zone": None, "kind": "installed",
                     "mac": None, "x": None, "y": None, "note": None,
                     "registered": False, "online": False, "live": False,
                     "fw": None, "ip": None, "last_seen": None, "age_s": None,
                     **_gateway_network_fields(observation)})
    return rows


def _gateway_network_fields(observation: sqlite3.Row) -> dict:
    # The network interface MAC can differ from the serial provisioning identity.
    return {"network_seen": True, "network_ip": observation["ip"],
            "network_mac": observation["mac"], "network_fw": observation["fw"],
            "network_transport": observation["transport"],
            "network_mqtt_connected": bool(observation["mqtt_connected"]),
            "network_seen_at": _iso(observation["seen_at"])}


# ───────── آمادهسازی گیتوی — وایفای و آدرس سیستم ─────────
# خوراک صفحهٔ «آمادهسازی گیتوی»: ssid (و اختیاری رمز) وایفای همین سیستم +
# پیشنهاد آدرس MQTT که گیتوی تازه باید بشناسد. همه‌چیز «بهترین تلاش» است —
# نبود ابزار سیستمی یعنی رشتهٔ خالی، نه خطا.


def _child_process_options() -> dict:
    """Keep CLI children quiet in a windowed Windows bundle."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _run_cmd(args: list[str], timeout: float = 8.0) -> str | None:
    """اجرای یک فرمان سیستمی کوتاه — متن یا None؛ هرگز استثنا نمی‌دهد."""
    try:
        res = subprocess.run(args, capture_output=True, timeout=timeout,
                             **_child_process_options())
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
        # مسیر سریع و بدون اسکن: «nmcli dev wifi» برای فهرست شبکهها اسکن
        # زنده میزند و چند ثانیه طول میکشد — با تایمآوت ۴ ثانیهای اپ
        # بیمعنی بود. بهجایش: دستگاه وایفای متصل از dev status + SSID از
        # iw (netlink).
        iface = ""
        dev = _run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE",
                        "dev", "status"])
        if dev:
            for line in dev.splitlines():
                parts = line.rsplit(":", 2)
                if len(parts) == 3 and parts[1] == "wifi" \
                        and parts[2] == "connected":
                    iface = parts[0]
                    break
        if iface:
            source = "nmcli"
            link = _run_cmd(["iw", "dev", iface, "link"])
            if link:
                for line in link.splitlines():
                    line = line.strip()
                    if line.startswith("SSID:"):
                        ssid = line.split(":", 1)[1].strip()
                        break
            if not ssid:  # ابزار iw نبود — نام پروفایل اتصال فعال
                gen = _run_cmd(["nmcli", "-t", "-g", "GENERAL.CONNECTION",
                                "dev", "show", iface])
                ssid = (gen or "").strip()
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
    if sys.platform.startswith("win"):
        out = _run_cmd(["powershell", "-NoProfile", "-Command",
                        "Get-NetIPAddress -AddressFamily IPv4 | Select-Object InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json -Compress"])
        try:
            rows = json.loads(out or "[]")
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows:
                ip = str(row.get("IPAddress", ""))
                if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                    cands.append({"iface": str(row.get("InterfaceAlias", "")),
                                  "ip": ip, "prefix": str(row.get("PrefixLength", ""))})
        except (ValueError, TypeError, AttributeError):
            pass
        out = None
    else:
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
        if back and back["ts"] >= now - VITALS_TTL and _mac_data_visible(c, v["mac"], back["ts"], now):
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
    seen = _fresh_bands(c, now)
    zones = {r["gw"]: r["zone"] for r in c.execute("SELECT gw, zone FROM gateway_registry WHERE kind='installed'")}
    health_latest = {}
    for r in c.execute("SELECT * FROM health WHERE ts >= ? ORDER BY ts DESC",
                       (now - HEALTH_TTL,)):
        if _mac_data_visible(c, r["mac"], r["ts"], now):
            health_latest.setdefault(r["mac"], r)
    vitals_latest = {}
    for r in c.execute("SELECT * FROM vitals WHERE ts >= ? ORDER BY ts DESC",
                       (now - VITALS_TTL,)):
        if _mac_data_visible(c, r["mac"], r["ts"], now):
            vitals_latest.setdefault(r["mac"], r)
    attempts = {}
    for r in c.execute("SELECT * FROM events WHERE ts >= ? AND kind IN "
                       "('measure_unavailable','measure_ok','measure_fail') ORDER BY ts DESC,id DESC",
                       (now - HEALTH_TTL,)):
        if _mac_data_visible(c, r["mac"], r["ts"], now):
            attempts.setdefault(r["mac"], r)

    fresh = {m for m, b in seen.items()
             if b["seen_at"] >= now - PRESENCE_TTL
             and _mac_scan_eligible(c, m, now)}
    rows = []
    for mac in sorted(set(reg) | fresh):
        e = reg.get(mac)
        b = seen.get(mac)
        present = mac in fresh
        monitoring = _monitoring_state_for_mac(c, mac, now)
        active = monitoring["scan_allowed"]
        h = health_latest.get(mac) if active else None
        health = None
        if h:
            health = {
                "state": h["state"], "fail": h["fail"],
                "wearing": bool(h["wearing"]), "ended": bool(h["ended"]),
                "bpm": json.loads(h["bpm"] or "[]"), "n": h["n"], "avg": h["avg"],
                "ts": _iso(h["ts"]), "age_s": round(now - h["ts"], 1),
            }
        vitals = _employee_vitals(c, vitals_latest.get(mac), now) if active else None
        status, issues = _employee_status(present, health, vitals)
        attempt = attempts.get(mac)
        if (active and attempt is not None and attempt["kind"] == "measure_unavailable"
                and (h is None or attempt["ts"] >= h["ts"])):
            issues.append("measure_unavailable")
            if status != "danger":
                status = "warn"
        rows.append({
            "mac": mac,
            "registered": e is not None,
            "name": e["name"] if e else None,
            "dept": e["dept"] if e else None,
            "role": e["role"] if e else None,
            "shift": e["shift"] if e else None,
            "staff_group": e["staff_group"] if e else None,
            "weekly_schedule": monitoring["weekly_schedule"],
            "scheduled_now": monitoring["scheduled_now"],
            "scan_allowed": active if e else False,
            "monitoring_reason": monitoring["monitoring_reason"],
            "scan_paused": bool(e["scan_paused"]) if e else False,
            "scan_pause_by": e["scan_pause_by"] if e else None,
            "scan_pause_at": e["scan_pause_at"] if e else None,
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
            "location": _band_location(b),
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
    historical = {r["mac"]: r for r in c.execute("SELECT * FROM bands")}
    seen = _fresh_bands(c, now)
    zones = {r["gw"]: r["zone"] for r in c.execute("SELECT gw, zone FROM gateway_registry WHERE kind='installed'")}
    emp = {r["mac"]: r["name"] for r in c.execute("SELECT mac, name FROM employees")}
    rows = []
    for mac in sorted(set(reg) | set(historical) | set(emp)):
        b = seen.get(mac)
        in_view = bool(b is not None and b["seen_at"] >= now - PRESENCE_TTL
                       and _mac_scan_eligible(c, mac, now))
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
            "assignment_status": "active" if mac in emp else "inactive",
            "monitoring_active": bool(mac in emp and _mac_scan_eligible(c, mac, now)),
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
        } for r in _fresh_bands(c, now).values()]
        health = []
        seen_pairs = set()
        for r in c.execute("SELECT * FROM health WHERE ts >= ? ORDER BY ts DESC",
                           (now - HEALTH_TTL,)):
            if not _mac_data_visible(c, r["mac"], r["ts"], now):
                continue
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
            "employee_name": r["employee_name"],
        } for r in c.execute("SELECT e.*,p.name AS employee_name FROM events e "
                             "LEFT JOIN employees p ON p.mac=e.mac ORDER BY e.id DESC LIMIT 50")
            if r["kind"] != "measure_unavailable" or _mac_data_visible(c, r["mac"], r["ts"], now)]
        vitals = []
        seen_pairs = set()
        for r in c.execute("SELECT * FROM vitals WHERE ts >= ? ORDER BY ts DESC",
                           (now - VITALS_TTL,)):
            if not _mac_data_visible(c, r["mac"], r["ts"], now):
                continue
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
                if back and back["ts"] >= now - VITALS_TTL and _mac_data_visible(c, r["mac"], back["ts"], now):
                    v["spo2_ack"] = bool(back["spo2_ack"])
                    v["hrv_ack"] = bool(back["hrv_ack"])
                    v["spo2_raw"] = json.loads(back["spo2_raw"] or "[]")
                    v["hrv_raw"] = json.loads(back["hrv_raw"] or "[]")
                    v["vitals_ts"] = _iso(back["ts"])
                    v["vitals_age_s"] = round(now - back["ts"], 1)
            vitals.append(v)
        employees = _employees_view(c, now)
        map_gateways = _gateways_view(c, now)
        operational_alerts = _sync_operational_alerts(c, employees, map_gateways, now)
        manual_rows = []
        manual_by_mac = measurement_policy.latest_by_mac(c, now)
        for employee in employees:
            measurement = manual_by_mac.get(employee["mac"])
            if (measurement is not None and employee["registered"] and employee["scan_allowed"]
                    and _mac_data_visible(c, employee["mac"], measurement["requested_at"], now)):
                employee["manual_measurement"] = measurement
                manual_rows.append(measurement)
        battery_alert_rows = visible_battery_alerts(
            c, now, lambda mac, at, current: current - at <= VITALS_TTL
            and _mac_data_visible(c, mac, at, current))
        bands_known = _bands_known_view(c, now)
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
        "events": events, "battery_alerts": battery_alert_rows,
        "manual_measurements": manual_rows,
        **operational_alerts,
    }


def _sync_operational_alerts(c, employees, gateways, now):
    with c:
        measurement_policy.expire(c, now)
        operational_alert_policy.sync(c, employees, gateways, now)
        return operational_alert_policy.view(c, now)


# ───────────────────────────── MQTT ─────────────────────────────

SCAN_POLICY_PREFIX = "scan-policy"
_SCAN_POLICY_REFRESH_S = 5
_scan_policy_lock = threading.Lock()
_scan_policy_wake = threading.Event()
_scan_policy_cleared: set[str] = set()
_scan_policy_last: dict[str, dict] = {}


def gateway_ids() -> list[str]:
    """All known receiver topics, including receivers needing an empty revoke."""
    with _lock:
        rows = db().execute(
            "SELECT gw FROM gateway_registry UNION SELECT gw FROM gateways "
            "UNION SELECT gw FROM band_observations").fetchall()
    return sorted({str(row["gw"]) for row in rows if row["gw"] and _valid_gw(row["gw"])})


def publish_scan_policies() -> dict[str, str]:
    """Clear legacy retained permissions once, then send fresh non-retained leases."""
    results = {}
    with _scan_policy_lock:
        current_gateways = sorted(set(gateway_ids()) | set(_scan_policy_last))
        for gw in current_gateways:
            topic = f"roztash/{gw}/{SCAN_POLICY_PREFIX}"
            clear_error = None
            if gw not in _scan_policy_cleared:
                try:
                    cleared, detail = publish(topic, "", retained=True)
                except Exception as exc:
                    cleared, detail = False, str(exc)
                if cleared:
                    _scan_policy_cleared.add(gw)
                else:
                    clear_error = "retained clear failed: " + detail
            # Re-evaluate after slow I/O and between gateways: never renew an old shift.
            policy = employee_scan_policy()
            payload = {key: policy[key] for key in
                       ("v", "active_macs", "emergency_macs", "health_interval_s", "lease_s", "generated_at")}
            payload["health_macs"] = policy["health_by_gateway"].get(gw, [])
            try:
                ok, detail = publish(topic, json.dumps(payload, separators=(",", ":")), retained=False)
            except Exception as exc:
                ok, detail = False, str(exc)
            error = clear_error or (None if ok else detail)
            results[gw] = error or "sent"
            with _lock:
                previous = _scan_policy_last.get(gw, {})
                _scan_policy_last[gw] = {"attempted_at": time.time(),
                    "sent_at": time.time() if ok else previous.get("sent_at"),
                    "ok": ok and clear_error is None, "error": error,
                    "policy_error": policy["error"], "retained_cleared": gw in _scan_policy_cleared}
    return results


_battery_dispatch_lock = threading.Lock()


def dispatch_battery_alerts(now: float | None = None) -> dict:
    """Try pending episodes outside the DB lock; ACKs alone confirm vibration."""
    results = {}
    with _battery_dispatch_lock:
        moment = time.time() if now is None else now
        with _lock:
            candidates = [row["mac"] for row in pending_battery_rows(db(), moment)]
        for mac in candidates:
            moment = time.time() if now is None else now
            with _lock:
                c = db()
                row = c.execute("SELECT * FROM battery_alert_state WHERE mac=?", (mac,)).fetchone()
                if row is None or not row["active"] or row["confirmed_at"] is not None:
                    continue
                retry_window_over = (row["first_attempt_at"] is not None
                                     and moment - row["first_attempt_at"] >= battery_policy.RETRY_WINDOW_SECONDS)
                if row["attempts"] >= battery_policy.MAX_ATTEMPTS or retry_window_over:
                    if row["delivery_status"] != "failed":
                        c.execute("UPDATE battery_alert_state SET delivery_status='unconfirmed',"
                                  "last_error='ack_not_received' WHERE mac=?", (mac,))
                    c.commit()
                    continue
                if (row["next_attempt_at"] > moment or moment - row["sample_at"] > VITALS_TTL
                        or not _mac_data_visible(c, mac, row["sample_at"], moment)):
                    continue
                # After any attempt keep retries on the same receiver; its dedupe cache
                # prevents a lost ACK from triggering a second physical vibration.
                gw = row["last_gateway"] if row["attempts"] else None
                if not gw:
                    gw = _fresh_bands(c, moment, installed_only=True).get(mac, {}).get("gw")
                observation = (c.execute("SELECT b.seen_at FROM band_observations b "
                                        "JOIN gateway_registry g ON g.gw=b.gw "
                                        "WHERE b.mac=? AND b.gw=? AND g.kind='installed'",
                                        (mac, gw)).fetchone() if gw else None)
                status = c.execute("SELECT last_seen,payload FROM gateways WHERE gw=?", (gw,)).fetchone() if gw else None
                error = None
                if (observation is None or not 0 <= moment - observation["seen_at"] <= PRESENCE_TTL
                        or not _mac_data_visible(c, mac, observation["seen_at"], moment)):
                    error = "band_unavailable"
                elif status is None or not status["last_seen"] or not 0 <= moment - status["last_seen"] <= GATEWAY_ONLINE_TTL:
                    error = "gateway_unavailable"
                else:
                    try:
                        capabilities = json.loads(status["payload"] or "{}")
                    except (TypeError, ValueError):
                        capabilities = {}
                    if not isinstance(capabilities, dict) or capabilities.get("vibration_request_id") is not True:
                        error = "gateway_update_required"
                    elif capabilities.get("scan_policy_ready") is not True:
                        error = "policy_unavailable"
                if error:
                    c.execute("UPDATE battery_alert_state SET last_error=? WHERE mac=?", (error, mac))
                    c.commit()
                    continue
                # The firmware's command queue has one slot. Don't flood one receiver.
                busy = c.execute("SELECT 1 FROM battery_alert_state WHERE mac!=? AND last_gateway=? "
                                 "AND active=1 AND confirmed_at IS NULL AND attempts>0 "
                                 "AND delivery_status IN ('dispatching','awaiting_ack') AND next_attempt_at>?",
                                 (mac, gw, moment)).fetchone()
                staff_busy = c.execute(
                    "SELECT 1 FROM staff_alert_delivery WHERE gateway=? AND status='awaiting_ack' "
                    "AND next_attempt_at>? AND attempts<? "
                    "AND (? - COALESCE(first_attempt_at,?))<? LIMIT 1",
                    (gw, moment, staff_alert_policy.MAX_ATTEMPTS, moment, moment,
                     staff_alert_policy.RETRY_WINDOW_SECONDS)).fetchone()
                if busy or staff_busy:
                    continue
                request = claim_battery(c, row, gw, moment)
                c.commit()
            if request is None:
                continue
            try:
                ok, detail = publish(f"roztash/{gw}/cmd", json.dumps(request, separators=(",", ":")), retained=False)
            except Exception:
                ok, detail = False, "publish_failed"
            with _lock:
                record_battery_publish(db(), request, gw, moment, ok)
                db().commit()
            results[mac] = "sent" if ok else "publish_failed"
    return results


_staff_alert_dispatch_lock = threading.Lock()


def dispatch_alert_notifications(now: float | None = None) -> dict:
    """Deliver current alert episodes through durable, correlated gateway commands."""
    moment = time.time() if now is None else now
    results = {}
    with _staff_alert_dispatch_lock:
        policy = employee_scan_policy(moment)
        with _lock:
            c = db()
            employees = _employees_view(c, moment)
            # Keep alert episodes and request expiry current with no UI open.
            _sync_operational_alerts(c, employees, _gateways_view(c, moment), moment)
            episodes = staff_alert_policy.sync_episodes(c, employees, moment)
            by_mac = {str(row.get("mac") or "").lower(): row for row in employees}
            for episode in episodes.values():
                source = by_mac.get(episode["source_mac"])
                if source:
                    staff_alert_policy.add_recipients(
                        c, episode, alert_recipients(source, employees), moment)

            fresh = _fresh_bands(c, moment, installed_only=True)
            rows = c.execute(
                "SELECT d.*,e.opened_at FROM staff_alert_delivery d "
                "JOIN staff_alert_episode e ON e.id=d.episode_id "
                "WHERE e.closed_at IS NULL AND d.status IN ('pending','failed','unconfirmed','awaiting_ack') "
                "AND d.next_attempt_at<=? ORDER BY e.opened_at,d.target_mac", (moment,)).fetchall()
            used_gateways, claims = set(), []
            for row in rows:
                target, group = row["target_mac"], row["target_group"]
                expired = (row["attempts"] >= staff_alert_policy.MAX_ATTEMPTS or
                    (row["first_attempt_at"] is not None and
                     moment-row["first_attempt_at"] >= staff_alert_policy.RETRY_WINDOW_SECONDS))
                if expired and row["status"] != "unconfirmed":
                    c.execute("UPDATE staff_alert_delivery SET status='unconfirmed',last_error='ack_not_received' "
                              "WHERE request_id=? AND status!='confirmed'", (row["request_id"],))
                    row = c.execute("SELECT * FROM staff_alert_delivery WHERE request_id=?",
                                    (row["request_id"],)).fetchone()
                if row["status"] == "unconfirmed":
                    # The gateway may still have this request in its duplicate
                    # cache. Do not move the same request to another gateway.
                    continue
                if group == "hse":
                    allowed = target in policy["emergency_macs"]
                else:
                    allowed = target in policy["active_macs"]
                if not allowed:
                    continue
                gw = row["gateway"] or (fresh.get(target) or {}).get("gw")
                if not gw or gw in used_gateways:
                    continue
                status = c.execute("SELECT last_seen,payload FROM gateways WHERE gw=?", (gw,)).fetchone()
                if status is None or not status["last_seen"] or not 0 <= moment-status["last_seen"] <= GATEWAY_ONLINE_TTL:
                    continue
                try:
                    capabilities = json.loads(status["payload"] or "{}")
                except (TypeError, ValueError):
                    capabilities = {}
                if (not isinstance(capabilities, dict)
                        or capabilities.get("scan_policy_ready") is not True
                        or capabilities.get("vibration_request_id") is not True
                        or capabilities.get("vibration_repeats") not in (True, 3)):
                    continue
                observed = c.execute("SELECT seen_at FROM band_observations WHERE mac=? AND gw=?",
                                     (target, gw)).fetchone()
                if observed is None or not 0 <= moment-observed["seen_at"] <= PRESENCE_TTL:
                    continue
                waiting = c.execute(
                    "SELECT 1 FROM staff_alert_delivery WHERE gateway=? AND request_id!=? "
                    "AND status='awaiting_ack' AND next_attempt_at>? AND attempts<? "
                    "AND (? - COALESCE(first_attempt_at,?))<? LIMIT 1",
                    (gw, row["request_id"], moment, staff_alert_policy.MAX_ATTEMPTS,
                     moment, moment, staff_alert_policy.RETRY_WINDOW_SECONDS)).fetchone()
                if waiting:
                    continue
                battery_busy = c.execute(
                    "SELECT 1 FROM battery_alert_state WHERE last_gateway=? AND active=1 "
                    "AND confirmed_at IS NULL AND attempts>0 AND delivery_status IN ('dispatching','awaiting_ack') "
                    "AND next_attempt_at>? LIMIT 1", (gw, moment)).fetchone()
                if battery_busy:
                    continue
                c.execute("UPDATE staff_alert_delivery SET attempts=attempts+1,gateway=?,status='awaiting_ack',"
                          "next_attempt_at=?,first_attempt_at=COALESCE(first_attempt_at,?),sent_at=?,last_error=NULL "
                          "WHERE request_id=?",
                          (gw,moment+staff_alert_policy.RETRY_SECONDS,moment,moment,row["request_id"]))
                claims.append((row,gw))
                used_gateways.add(gw)
            c.commit()
        for row,gw in claims:
            request={"action":"vibrate","mac":row["target_mac"],"request_id":row["request_id"],
                     "reason":"staff_alert","ttl_s":60,"repeats":3,
                     "completed_pulses":row["completed_pulses"]}
            if row["target_group"]=="hse": request["emergency"]=True
            try:
                ok,detail=publish(f"roztash/{gw}/cmd",json.dumps(request,separators=(",",":")),retained=False)
            except Exception as exc:
                ok,detail=False,str(exc)
            if not ok:
                with _lock:
                    c=db()
                    c.execute("UPDATE staff_alert_delivery SET status='failed',last_error=? WHERE request_id=? "
                              "AND status NOT IN ('confirmed','closed','cancelled')",
                              (str(detail)[:160],row["request_id"]))
                    c.commit()
            results[row["target_mac"]]="sent" if ok else "publish_failed"
    return results


def scan_policy_loop() -> None:
    while True:
        _scan_policy_wake.clear()
        started = time.monotonic()
        try:
            results = publish_scan_policies()
            for gw, result in results.items():
                if result != "sent":
                    log(f"scan policy not delivered to {gw}: {result}")
            dispatch_battery_alerts()
            dispatch_alert_notifications()
            policy = employee_scan_policy()
            transition = policy["next_transition_at"]
            delay = max(0.05, _SCAN_POLICY_REFRESH_S - (time.monotonic() - started))
            if transition is not None:
                delay = min(delay, max(0.05, transition - time.time()))
        except Exception as exc:
            log(f"scan policy refresh failed: {exc!r}")
            delay = _SCAN_POLICY_REFRESH_S
        _scan_policy_wake.wait(delay)


def subscriber_loop() -> None:
    cmd = [os.environ.get("ROZTASH_MOSQUITTO_SUB") or "mosquitto_sub",
           "-h", MQTT_HOST, "-p", str(MQTT_PORT),
           "-t", MQTT_TOPIC, "-F", "%t %p"]
    while True:
        p = None
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                 **_child_process_options())
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


def publish(topic: str, payload: str, retained: bool = False) -> tuple[bool, str]:
    """انتشار یک پیام روی بروکر — برای فرمان‌ها و سیاست اسکن retained."""
    try:
        cmd = [os.environ.get("ROZTASH_MOSQUITTO_PUB") or "mosquitto_pub",
               "-h", MQTT_HOST, "-p", str(MQTT_PORT)]
        if retained:
            cmd.append("-r")
        cmd.extend(["-t", topic, "-m", payload])
        p = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=5, **_child_process_options())
        if p.returncode == 0:
            return True, "sent"
        return False, (p.stderr or p.stdout or "mosquitto_pub failed").strip()[:200]
    except Exception as exc:  # noqa: BLE001 — هر خطای اجرا به پاسخ برمی‌گردد
        return False, repr(exc)[:200]


def request_measurement(doc: dict, now: float | None = None) -> tuple[bool, str, dict]:
    """Queue an authenticated, on-duty request; publication is not a result."""
    moment = time.time() if now is None else now
    actor = str(doc.get("actor") or "").strip().lower()
    if not actor or not can_manage_employee_scanning(get_role(actor)):
        return False, "forbidden", {}
    mac = _norm_mac(doc.get("mac"))
    if not _valid_mac(mac):
        return False, "invalid mac", {}
    vitals = doc.get("vitals", False)
    if type(vitals) is not bool:
        return False, "invalid measurement", {}
    scan_policy = employee_scan_policy(moment)
    assigned_gateways = {gw for gw, macs in scan_policy["health_by_gateway"].items()
                         if mac in macs}
    with _lock:
        c = db()
        employee = c.execute("SELECT * FROM employees WHERE mac=?", (mac,)).fetchone()
        if employee is None:
            return False, "not found", {}
        monitoring = _monitoring_state(employee, moment)
        if not monitoring["scan_allowed"]:
            return False, "employee monitoring is paused or outside scheduled hours", {}
        earliest = max(moment - PRESENCE_TTL, monitoring["data_floor"] or 0)
        observations = c.execute(
            "SELECT b.gw,g.last_seen,g.payload FROM band_observations b "
            "JOIN gateway_registry r ON r.gw=b.gw AND r.kind='installed' "
            "LEFT JOIN gateways g ON g.gw=b.gw WHERE b.mac=? AND b.seen_at BETWEEN ? AND ? "
            "ORDER BY b.rssi DESC,b.gw", (mac, earliest, moment)).fetchall()
        if not observations:
            return False, "band unavailable", {}
        online = [row for row in observations if row["last_seen"] and
                  0 <= moment-row["last_seen"] <= GATEWAY_ONLINE_TTL]
        if not online:
            return False, "gateway unavailable", {}
        capable = []
        for row in online:
            try:
                caps = json.loads(row["payload"] or "{}")
            except (ValueError, TypeError):
                caps = {}
            if isinstance(caps, dict) and caps.get("manual_measurement") is True:
                capable.append((row, caps))
        if not capable:
            return False, "gateway update required", {}
        ready = [(row, caps) for row, caps in capable
                 if caps.get("scan_policy_ready") is True]
        if not ready:
            return False, "gateway policy unavailable", {}
        # Route only through a receiver which holds this MAC's current lease.
        # Scan policy prefers a capable fresh observer when available; the
        # strongest observation may be older firmware or not yet authorized.
        ready = [(row, caps) for row, caps in ready if row["gw"] in assigned_gateways]
        if not ready:
            return False, "assigned gateway unavailable", {}
        gw = ready[0][0]["gw"]
        with c:
            measurement_policy.expire(c, moment)
        active = c.execute("SELECT request_id FROM manual_measurements WHERE mac=? "
                           "AND status IN ('pending','queued','started') LIMIT 1", (mac,)).fetchone()
        if active:
            return False, "measurement already pending", {"request_id":active["request_id"]}
        request_id = "measure-" + uuid.uuid4().hex
        c.execute("INSERT INTO manual_measurements(request_id,mac,gateway,actor,requested_at,"
                  "expires_at,status,detail,updated_at) VALUES(?,?,?,?,?,?,'pending','',?)",
                  (request_id, mac, gw, actor, moment, moment + 120, moment))
        c.commit()
    payload = {"action":"measure","mac":mac,"request_id":request_id,"ttl_s":60,"vitals":vitals}
    try:
        ok, detail = publish(f"roztash/{gw}/cmd", json.dumps(payload,separators=(",",":")), retained=False)
    except Exception:
        ok, detail = False, "publish failed"
    with _lock:
        c = db()
        if not ok:
            c.execute("UPDATE manual_measurements SET status='failed',detail='publish failed',updated_at=? "
                      "WHERE request_id=? AND status='pending'", (moment,request_id))
        c.commit()
    return ok, "" if ok else "publish failed", {"gw":gw,"request_id":request_id,"status":"pending"}


def discover_network_gateways(*, actor: str, now: float | None = None):
    """Perform bounded LAN UDP discovery and persist observations, not online state."""
    actor = str(actor or "").strip().lower()
    if not actor or not can_manage_gateways(get_role(actor)):
        return False, "forbidden", []
    try:
        rows = gateway_discovery.discover_gateways(candidates=_host_ip_candidates(), timeout_s=2.0)
    except (OSError, RuntimeError, ValueError) as exc:
        log(f"gateway network discovery failed: {type(exc).__name__}")
        return False, "network discovery failed", []
    moment = time.time() if now is None else float(now)
    with _lock:
        c = db()
        c.execute("DELETE FROM network_gateway_observations WHERE seen_at<?",
                  (moment - GATEWAY_DISCOVERY_TTL,))
        for row in rows:
            c.execute(
                "INSERT INTO network_gateway_observations(gw,mac,fw,ip,transport,mqtt_connected,seen_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(gw) DO UPDATE SET "
                "mac=excluded.mac,fw=excluded.fw,ip=excluded.ip,transport=excluded.transport,"
                "mqtt_connected=excluded.mqtt_connected,seen_at=excluded.seen_at",
                (row["gw"], row["mac"], row["fw"], row["ip"], row["transport"],
                 int(row["mqtt_connected"]), moment),
            )
        c.commit()
    return True, "", rows


def acknowledge_live_alert(doc: dict, now: float | None = None):
    actor = str(doc.get("actor") or "").strip().lower()
    if not actor or not can_manage_employee_scanning(get_role(actor)):
        return False, "forbidden"
    alert_id = doc.get("id")
    with _lock:
        c = db()
        ok, error = operational_alert_policy.acknowledge(
            c, alert_id, actor, time.time() if now is None else now)
        c.commit()
    return ok, error


def gateway_diagnostic(doc: dict, now: float | None = None):
    """Start or poll one owner-only gateway diagnostic without changing policy."""
    moment = time.time() if now is None else float(now)
    actor = str((doc or {}).get("actor") or "").strip().lower()
    if not actor or not can_manage_gateways(get_role(actor)):
        return False, "forbidden", {}
    action = str((doc or {}).get("action") or "").strip()
    if action == "status":
        with _lock:
            return diagnostic_policy.status(db(), (doc or {}).get("request_id"), moment)
    with _lock:
        ok, error, info, command_doc = diagnostic_policy.create(
            db(), actor=actor, action=action, gw=(doc or {}).get("gw"),
            mac=(doc or {}).get("mac"), now=moment)
    if not ok:
        return False, error, info
    try:
        sent, _detail = publish(
            f"roztash/{info['gw']}/cmd",
            json.dumps(command_doc, separators=(",", ":")), retained=False)
    except Exception:
        sent = False
    if not sent:
        with _lock:
            info = diagnostic_policy.publish_failed(db(), info["request_id"], moment)
        return False, "publish failed", info
    return True, "", info


def command(doc: dict) -> tuple[bool, str, dict]:
    """فرمان را روی roztash/<gw>/cmd منتشر می‌کند؛ گیت‌وی همان مچ‌بند را می‌فرستد.

    برمی‌گرداند: (ok، متن خطا، اطلاعات مسیر). مچ‌بند ناشناس باشد، سراغ
    تازه‌ترین گیت‌وی می‌رود.
    """
    action = str((doc or {}).get("action") or "").strip()
    mac = str((doc or {}).get("mac") or "").strip().lower()
    gw = str((doc or {}).get("gw") or "").strip()
    emergency = bool((doc or {}).get("emergency"))
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
    if not emergency:
        try:
            policy = employee_scan_policy()
        except ValueError:
            return False, "gateway scan capacity exceeded", {}
    else:
        policy = {"active_macs": []}
    with _lock:
        assigned = db().execute("SELECT mac,staff_group FROM employees WHERE mac=?", (mac,)).fetchone()
    if emergency and (assigned is None or assigned["staff_group"] != "hse"):
        return False, "emergency vibration is only for HSE", {}
    if not emergency and assigned is not None and mac not in policy["health_macs"]:
        return False, "employee monitoring is paused or outside scheduled hours", {}
    topic = f"roztash/{gw}/cmd"
    command_doc = {"action": action, "mac": mac}
    if emergency:
        command_doc["emergency"] = True
    payload = json.dumps(command_doc, ensure_ascii=False)
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
        elif path == "/api/monitoring":
            self._send(200, {"ok": True, "scan_policy": employee_scan_policy()})
        elif path == "/api/monitoring/settings":
            self._send(200, monitoring_settings())
        elif path == "/api/bands":
            self._send(200, {"ok": True, "bands": bands_list()})
        elif path == "/api/bands/scan":
            actor = verify_request("GET", self.path, b"", self.headers)
            if not actor:
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                devices = discover_bands_for_admin(actor)
            except PermissionError:
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            except RuntimeError as exc:
                self._send(503, {"ok": False, "error": str(exc)})
                return
            self._send(200, {"ok": True, "devices": devices})
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
        if path not in ("/api/command", "/api/measurements", "/api/alerts/ack",
                        "/api/gateways/diagnostics",
                        "/api/gateways/discover", "/api/employees", "/api/monitoring", "/api/monitoring/settings",
                        "/api/bands", "/api/catalogs", "/api/gateways"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0:
                raise ValueError("invalid content length")
            if length > 8_000_000:  # عکس پرسنلی base64 هم جا می‌شود
                self._send(413, {"ok": False, "error": "body too large"})
                return
            body = self.rfile.read(length)
            doc = json.loads(body or b"{}")
            if not isinstance(doc, dict):
                raise ValueError("body must be an object")
        except Exception:
            self._send(400, {"ok": False, "error": "bad json body"})
            return
        if path in ("/api/monitoring", "/api/monitoring/settings", "/api/measurements",
                    "/api/gateways/diagnostics",
                    "/api/alerts/ack", "/api/gateways/discover"):
            actor = verify_request("POST", self.path, body, self.headers)
            if not actor or doc.get("actor") != actor:
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
        if path == "/api/measurements":
            ok, err, info = request_measurement(doc)
            self._send(200 if ok else (403 if err == "forbidden" else 400),
                       {"ok":ok,"error":err or None,"info":info})
        elif path == "/api/gateways/diagnostics":
            ok, err, info = gateway_diagnostic(doc)
            code = 200 if ok else (403 if err == "forbidden" else
                   (409 if err == "diagnostic busy" else (404 if err == "not found" else 400)))
            self._send(code, {"ok":ok,"error":err or None,"info":info})
        elif path == "/api/alerts/ack":
            ok, err = acknowledge_live_alert(doc)
            self._send(200 if ok else (403 if err == "forbidden" else 400),
                       {"ok":ok,"error":err or None})
        elif path == "/api/gateways/discover":
            ok, err, rows = discover_network_gateways(actor=str(doc.get("actor") or ""))
            self._send(200 if ok else (403 if err == "forbidden" else 503),
                       {"ok":ok,"error":err or None,"gateways":rows})
        elif path == "/api/command":
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
        elif path == "/api/monitoring":
            ok, err = set_employee_monitoring(doc)
            code = 200 if ok else (403 if err == "forbidden" else 400)
            self._send(code, {"ok": ok, "error": err or None})
        elif path == "/api/monitoring/settings":
            ok, err = set_monitoring_settings(doc)
            code = 200 if ok else (403 if err == "forbidden" else 400)
            self._send(code, {"ok": ok, "error": err or None})
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
            actor = verify_request("DELETE", self.path, b"", self.headers)
            if not actor:
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            if not can_delete_employees(get_role(actor)):
                self._send(403, {"ok": False, "error": "forbidden"})
                return
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
    db()  # Finish schema setup before either worker can access the connection.
    
    # Start discovery server for zero-config networking
    discovery_server = DiscoveryServer(MQTT_HOST, int(MQTT_PORT))
    threading.Thread(target=discovery_server.start, daemon=True).start()
    log(f"discovery server started on port {DISCOVERY_PORT}")
    
    threading.Thread(target=subscriber_loop, daemon=True).start()
    threading.Thread(target=scan_policy_loop, daemon=True).start()
    srv = Server((HTTP_HOST, HTTP_PORT), Handler)
    log(f"http on http://{HTTP_HOST}:{HTTP_PORT}  db={DB_PATH}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        discovery_server.stop()
        log("bye")


if __name__ == "__main__":
    main()
