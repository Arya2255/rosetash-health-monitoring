"""Bounded gateway diagnostic requests, separate from monitoring data."""
from __future__ import annotations

import json
import re
import uuid

_REQUEST_ID = re.compile(r"\Adiag-[0-9a-f]{32}\Z")
_GW = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,22}\Z")
_MAC = re.compile(r"\A(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\Z")
_DETAIL = re.compile(r"\A[a-z0-9_.-]{1,80}\Z")
_TTL_S = 20


def ensure_schema(connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS gateway_diagnostics(
          request_id TEXT PRIMARY KEY, gw TEXT NOT NULL, action TEXT NOT NULL,
          mac TEXT, actor TEXT NOT NULL, status TEXT NOT NULL,
          devices TEXT NOT NULL DEFAULT '[]', connected INTEGER,
          battery INTEGER, detail TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL, expires_at REAL NOT NULL, updated_at REAL NOT NULL)
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_gateway_diagnostics_active "
        "ON gateway_diagnostics(gw,status,expires_at)")


def _row(row) -> dict:
    return {
        "request_id": row["request_id"], "gw": row["gw"], "action": row["action"],
        "mac": row["mac"], "status": row["status"],
        "devices": json.loads(row["devices"] or "[]"),
        "connected": None if row["connected"] is None else bool(row["connected"]),
        "battery": row["battery"], "detail": row["detail"],
    }


def expire(connection, now: float) -> None:
    connection.execute(
        "UPDATE gateway_diagnostics SET status='timeout',detail='response_timeout',updated_at=? "
        "WHERE status='pending' AND expires_at<=?", (now, now))


def create(connection, *, actor: str, action: str, gw: str, mac: str | None, now: float):
    action = str(action or "").strip()
    gw = str(gw or "").strip().lower()
    mac = str(mac or "").strip().lower()
    if action not in ("scan", "probe"):
        return False, "unknown action", {}, None
    if not _GW.fullmatch(gw):
        return False, "invalid gw", {}, None
    if action == "probe" and not _MAC.fullmatch(mac):
        return False, "invalid mac", {}, None
    if action == "scan":
        mac = None
    expire(connection, now)
    active = connection.execute(
        "SELECT request_id FROM gateway_diagnostics WHERE gw=? AND status='pending' LIMIT 1",
        (gw,)).fetchone()
    if active:
        return False, "diagnostic busy", {"request_id": active["request_id"]}, None
    connection.execute("DELETE FROM gateway_diagnostics WHERE created_at<?", (now - 86400,))
    request_id = "diag-" + uuid.uuid4().hex
    connection.execute(
        "INSERT INTO gateway_diagnostics(request_id,gw,action,mac,actor,status,created_at,expires_at,updated_at) "
        "VALUES(?,?,?,?,?,'pending',?,?,?)",
        (request_id, gw, action, mac, actor, now, now + _TTL_S, now))
    connection.commit()
    command = {"action": "diagnostic_" + action, "request_id": request_id, "ttl_s": _TTL_S}
    if mac:
        command["mac"] = mac
    doc = _row(connection.execute(
        "SELECT * FROM gateway_diagnostics WHERE request_id=?", (request_id,)).fetchone())
    return True, "", doc, command


def publish_failed(connection, request_id: str, now: float) -> dict:
    connection.execute(
        "UPDATE gateway_diagnostics SET status='failed',detail='publish_failed',updated_at=? "
        "WHERE request_id=? AND status='pending'", (now, request_id))
    connection.commit()
    return _row(connection.execute(
        "SELECT * FROM gateway_diagnostics WHERE request_id=?", (request_id,)).fetchone())


def status(connection, request_id: str, now: float):
    expire(connection, now)
    connection.commit()
    row = connection.execute(
        "SELECT * FROM gateway_diagnostics WHERE request_id=?", (str(request_id or ""),)).fetchone()
    if row is None:
        return False, "not found", {}
    return True, "", _row(row)


def _devices(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    unique = {}
    for item in value[:64]:
        if not isinstance(item, dict):
            continue
        mac = str(item.get("mac") or "").lower()
        rssi = item.get("rssi")
        if not _MAC.fullmatch(mac) or type(rssi) is not int or not -127 <= rssi <= 0:
            continue
        old = unique.get(mac)
        if old is None or rssi > old["rssi"]:
            unique[mac] = {"mac": mac, "rssi": rssi}
    return sorted(unique.values(), key=lambda item: (-item["rssi"], item["mac"]))


def record_result(connection, gw: str, doc: dict, now: float) -> bool:
    """Accept only a fresh, matching result for a pending request."""
    if not isinstance(doc, dict) or doc.get("replayed") is True:
        return False
    request_id = doc.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        return False
    row = connection.execute(
        "SELECT * FROM gateway_diagnostics WHERE request_id=? AND gw=? AND status='pending'",
        (request_id, gw)).fetchone()
    if row is None or now >= row["expires_at"]:
        return False
    kind = doc.get("type")
    expected = row["action"]
    if kind == expected + "_done":
        if expected == "scan":
            devices = _devices(doc.get("devices"))
            connection.execute(
                "UPDATE gateway_diagnostics SET status='done',devices=?,detail='',updated_at=? "
                "WHERE request_id=? AND status='pending'",
                (json.dumps(devices, separators=(",", ":")), now, request_id))
        else:
            mac = str(doc.get("mac") or "").lower()
            connected = doc.get("connected")
            battery = doc.get("battery")
            if mac != row["mac"] or type(connected) is not bool:
                return False
            if battery is not None and (type(battery) is not int or not 0 <= battery <= 100):
                return False
            connection.execute(
                "UPDATE gateway_diagnostics SET status=?,connected=?,battery=?,detail=?,updated_at=? "
                "WHERE request_id=? AND status='pending'",
                ("done" if connected else "failed", int(connected), battery,
                 "" if connected else "connect_failed", now, request_id))
    elif kind == expected + "_reject":
        detail = doc.get("detail")
        detail = detail if isinstance(detail, str) and _DETAIL.fullmatch(detail) else "request_rejected"
        if expected == "probe" and doc.get("connected") is False:
            if str(doc.get("mac") or "").lower() != row["mac"]:
                return False
            connection.execute(
                "UPDATE gateway_diagnostics SET status='failed',connected=0,battery=NULL,"
                "detail='connect_failed',updated_at=? WHERE request_id=? AND status='pending'",
                (now, request_id))
        else:
            connection.execute(
                "UPDATE gateway_diagnostics SET status='rejected',detail=?,updated_at=? "
                "WHERE request_id=? AND status='pending'", (detail, now, request_id))
    else:
        return False
    connection.commit()
    return True
