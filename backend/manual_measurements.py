"""Durable state for operator-requested measurements; not a sensor simulator."""
import math

SCHEMA = """
CREATE TABLE IF NOT EXISTS manual_measurements(
 request_id TEXT PRIMARY KEY, mac TEXT NOT NULL, gateway TEXT NOT NULL,
 actor TEXT NOT NULL, requested_at REAL NOT NULL, expires_at REAL NOT NULL,
 status TEXT NOT NULL, detail TEXT, updated_at REAL NOT NULL, bpm REAL);
CREATE INDEX IF NOT EXISTS idx_manual_measurement_mac ON manual_measurements(mac,requested_at);
"""
_ACTIVE = ("pending", "queued", "started")
_EVENT_STATES = {"measure_queued": "queued", "measure_started": "started",
                 "measure_fail": "failed", "measure_reject": "rejected"}


def ensure_schema(connection):
    connection.executescript(SCHEMA)
    if "bpm" not in {row[1] for row in connection.execute("PRAGMA table_info(manual_measurements)")}:
        connection.execute("ALTER TABLE manual_measurements ADD COLUMN bpm REAL")


def expire(connection, now):
    connection.execute("UPDATE manual_measurements SET status='timeout',detail='measurement timeout',updated_at=? "
                       "WHERE status IN ('pending','queued','started') AND expires_at<=?", (now, now))


def matching_request(connection, gateway, doc, now):
    request_id = doc.get("request_id")
    if not isinstance(request_id, str) or doc.get("replayed") is True:
        return None
    return connection.execute(
        "SELECT * FROM manual_measurements WHERE request_id=? AND gateway=? AND mac=? "
        "AND requested_at<=? AND expires_at>?", (request_id, gateway, doc.get("mac"), now, now)
    ).fetchone()


def record_result(connection, gateway, event, now):
    kind = event.get("type")
    if (event.get("reason") != "manual_measure" or not isinstance(kind, str)
            or kind not in _EVENT_STATES):
        return False
    row = matching_request(connection, gateway, event, now)
    if row is None or row["status"] not in _ACTIVE:
        return False
    # Late queue/start packets cannot move a running measurement backwards.
    status = _EVENT_STATES[kind]
    if row["status"] == "started" and status == "queued":
        return False
    connection.execute("UPDATE manual_measurements SET status=?,detail=?,updated_at=? WHERE request_id=?",
                       (status, str(event.get("detail") or "")[:160], now, row["request_id"]))
    return True


def record_health(connection, gateway, doc, now):
    """A live, correlated sample completes the request; a status event alone cannot."""
    count, samples, average = doc.get("n"), doc.get("bpm"), doc.get("avg")
    if (doc.get("state") != "done" or type(count) is not int or not 1 <= count <= 255
            or not isinstance(samples, list) or len(samples) != count
            or not all(type(value) is int and 30 <= value <= 240 for value in samples)
            or type(average) not in (int, float) or not 30 <= average <= 240
            or not math.isclose(average, sum(samples) / count, abs_tol=.001)):
        return False
    row = matching_request(connection, gateway, doc, now)
    if row is None or row["status"] not in _ACTIVE:
        return False
    connection.execute("UPDATE manual_measurements SET status='done',detail='',bpm=?,updated_at=? "
                       "WHERE request_id=?", (average, now, row["request_id"]))
    return True


def latest_by_mac(connection, now):
    """Expose the latest result per band without operator identity."""
    return {row["mac"]: dict(row) for row in connection.execute(
        "SELECT request_id,mac,gateway,status,detail,requested_at,updated_at,bpm FROM ("
        "SELECT *,ROW_NUMBER() OVER(PARTITION BY mac ORDER BY requested_at DESC,rowid DESC) AS position "
        "FROM manual_measurements WHERE requested_at BETWEEN ? AND ?) WHERE position=1",
        (now - 86400, now))}
