# -*- coding: utf-8 -*-
"""کلاینت پل زنده — تنها جایی که برنامه با بک‌اند محلی حرف می‌زند.

پل زنده در backend/bridge.py پیام‌های گیت‌وی را روی MQTT می‌گیرد و
به شکل JSON سرو می‌کند: http://127.0.0.1:8726/api/snapshot

دفتر کارکنان (نگاشت مک مچ‌بند ↔ کارکن) هم روی همین پل است:
GET/POST/DELETE /api/employees — توابع live_employees، save_employee
و delete_employee. دفتر مچ‌بندها (/api/bands — live_bands، save_band،
delete_band)، تعاریف پایه (/api/catalogs — live_catalogs، save_catalog،
delete_catalog) و عکس پرسنلی (/api/photo — photo_src) هم همین‌جا.

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

import applog


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
    "name required": "نام لازم است",
    "not found": "این مورد در دفتر نیست",
    "duplicate": "این مورد از قبل ثبت شده است",
    "invalid kind": "نوع تعریف نامعتبر است",
    "invalid parent": "شرکت والد نامعتبر است",
    "invalid age": "سن معتبر نیست — عددی بین ۱ تا ۱۲۰ وارد کن",
    "invalid id": "شناسهٔ تعریف نامعتبر است",
    "has children": "این شرکت زیرشرکت دارد — اول زیرشرکت‌ها را حذف کن",
    "assigned": "این مچ‌بند به یک کارکن تخصیص دارد — اول تخصیص کارکن را بردار",
    "photo too large": "عکس بزرگ‌تر از حد مجاز است — عکس کوچک‌تری انتخاب کن",
    "bad photo": "فرمت عکس پشتیبانی نمی‌شود — JPG یا PNG انتخاب کن",
    "photo save failed": "ذخیرهٔ عکس روی پل ناموفق بود",
    "body too large": "حجم درخواست بیش از حد مجاز است",
    "invalid gw": "شناسهٔ گیت‌وی معتبر نیست — حروف کوچک انگلیسی، عدد، نقطه و خط تیره؛ نمونه: gw-filter-2",
    "invalid position": "موقعیت باید بین ۰ و ۱ باشد",
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
    """ثبت/ویرایش کارکن در دفتر پل — کلید، مک مچ‌بند است.

    مهلت بلندتر است چون ممکن است عکس پرسنلی (base64) هم همراه باشد.
    """
    doc = dict(doc or {})
    doc["mac"] = str(doc.get("mac") or "").strip().lower()
    return _post_json("/api/employees", doc, timeout=10.0)


def _delete_json(path: str, key: str, value, fallback: str) -> tuple[bool, str]:
    """DELETE به پل — هرگز استثنا بیرون نمی‌دهد؛ خطای پل را فارسی برمی‌گرداند."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    url = (BRIDGE + path + "?" + key + "="
           + urllib.parse.quote(str(value or "").strip().lower()))
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False, "پل پاسخ نداد"
    if doc.get("ok"):
        _cache["t"] = 0.0
        return True, ""
    err = str(doc.get("error") or "")
    return False, _ERROR_FA.get(err, err or fallback)


def delete_employee(mac: str) -> tuple[bool, str]:
    """حذف کارکن از دفتر پل — مچ‌بندش اگر در دید باشد «ثبت‌نشده» می‌شود."""
    return _delete_json("/api/employees", "mac", mac, "حذف نشد")


# ─────────────── دفتر مچ‌بندها و تعاریف پایه — روی پل ───────────────


def live_bands(force: bool = False):
    """فهرست ادغام‌شدهٔ مچ‌بندهای شناخته‌شده از پل — None یعنی پل نیست.

    خروجی snapshot["bands_known"] است: دفتر مچ‌بندها + مچ‌بندهای در دید +
    مچ‌بندهای تخصیص‌داده‌شده به کارکنان، هر کدام با وضعیت دید و صاحبش.
    """
    doc = live_status(force=force)
    if not doc or not doc.get("ok"):
        return None
    return doc.get("bands_known") or []


