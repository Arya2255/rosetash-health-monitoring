# -*- coding: utf-8 -*-
"""کلاینت پل زنده — تنها جایی که برنامه با بک‌اند محلی حرف می‌زند.

پل زنده در backend/bridge.py پیام‌های گیت‌وی را روی MQTT می‌گیرد و
به شکل JSON سرو می‌کند: http://127.0.0.1:8726/api/snapshot

دفتر کارکنان (نگاشت مک مچ‌بند ↔ کارکن) هم روی همین پل است:
GET/POST/DELETE /api/employees — توابع live_employees، save_employee
و delete_employee.

قواعد:
  - فقط کتابخانهٔ استاندارد پایتون
  - هرگز استثنا به بیرون نمی‌دهد؛ اگر پل نبود None برمی‌گرداند
  - نتیجه چند ثانیه کش می‌شود تا رابط کاربری سرور را اذیت نکند
  - متغیرهای محیطی (هر دو املای ROZTASH_* و ROSETASH_* پذیرفته می‌شود):
      ROZTASH_LIVE=0   خاموش کردن حالت زنده
      ROZTASH_BRIDGE   آدرس پل، پیش‌فرض http://127.0.0.1:8726
      ROZTASH_LIVE_TTL عمر کش به ثانیه، پیش‌فرض ۴
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request


def _env(*names, default: str = "") -> str:
    """نخستین متغیر محیطی موجود — پذیرش هر دو املای ROZTASH/ROSETASH."""
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v
    return default


BRIDGE = _env("ROZTASH_BRIDGE", "ROSETASH_BRIDGE",
              default="http://127.0.0.1:8726")
MODE = _env("ROZTASH_LIVE", "ROSETASH_LIVE", default="auto")
CACHE_TTL = float(_env("ROZTASH_LIVE_TTL", "ROSETASH_LIVE_TTL", default="4"))

_cache: dict = {"t": 0.0, "doc": None}
_cached_once = False


def _fetch(timeout: float = 0.9):
    try:
        with urllib.request.urlopen(BRIDGE + "/api/snapshot", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def live_status(force: bool = False):
    """تصویر زندهٔ گیت‌وی یا None اگر پل در دسترس نباشد.

    ساختار {'gateways': [...], 'bands': [...], 'health': [...], ...}
    """
    global _cached_once
    if MODE == "0":
        return None
    now = time.time()
    if not force and _cached_once and (now - _cache["t"]) < CACHE_TTL:
        return _cache["doc"]
    doc = _fetch()
    _cache["t"] = now
    _cache["doc"] = doc
    _cached_once = True
    return doc


def live_available() -> bool:
    """آیا پل زنده پاسخ می‌دهد؟"""
    doc = live_status()
    return bool(doc and doc.get("ok"))


def live_summary():
    """خلاصهٔ کوچک برای نمایش: گیت‌وی، حضور مچ‌بند، آخرین ضربان و حیاتی‌ها."""
    doc = live_status()
    if not doc or not doc.get("ok"):
        return None
    gateways = doc.get("gateways") or []
    gateway = gateways[0] if gateways else None
    bands = doc.get("bands") or []
    band = bands[0] if bands else None
    health = (doc.get("health") or [None])[0]
    vitals = (doc.get("vitals") or [None])[0]
    return {
        "available": True,
        "fetched_at": doc.get("fetched_at"),
        "gateway": gateway,
        "band": band,
        "health": health,
        "vitals": vitals,
        "gateways_count": len(gateways),
        "gateways_online": sum(1 for g in gateways if g.get("online")),
        "bands_count": len(bands),
    }


def send_vibrate(mac: str | None = None, timeout: float = 2.5) -> tuple[bool, str]:
    """فرمان لرزاندن مچ‌بند را از راه پل به گیت‌وی می‌دهد.

    mac خالی باشد، پل خودش مچ‌بند شناخته‌شده را پیدا می‌کند. برمی‌گرداند
    (ok، پیام کوتاه برای نمایش)؛ هرگز استثنا بیرون نمی‌دهد.
    """
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    body = json.dumps({"action": "vibrate",
                       "mac": (mac or "").strip().lower()}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE + "/api/command", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False, "پل پاسخ نداد"
    if doc.get("ok"):
        return True, "فرمان لرزاندن رفت — اگر روی دست باشد می‌لرزد"
    return False, str(doc.get("error") or "فرمان نرسید")


# ─────────────────────── دفتر کارکنان — روی پل ───────────────────────

# ترجمهٔ خطاهای پل به پیام فارسی برای نمایش
_ERROR_FA = {
    "invalid mac": "مک مچ‌بند معتبر نیست — قالب درست: f3:b6:d6:b7:47:d7",
    "name required": "نام کارکن لازم است",
    "not found": "این کارکن در دفتر نیست",
}


def live_employees(force: bool = False):
    """فهرست ادغام‌شدهٔ کارکنان از پل — None یعنی پل در دسترس نیست.

    خروجی snapshot["employees"] است: هر کارکن ثبت‌شده + هر مچ‌بند
    ثبت‌نشدهٔ در دید، با وضعیت و حیاتی‌های واقعی.
    """
    doc = live_status(force=force)
    if not doc or not doc.get("ok"):
        return None
    return doc.get("employees") or []


def _post_json(path: str, payload: dict, timeout: float = 4.0) -> tuple[bool, str]:
    """POST به پل — هرگز استثنا بیرون نمی‌دهد؛ خطای پل را فارسی برمی‌گرداند."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    req = urllib.request.Request(
        BRIDGE + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False, "پل پاسخ نداد"
    if doc.get("ok"):
        _cache["t"] = 0.0  # دفعهٔ بعد مستقیم از سرور خوانده شود
        return True, ""
    err = str(doc.get("error") or "")
    return False, _ERROR_FA.get(err, err or "ثبت نشد")


def save_employee(doc: dict) -> tuple[bool, str]:
    """ثبت/ویرایش کارکن در دفتر پل — کلید، مک مچ‌بند است."""
    doc = dict(doc or {})
    doc["mac"] = str(doc.get("mac") or "").strip().lower()
    return _post_json("/api/employees", doc)


def delete_employee(mac: str) -> tuple[bool, str]:
    """حذف کارکن از دفتر پل — مچ‌بندش اگر در دید باشد «ثبت‌نشده» می‌شود."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    req = urllib.request.Request(
        BRIDGE + "/api/employees?mac=" + urllib.parse.quote(str(mac or "").strip().lower()),
        method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False, "پل پاسخ نداد"
    if doc.get("ok"):
        _cache["t"] = 0.0
        return True, ""
    err = str(doc.get("error") or "")
    return False, _ERROR_FA.get(err, err or "حذف نشد")
