"""Persistent low-battery episodes and correlated vibration delivery.

Pure SQLite state transitions. Callers hold the bridge DB lock; no network I/O here.
"""
from __future__ import annotations

import json
import uuid

WARN_PERCENT = 20
RECOVER_PERCENT = 30
MAX_ATTEMPTS = 3
RETRY_SECONDS = 120
RETRY_WINDOW_SECONDS = 480  # stays inside gateway duplicate memory even with command TTL
COMMAND_TTL_SECONDS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS battery_alert_state(
  mac TEXT PRIMARY KEY,
  episode_id TEXT,
  active INTEGER NOT NULL DEFAULT 0,
  battery INTEGER NOT NULL,
  sample_at REAL NOT NULL,
  opened_at REAL,
  resolved_at REAL,
  request_id TEXT,
  delivery_status TEXT NOT NULL DEFAULT 'none',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at REAL NOT NULL DEFAULT 0,
  first_attempt_at REAL,
  last_gateway TEXT,
  sent_at REAL,
  confirmed_at REAL,
  last_error TEXT);
"""


def ensure_schema(c):
    c.executescript(SCHEMA)
    columns = {row[1] for row in c.execute("PRAGMA table_info(battery_alert_state)")}
    if "first_attempt_at" not in columns:
        c.execute("ALTER TABLE battery_alert_state ADD COLUMN first_attempt_at REAL")
        # A legacy attempted delivery has unknown dedupe age: never blindly resend.
        c.execute("UPDATE battery_alert_state SET first_attempt_at=0 WHERE attempts>0")


def valid_percent(value) -> bool:
    return type(value) is int and 0 <= value <= 100


def _event(c, at, gw, kind, mac, **details):
    c.execute("INSERT INTO events(ts,gw,kind,mac,payload) VALUES(?,?,?,?,?)",
              (at, gw, kind, mac, json.dumps(details, separators=(",", ":"))))


def observe(c, mac, gw, level, at):
    """Record only fresh valid samples; 20/30 hysteresis suppresses alert chatter."""
    if not valid_percent(level):
        return
    row = c.execute("SELECT * FROM battery_alert_state WHERE mac=?", (mac,)).fetchone()
    if row is not None and at <= row["sample_at"]:
        return
    if row is None:
        c.execute("INSERT INTO battery_alert_state(mac,battery,sample_at) VALUES(?,?,?)",
                  (mac, level, at))
        active = False
    else:
        active = bool(row["active"])
        c.execute("UPDATE battery_alert_state SET battery=?,sample_at=? WHERE mac=?",
                  (level, at, mac))
    if active and level >= RECOVER_PERCENT:
        c.execute("UPDATE battery_alert_state SET active=0,resolved_at=?,"
                  "delivery_status='resolved',last_error=NULL WHERE mac=?", (at, mac))
        _event(c, at, gw, "battery_recovered", mac, battery=level)
    elif not active and level <= WARN_PERCENT:
        episode = uuid.uuid4().hex
        c.execute("UPDATE battery_alert_state SET active=1,episode_id=?,opened_at=?,"
                  "resolved_at=NULL,request_id=?,delivery_status='pending',attempts=0,"
                  "next_attempt_at=?,first_attempt_at=NULL,last_gateway=NULL,sent_at=NULL,confirmed_at=NULL,"
                  "last_error=NULL WHERE mac=?",
                  (episode, at, "battery-" + episode, at, mac))
        _event(c, at, gw, "battery_low", mac, battery=level, request_id="battery-" + episode)


def record_result(c, gw, doc, at):
    """Only a matching device result can confirm an automatic battery warning."""
    if doc.get("reason") != "battery_low" or not isinstance(doc.get("request_id"), str):
        return
    kind = doc.get("type")
    if kind not in ("vibrated", "vibrate_fail", "cmd_reject"):
        return
    mac = doc.get("mac")
    row = c.execute("SELECT * FROM battery_alert_state WHERE mac=?", (mac,)).fetchone()
    if (row is None or not row["active"] or row["confirmed_at"] is not None
            or row["request_id"] != doc["request_id"] or row["last_gateway"] != gw
            or row["attempts"] == 0 or at < row["opened_at"]):
        return
    if kind == "vibrated":
        c.execute("UPDATE battery_alert_state SET delivery_status='confirmed',confirmed_at=?,"
                  "last_error=NULL WHERE mac=?", (at, mac))
        _event(c, at, gw, "battery_vibration_confirmed", mac, request_id=row["request_id"])
    else:
        error = "vibration_failed" if kind == "vibrate_fail" else "command_rejected"
        c.execute("UPDATE battery_alert_state SET delivery_status='failed',last_error=? WHERE mac=?",
                  (error, mac))
        _event(c, at, gw, "battery_vibration_failed", mac, request_id=row["request_id"], error=error)


def claim(c, row, gw, now):
    """Persist the attempt before publishing to prevent concurrent duplicate sends."""
    if row["attempts"] >= MAX_ATTEMPTS or row["next_attempt_at"] > now:
        return None
    c.execute("UPDATE battery_alert_state SET attempts=attempts+1,next_attempt_at=?,"
              "first_attempt_at=COALESCE(first_attempt_at,?),"
              "last_gateway=?,delivery_status='dispatching',last_error=NULL WHERE mac=?",
              (now + RETRY_SECONDS, now, gw, row["mac"]))
    return {"action": "vibrate", "mac": row["mac"], "request_id": row["request_id"],
            "reason": "battery_low", "ttl_s": COMMAND_TTL_SECONDS}


def record_publish(c, request, gw, now, ok):
    row = c.execute("SELECT * FROM battery_alert_state WHERE mac=?", (request["mac"],)).fetchone()
    if (row is None or not row["active"] or row["request_id"] != request["request_id"]):
        return
    # The subscriber may have received a device ACK while the publisher was running.
    if row["delivery_status"] == "dispatching":
        c.execute("UPDATE battery_alert_state SET delivery_status=?,last_error=? WHERE mac=?",
                  ("awaiting_ack" if ok else "failed", None if ok else "publish_failed", request["mac"]))
    if ok:
        c.execute("UPDATE battery_alert_state SET sent_at=? WHERE mac=?", (now, request["mac"]))
    _event(c, now, gw, "battery_vibration_sent" if ok else "battery_vibration_failed",
           request["mac"], request_id=request["request_id"],
           error=None if ok else "publish_failed")


def pending_rows(c, now):
    return c.execute("SELECT b.* FROM battery_alert_state b JOIN employees e ON e.mac=b.mac "
                     "WHERE b.active=1 AND b.confirmed_at IS NULL AND b.next_attempt_at<=? "
                     "ORDER BY b.opened_at,b.mac", (now,)).fetchall()


def visible_alerts(c, now, data_visible):
    out = []
    rows = c.execute("SELECT b.*,e.name AS employee_name FROM battery_alert_state b "
                     "JOIN employees e ON e.mac=b.mac WHERE b.active=1 ORDER BY b.battery,b.opened_at")
    for row in rows:
        if not data_visible(row["mac"], row["sample_at"], now):
            continue
        status = row["delivery_status"]
        if (status in ("awaiting_ack", "dispatching") and row["next_attempt_at"] <= now
                and row["confirmed_at"] is None):
            status = "unconfirmed"
        out.append({"mac": row["mac"], "employee_name": row["employee_name"],
                    "battery": row["battery"], "threshold": WARN_PERCENT,
                    "sample_at": row["sample_at"], "age_s": max(0, now - row["sample_at"]),
                    "opened_at": row["opened_at"], "vibration_status": status,
                    "attempts": row["attempts"], "confirmed_at": row["confirmed_at"],
                    "last_error": row["last_error"]})
    return out