def live_catalogs(force: bool = False):
    """تعاریف پایه (شرکت/واحد/خط/سمت) از پل — None یعنی پل نیست."""
    doc = live_status(force=force)
    if not doc or not doc.get("ok"):
        return None
    return doc.get("catalogs") or {}


def photo_src(emp) -> str | None:
    """نشانی کامل عکس پرسنلی کارکن برای ft.Image — None یعنی عکسی نیست."""
    photo = emp.get("photo") if isinstance(emp, dict) else None
    if not photo:
        return None
    return BRIDGE + str(photo)


def save_band(doc: dict) -> tuple[bool, str]:
    """ثبت/ویرایش مچ‌بند در دفتر پل — برچسب و یادداشت اختیاری است."""
    doc = dict(doc or {})
    doc["mac"] = str(doc.get("mac") or "").strip().lower()
    return _post_json("/api/bands", doc)


def delete_band(mac: str) -> tuple[bool, str]:
    """حذف مچ‌بند از دفتر پل — اگر به کارکنی تخصیص دارد، رد می‌شود."""
    return _delete_json("/api/bands", "mac", mac, "حذف نشد")


def save_catalog(doc: dict) -> tuple[bool, str]:
    """افزودن/ویرایش تعریف پایه (شرکت/واحد/خط/سمت) روی پل."""
    return _post_json("/api/catalogs", dict(doc or {}))


def delete_catalog(cid) -> tuple[bool, str]:
    """حذف یک تعریف پایه از پل — والدی که زیرمجموعه دارد رد می‌شود."""
    return _delete_json("/api/catalogs", "id", cid, "حذف نشد")


# ─────────────── دفتر گیت‌وی‌ها — تعریف و چیدمان روی نقشه ───────────────


def live_gateways(force: bool = False):
    """فهرست ادغام‌شدهٔ گیت‌وی‌های نقشه از پل — None یعنی پل در دسترس نیست.

    خروجی snapshot["map_gateways"] است: گیت‌وی‌های تعریف‌شده (با موقعیت
    نسبی روی نقشه) + گیت‌وی‌های کشف‌شدهٔ شبکه که هنوز تعریف نشده‌اند.
    """
    doc = live_status(force=force)
    if not doc or not doc.get("ok"):
        return None
    return doc.get("map_gateways") or []


def save_gateway(doc: dict) -> tuple[bool, str]:
    """ثبت/ویرایش گیت‌وی در دفتر پل — شناسهٔ خالی = ساخت خودکار (gw-۱…)."""
    doc = dict(doc or {})
    doc["gw"] = str(doc.get("gw") or "").strip().lower()
    return _post_json("/api/gateways", doc)


def delete_gateway(gw: str) -> tuple[bool, str]:
    """حذف گیت‌وی از دفتر پل — اگر دوباره در شبکه دیده شود، «تعریف‌نشده» می‌ماند."""
    return _delete_json("/api/gateways", "gw", str(gw or "").strip().lower(),
                        "حذف نشد")


def netinfo(include_pass: bool = False):
    """وای‌فای و آدرس پیشنهادی همین سیستم از پل — None یعنی پل در دسترس نیست.

    خروجی مثل {'ssid', 'mqtt_host', 'mqtt_port', 'candidates', ...}؛
    include_pass=True رمز وای‌فای هم می‌آید (برای صفحهٔ آماده‌سازی گیتوی —
    پل فقط روی 127.0.0.1 سرو می‌کند).
    """
    if MODE == "0":
        return None
    suffix = "?include_pass=1" if include_pass else ""
    try:
        with urllib.request.urlopen(BRIDGE + "/api/netinfo" + suffix,
                                    timeout=6.0) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        return doc if doc.get("ok") else None
    except Exception:
        return None
