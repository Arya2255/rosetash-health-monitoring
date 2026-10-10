#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""پل زندهٔ روزتاش — MQTT → SQLite → HTTP JSON API.

مصرف‌کننده‌ها:
  - src/data.py — حالت زندهٔ برنامهٔ فلت با GET /api/snapshot
  - ابزارهای دمو و عیب‌یابی با GET /health و /api/events

قواعد طراحی:
  - فقط کتابخانهٔ استاندارد پایتون
  - اشتراک MQTT با mosquitto_sub به‌عنوان زیرفرایند و حلقهٔ بازاتصال
  - TTL حضور ۶۰ ثانیه — هماهنگ با فریمور گیتوی
  - TTL سلامت ۱۵ دقیقه — برای نمایش آخرین اندازه‌گیری
  - گیتوی آنلاین اگر status آن کمتر از ۱۸۰ ثانیه پیش رسیده باشد
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MQTT_HOST = os.environ.get("ROZTASH_MQTT_HOST", "127.0.0.1")
MQTT_PORT = os.environ.get("ROZTASH_MQTT_PORT", "1884")
MQTT_TOPIC = os.environ.get("ROZTASH_MQTT_TOPIC", "roztash/#")
HTTP_HOST = os.environ.get("ROZTASH_BRIDGE_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("ROZTASH_BRIDGE_PORT", "8726"))
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("ROZTASH_BRIDGE_DB", os.path.join(HERE, "state", "live.db"))

PRESENCE_TTL = float(os.environ.get("ROZTASH_PRESENCE_TTL", "60"))
HEALTH_TTL = float(os.environ.get("ROZTASH_HEALTH_TTL", "900"))
GATEWAY_ONLINE_TTL = float(os.environ.get("ROZTASH_GATEWAY_ONLINE_TTL", "180"))
EVENTS_KEEP = 3000
HEALTH_KEEP = 5000

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
        else:
            c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
                      (ts, gw, doc.get("type", leaf), doc.get("mac"), payload))
        # هرس سبک
        c.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (EVENTS_KEEP,))
        c.execute("DELETE FROM health WHERE id <= (SELECT MAX(id) FROM health) - ?", (HEALTH_KEEP,))
        c.commit()


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
    return {
        "ok": True, "fetched_at": _iso(now), "now": now,
        "presence_ttl": PRESENCE_TTL, "health_ttl": HEALTH_TTL,
        "gateways": gws, "bands": bands, "health": health, "events": events,
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


# ───────────────────────────── HTTP ─────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "roztash-bridge/0.1"

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
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def log_message(self, format: str, *args) -> None:  # noqa: A002 — امضای والد
        return


def main() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    threading.Thread(target=subscriber_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), Handler)
    log(f"http on http://{HTTP_HOST}:{HTTP_PORT}  db={DB_PATH}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("bye")


if __name__ == "__main__":
    main()
