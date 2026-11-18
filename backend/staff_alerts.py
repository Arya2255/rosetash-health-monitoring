"""Durable alert episodes and correlated three-pulse delivery state."""
from __future__ import annotations

import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS staff_alert_episode(
  id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  source_mac TEXT NOT NULL,
  issue TEXT NOT NULL,
  source_group TEXT NOT NULL,
  company TEXT,
  dept TEXT,
  line TEXT,
  opened_at REAL NOT NULL,
  closed_at REAL);
CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_alert_active_fingerprint
  ON staff_alert_episode(fingerprint) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_staff_alert_opened
  ON staff_alert_episode(closed_at,opened_at);
CREATE TABLE IF NOT EXISTS staff_alert_delivery(
  episode_id TEXT NOT NULL,
  target_mac TEXT NOT NULL,
  target_group TEXT NOT NULL,
  emergency INTEGER NOT NULL DEFAULT 0,
  request_id TEXT NOT NULL UNIQUE,
  gateway TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_attempt_at REAL NOT NULL DEFAULT 0,
  first_attempt_at REAL,
  sent_at REAL,
  confirmed_at REAL,
  completed_pulses INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  PRIMARY KEY(episode_id,target_mac));
CREATE INDEX IF NOT EXISTS idx_staff_alert_delivery_pending
  ON staff_alert_delivery(status,next_attempt_at,gateway);
"""
MAX_ATTEMPTS = 3
RETRY_SECONDS = 120
RETRY_WINDOW_SECONDS = 480


def ensure_schema(connection):
    connection.executescript(SCHEMA)


def sync_episodes(connection, employees, now):
    """Open one episode per active registered band/issue and close recovered ones."""
    active = {}
    resolved_sources = set()
    for person in employees or []:
        if (isinstance(person, dict) and person.get("registered") is True
                and person.get("present") is True
                and (person.get("health") is not None or person.get("vitals") is not None)):
            resolved_sources.add(str(person.get("mac") or "").lower())
        if (not isinstance(person, dict) or person.get("registered") is not True
                or person.get("status") not in ("warn", "danger")):
            continue
        mac = str(person.get("mac") or "").lower()
        if not mac:
            continue
        for issue in person.get("issues") or ():
            if not isinstance(issue, str) or not issue or len(issue) > 64:
                continue
            company = str(person.get("company") or "").strip().casefold()
            dept = str(person.get("dept") or "").strip().casefold()
            line = str(person.get("line") or "").strip().casefold()
            group = str(person.get("staff_group") or "employee")
            fingerprint = f"health:{mac}:{issue}:{group}:{company}:{dept}:{line}"
            active[fingerprint] = (person, mac, issue)

    current = {row["fingerprint"]: row for row in connection.execute(
        "SELECT * FROM staff_alert_episode WHERE closed_at IS NULL")}
    for fingerprint, episode in current.items():
        if fingerprint not in active and episode["source_mac"] in resolved_sources:
            connection.execute("UPDATE staff_alert_episode SET closed_at=? WHERE id=? AND closed_at IS NULL",
                               (now, episode["id"]))
            connection.execute("UPDATE staff_alert_delivery SET status='closed',last_error='alert_closed' "
                               "WHERE episode_id=? AND status NOT IN ('confirmed','closed')",
                               (episode["id"],))

    for fingerprint, (person, mac, issue) in active.items():
        if fingerprint in current:
            continue
        episode_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO staff_alert_episode(id,fingerprint,source_mac,issue,source_group,company,dept,line,opened_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (episode_id, fingerprint, mac, issue, person.get("staff_group") or "employee",
             person.get("company"), person.get("dept"), person.get("line"), now))
    connection.commit()
    return {row["fingerprint"]: row for row in connection.execute(
        "SELECT * FROM staff_alert_episode WHERE closed_at IS NULL")}


def add_recipients(connection, episode, recipients, now):
    for recipient in recipients or ():
        if not isinstance(recipient, dict) or recipient.get("registered") is not True:
            continue
        mac = str(recipient.get("mac") or "").lower()
        group = recipient.get("staff_group")
        if not mac or group not in ("hse", "shift_leader", "supervisor"):
            continue
        connection.execute(
            "INSERT OR IGNORE INTO staff_alert_delivery(episode_id,target_mac,target_group,emergency,request_id,status,next_attempt_at) "
            "VALUES(?,?,?,?,?,'pending',?)",
            (episode["id"], mac, group, int(group == "hse"), "staff-" + uuid.uuid4().hex, now))
    connection.commit()


def record_result(connection, gateway, event, now):
    """Accept only an ACK for this target/gateway/request and all three pulses."""
    request_id = event.get("request_id")
    mac = str(event.get("mac") or "").lower()
    if event.get("reason") != "staff_alert" or not isinstance(request_id, str) or not mac:
        return False
    row = connection.execute(
        "SELECT d.*,e.opened_at,e.closed_at FROM staff_alert_delivery d "
        "JOIN staff_alert_episode e ON e.id=d.episode_id WHERE d.request_id=?",
        (request_id,)).fetchone()
    if (row is None or row["closed_at"] is not None or row["gateway"] != gateway
            or row["target_mac"] != mac or row["attempts"] == 0
            or now < row["opened_at"] or row["status"] in ("confirmed", "closed", "cancelled")):
        return False
    kind = event.get("type")
    if kind == "vibrated":
        pulses = event.get("completed_pulses")
        if type(pulses) is not int or pulses < 0 or pulses > 3:
            return False
        if pulses < 3:
            connection.execute(
                "UPDATE staff_alert_delivery SET completed_pulses=max(completed_pulses,?),"
                "status='awaiting_ack',last_error='partial_ack' WHERE request_id=?",
                (pulses, request_id))
            return False
        connection.execute(
            "UPDATE staff_alert_delivery SET status='confirmed',confirmed_at=?,completed_pulses=?,last_error=NULL "
            "WHERE request_id=?", (now, pulses, request_id))
    elif kind in ("vibrate_fail", "cmd_reject"):
        pulses = event.get("completed_pulses", 0)
        pulses = min(3, pulses) if type(pulses) is int and pulses >= 0 else 0
        connection.execute("UPDATE staff_alert_delivery SET status='failed',completed_pulses=max(completed_pulses,?),last_error=? WHERE request_id=?",
                           (pulses, str(event.get("detail") or kind)[:160], request_id))
    else:
        return False
    return True


def accepts_result(connection, gateway, event):
    """Allow an otherwise off-shift HSE only a correlated pending staff ACK."""
    request_id = event.get("request_id")
    mac = str(event.get("mac") or "").lower()
    return bool(event.get("reason") == "staff_alert" and isinstance(request_id, str) and mac
        and connection.execute(
            "SELECT 1 FROM staff_alert_delivery d JOIN staff_alert_episode e ON e.id=d.episode_id "
            "WHERE d.request_id=? AND d.target_mac=? AND d.gateway=? AND d.attempts>0 "
            "AND e.closed_at IS NULL AND d.status NOT IN ('confirmed','closed','cancelled')",
            (request_id, mac, gateway)).fetchone())
