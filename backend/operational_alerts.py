"""Durable live health and installed-gateway operational alert episodes.

The bridge owns locking and commits.  This module only reads and mutates the
SQLite connection supplied by its caller; it performs no I/O beyond SQLite.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
import math
import uuid
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")

SCHEMA = """
CREATE TABLE IF NOT EXISTS operational_alerts(
  id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  source TEXT NOT NULL,
  type TEXT NOT NULL,
  severity TEXT NOT NULL,
  emp TEXT,
  mac TEXT,
  gw TEXT,
  dept TEXT,
  location TEXT NOT NULL,
  opened_at REAL NOT NULL,
  closed_at REAL,
  status TEXT NOT NULL,
  acknowledged_by TEXT,
  acknowledged_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS operational_alert_active_fingerprint
  ON operational_alerts(fingerprint) WHERE closed_at IS NULL;
CREATE INDEX IF NOT EXISTS operational_alert_history_idx
  ON operational_alerts(opened_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS operational_gateway_state(
  gw TEXT PRIMARY KEY,
  ever_seen INTEGER NOT NULL DEFAULT 0,
  last_seen REAL
);
"""


def ensure_schema(c):
    """Create the durable alert tables without committing the caller's work."""
    for statement in SCHEMA.split(";"):
        if statement.strip():
            c.execute(statement)


def note_gateway_seen(c, gw, now):
    """Remember a genuine online status receipt, independently of MQTT LWT."""
    c.execute(
        "INSERT INTO operational_gateway_state(gw,ever_seen,last_seen) VALUES(?,1,?) "
        "ON CONFLICT(gw) DO UPDATE SET ever_seen=1,last_seen=max(COALESCE(last_seen,0),excluded.last_seen)",
        (_text(gw), float(now)),
    )


def _text(value, default="") -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return default
    return str(value).strip()


def _positive_epoch(value):
    # bool is an int subclass but is not a useful observation timestamp.
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError):
        if not isinstance(value, str):
            return None
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
        except (OverflowError, OSError, ValueError):
            return None
    return result if math.isfinite(result) and result > 0 else None


def _location(value, fallback=None) -> str:
    """Reduce bridge location objects to the user-facing safe string."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("zone", "label", "name", "gw"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    candidate = _text(fallback)
    return candidate or "—"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(float(epoch), TEHRAN).isoformat(timespec="seconds")


def _health_records(employees):
    """Return one current record per eligible employee/issue fingerprint."""
    records = {}
    for employee in employees or ():
        if not isinstance(employee, dict):
            continue
        if employee.get("registered") is not True or employee.get("scan_allowed") is not True:
            continue
        mac = _text(employee.get("mac")).lower()
        if not mac:
            continue
        issues = employee.get("issues")
        if not isinstance(issues, (list, tuple, set)):
            continue
        status = _text(employee.get("status")).lower()
        if status not in ("warn", "danger"):
            continue
        severity = "danger" if status == "danger" else "warn"
        location = _location(employee.get("location"), employee.get("zone"))
        gateway = None
        if isinstance(employee.get("location"), dict):
            gateway = _text(employee["location"].get("gw")) or None
        for issue in issues:
            if not isinstance(issue, str) or not issue:
                continue
            # The issue code is intentionally retained for the UI's label map.
            fingerprint = f"health:{mac}:{issue}"
            records[fingerprint] = {
                "fingerprint": fingerprint,
                "type": issue,
                "severity": severity,
                "emp": _text(employee.get("name")) or mac,
                "mac": mac,
                "gw": gateway,
                "dept": _text(employee.get("dept")),
                "location": location,
            }
    return records


def _gateway_records(c, gateways):
    """Persist installed-gateway sightings and return current offline episodes.

    ``online`` is supplied by the bridge after applying its 180-second TTL;
    ``last_seen`` is an epoch value.  Registered rows with no positive sighting
    are not evidence that a gateway has ever been provisioned.
    """
    records = {}
    for gateway in gateways or ():
        if not isinstance(gateway, dict):
            continue
        if (gateway.get("registered") is not True
                or _text(gateway.get("kind")).lower() != "installed"):
            continue
        gw = _text(gateway.get("gw"))
        if not gw:
            continue
        last_seen = _positive_epoch(gateway.get("last_seen"))
        prior = c.execute(
            "SELECT ever_seen FROM operational_gateway_state WHERE gw=?", (gw,)
        ).fetchone()
        explicit_ever_seen = gateway.get("ever_seen") is True
        ever_seen = bool(prior and prior["ever_seen"]) or last_seen is not None or explicit_ever_seen
        c.execute(
            "INSERT INTO operational_gateway_state(gw,ever_seen,last_seen) VALUES(?,?,?) "
            "ON CONFLICT(gw) DO UPDATE SET ever_seen=max(ever_seen,excluded.ever_seen), "
            "last_seen=COALESCE(excluded.last_seen,operational_gateway_state.last_seen)",
            (gw, int(ever_seen), last_seen),
        )
        # A missing timestamp is the normal shape of a never-provisioned row.
        # It must never become an offline alert merely because it is registered.
        if gateway.get("online") is not False or not ever_seen:
            continue
        fingerprint = f"gateway:{gw}:offline"
        records[fingerprint] = {
            "fingerprint": fingerprint,
            "type": "gateway_offline",
            "severity": "warn",
            "emp": _text(gateway.get("label")) or gw,
            "mac": None,
            "gw": gw,
            "dept": "",
            "location": _location(gateway.get("zone"), gateway.get("label")),
        }
    return records


def _insert_or_update(c, fingerprint, record, now):
    row = c.execute(
        "SELECT * FROM operational_alerts "
        "WHERE fingerprint=? AND closed_at IS NULL", (fingerprint,)
    ).fetchone()
    if row is None:
        c.execute(
            "INSERT INTO operational_alerts("
            "id,fingerprint,source,type,severity,emp,mac,gw,dept,location,"
            "opened_at,status,acknowledged_by,acknowledged_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,'open',NULL,NULL)",
            (uuid.uuid4().hex, record["fingerprint"], "live", record["type"],
             record["severity"], record["emp"], record["mac"], record["gw"],
             record["dept"], record["location"], float(now)),
        )
        return
    # Identity and acknowledgement survive refreshes; display metadata follows
    # the latest real snapshot while the condition remains contiguous.
    c.execute(
        "UPDATE operational_alerts SET type=?,severity=?,emp=?,mac=?,gw=?,dept=?,location=? "
        "WHERE id=? AND closed_at IS NULL",
        (record["type"], record["severity"], record["emp"], record["mac"],
         record["gw"], record["dept"], record["location"], row["id"]),
    )


def sync(c, employees, gateways, now):
    """Reconcile current real conditions with durable alert episodes.

    Repeated snapshots do not create rows.  A condition that disappears closes
    its episode, so a later occurrence receives a fresh durable id.
    """
    current = _health_records(employees)
    current.update(_gateway_records(c, gateways))

    open_rows = c.execute(
        "SELECT id,fingerprint FROM operational_alerts WHERE closed_at IS NULL"
    ).fetchall()
    for row in open_rows:
        if row["fingerprint"] not in current:
            c.execute(
                "UPDATE operational_alerts SET status='closed',closed_at=? "
                "WHERE id=? AND closed_at IS NULL", (float(now), row["id"]),
            )
    for fingerprint, record in current.items():
        _insert_or_update(c, fingerprint, record, now)


def _row_to_alert(row) -> dict:
    return {
        "id": row["id"],
        "source": row["source"],
        "type": row["type"],
        "severity": row["severity"],
        "emp": row["emp"],
        "mac": row["mac"],
        "gw": row["gw"],
        "dept": row["dept"],
        "location": row["location"],
        "time": _iso(row["closed_at"] if row["status"] == "closed" else row["opened_at"]),
        "status": row["status"],
        "acknowledged_by": row["acknowledged_by"],
    }


def _tehran_day_bounds(now):
    local = datetime.fromtimestamp(float(now), TEHRAN)
    start = datetime.combine(local.date(), time.min, TEHRAN)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def view(c, now) -> dict:
    """Return active episodes and today's closed live history."""
    active = [
        _row_to_alert(row)
        for row in c.execute(
            "SELECT * FROM operational_alerts WHERE closed_at IS NULL "
            "ORDER BY opened_at DESC,id DESC"
        )
    ]
    start, end = _tehran_day_bounds(now)
    history = [
        _row_to_alert(row)
        for row in c.execute(
            "SELECT * FROM operational_alerts "
            "WHERE source='live' AND status='closed' AND closed_at>=? AND closed_at<? "
            "ORDER BY closed_at DESC,id DESC LIMIT 100", (start, end)
        )
    ]
    return {"alerts_active": active, "alerts_history": history}


def acknowledge(c, alert_id, actor, now):
    """Acknowledge an ongoing alert without closing or dispatching anything."""
    if not isinstance(alert_id, str) or not alert_id:
        return False, "invalid_alert_id"
    if not isinstance(actor, str) or not actor.strip():
        return False, "actor_required"
    row = c.execute(
        "SELECT status FROM operational_alerts WHERE id=?", (alert_id,)
    ).fetchone()
    if row is None:
        return False, "alert_not_found"
    if row["status"] == "closed":
        return False, "alert_closed"
    if row["status"] == "acknowledged":
        return True, ""
    c.execute(
        "UPDATE operational_alerts SET status='acknowledged',acknowledged_by=?,"
        "acknowledged_at=? WHERE id=? AND status='open'",
        (actor.strip(), float(now), alert_id),
    )
    return True, ""
