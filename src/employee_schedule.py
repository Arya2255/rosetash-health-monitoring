"""Weekly employee scan schedules and explicit monitoring pauses."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
DAY_KEYS = ("sat", "sun", "mon", "tue", "wed", "thu", "fri")
DAY_LABELS = {
    "sat": "شنبه", "sun": "یکشنبه", "mon": "دوشنبه",
    "tue": "سه‌شنبه", "wed": "چهارشنبه", "thu": "پنجشنبه", "fri": "جمعه",
}
MAX_ACTIVE_MACS = 256  # Software policy capacity; not the radio whitelist limit
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_schedule(raw):
    """Return a validated weekly map; empty schedules intentionally mean off."""
    if not isinstance(raw, dict):
        if raw in (None, ""):
            return {}
        raise ValueError("schedule must be an object")
    if set(raw) - set(DAY_KEYS):
        raise ValueError("unknown weekday")

    normalized = {}
    for day in DAY_KEYS:
        entries = raw.get(day, [])
        if entries in (None, ""):
            entries = []
        if not isinstance(entries, list):
            raise ValueError("day schedule must be a list")
        ranges = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("invalid schedule entry")
            values = [str(entry.get(key) or "").strip().translate(_DIGITS)
                      for key in ("start", "end")]
            if any(re.fullmatch(r"[0-9]{2}:[0-9]{2}", value) is None for value in values):
                raise ValueError("time must use HH:MM")
            try:
                start, end = (time.fromisoformat(value) for value in values)
            except ValueError as exc:
                raise ValueError("time must use HH:MM") from exc
            if start == end:
                raise ValueError("start and end times must differ")
            ranges.append({"start": start.strftime("%H:%M"),
                           "end": end.strftime("%H:%M")})
        if ranges:
            ranges.sort(key=lambda item: item["start"])
            normalized[day] = ranges
    return normalized


def _as_tehran(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(TEHRAN)
    if now.tzinfo is None:
        return now.replace(tzinfo=TEHRAN)
    return now.astimezone(TEHRAN)


def _weekly_index(date) -> int:
    return (date.weekday() + 2) % 7  # Saturday = 0


def is_scheduled(schedule, now: datetime | None = None) -> bool:
    """Match Tehran local time, including overnight ranges from yesterday."""
    try:
        schedule = normalize_schedule(schedule)
    except (TypeError, ValueError):
        return False
    now = _as_tehran(now)
    today_index = _weekly_index(now.date())
    today = DAY_KEYS[today_index]
    previous = DAY_KEYS[(today_index - 1) % 7]
    current = now.timetz().replace(tzinfo=None)

    for entry in schedule.get(today, []):
        start, end = time.fromisoformat(entry["start"]), time.fromisoformat(entry["end"])
        if end > start and start <= current < end:
            return True
        if end < start and current >= start:
            return True
    for entry in schedule.get(previous, []):
        start, end = time.fromisoformat(entry["start"]), time.fromisoformat(entry["end"])
        if end < start and current < end:
            return True
    return False


def next_scheduled_start(schedule, now: datetime | None = None) -> datetime | None:
    """Return the next local Tehran start time for a configured weekly schedule."""
    try:
        schedule = normalize_schedule(schedule)
    except (TypeError, ValueError):
        return None
    now = _as_tehran(now)
    candidates = []
    for offset in range(8):
        date = now.date() + timedelta(days=offset)
        day = DAY_KEYS[_weekly_index(date)]
        for entry in schedule.get(day, []):
            candidate = datetime.combine(date, time.fromisoformat(entry["start"]), TEHRAN)
            if candidate > now:
                candidates.append(candidate)
    return min(candidates) if candidates else None


def next_schedule_transition(schedule, now: datetime | None = None) -> datetime | None:
    """Next effective on/off boundary, ignoring overlapping interval endpoints."""
    schedule = normalize_schedule(schedule)
    now = _as_tehran(now)
    boundaries = set()
    for offset in range(-1, 9):
        date = now.date() + timedelta(days=offset)
        for item in schedule.get(DAY_KEYS[_weekly_index(date)], []):
            start = datetime.combine(date, time.fromisoformat(item["start"]), TEHRAN)
            end = datetime.combine(date, time.fromisoformat(item["end"]), TEHRAN)
            if end <= start:
                end += timedelta(days=1)
            boundaries.update((start, end))
    for boundary in sorted(boundaries):
        if boundary > now and is_scheduled(schedule, boundary - timedelta(microseconds=1)) != is_scheduled(schedule, boundary):
            return boundary
    return None


def eligible_employee(emp: dict, now: datetime | None = None) -> bool:
    """Scheduled and not manually paused; missing schedules remain excluded."""
    if not isinstance(emp, dict) or emp.get("scan_paused"):
        return False
    return is_scheduled(emp.get("weekly_schedule"), now)


def active_employee_macs(employees: list[dict], now: datetime | None = None,
                         limit: int = MAX_ACTIVE_MACS) -> list[str]:
    """Return unique eligible MACs; reject rather than truncate an oversized policy."""
    result = []
    seen = set()
    for employee in employees:
        if not eligible_employee(employee, now):
            continue
        mac = str(employee.get("mac") or "").strip().lower().replace("-", ":")
        parts = mac.split(":")
        valid = (len(parts) == 6 and
                 all(len(part) == 2 and all(ch in "0123456789abcdef" for ch in part)
                     for part in parts))
        if valid and mac not in seen:
            result.append(mac)
            seen.add(mac)
    if len(result) > limit:
        raise ValueError(f"active employee bands exceed gateway policy capacity ({limit})")
    return result
