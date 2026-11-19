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
import urllib.error

from bridge_auth import sign_request

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
# وضعیت آخرین اتصال به پل — برای ثبت گذار (خطا/بازگشت) در لاگ بدون اسپم
_bridge_state: dict = {"ok": None, "since": 0.0}


def _note_bridge(ok: bool, exc: Exception | None = None) -> None:
    """گذار وضعیت پل را در لاگ ثبت می‌کند — فقط لحظهٔ تغییر، نه هر بار."""
    prev = _bridge_state.get("ok")
    if ok:
        if prev is False:
            applog.info("پل دوباره در دسترس است — بازگشت به دادهٔ زنده")
        _bridge_state["ok"] = True
    elif prev is not False:
        applog.error("اتصال به پل برقرار نشد — %s — %s: %s", BRIDGE,
                     type(exc).__name__ if exc else "خطا",
                     exc if exc else "بدون جزئیات")
        _bridge_state["ok"] = False
    _bridge_state["since"] = time.time()


def _fetch(timeout: float = 0.9):
    try:
        with urllib.request.urlopen(BRIDGE + "/api/snapshot", timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        _note_bridge(True)
        return doc
    except Exception as exc:
        _note_bridge(False, exc)
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


def send_vibrate(mac: str | None = None, timeout: float = 2.5,
                 *, emergency: bool = False) -> tuple[bool, str]:
    """فرمان لرزاندن مچ‌بند را از راه پل به گیت‌وی می‌دهد.

    mac خالی باشد، پل خودش مچ‌بند شناخته‌شده را پیدا می‌کند. برمی‌گرداند
    (ok، پیام کوتاه برای نمایش)؛ هرگز استثنا بیرون نمی‌دهد.
    """
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    body = json.dumps({"action": "vibrate",
                       "mac": (mac or "").strip().lower(),
                       "emergency": bool(emergency)}).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE + "/api/command", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            with exc:
                doc = json.loads(exc.read(8192).decode("utf-8"))
        except Exception:
            doc = None
        error = doc.get("error") if isinstance(doc, dict) else None
        reason = _ERROR_FA.get(error) if isinstance(error, str) else None
        applog.warn("فرمان لرزش رد شد — HTTP %s — %s", exc.code, reason or "علت گزارش‌نشده")
        return False, reason or f"پل درخواست را رد کرد — HTTP {exc.code}"
    except Exception as exc:
        applog.error("فرمان لرزش نرسید — پل پاسخ نداد — %s: %s",
                     type(exc).__name__, exc)
        return False, "پل پاسخ نداد"
    if isinstance(doc, dict) and doc.get("ok") is True:
        applog.info("فرمان لرزش برای مچ‌بند %s فرستاده شد",
                    applog.mask_mac(mac))
        return True, "فرمان لرزش ارسال شد. لرزش مچ‌بند را بررسی کنید"
    applog.warn("پاسخ پل تأیید ارسال فرمان لرزش را نداشت")
    return False, "ارسال فرمان لرزش تأیید نشد"


def request_manual_measurement(mac: str, *, actor: str, timeout: float = 8.0):
    """Request a real measurement from the currently observing installed gateway."""
    if MODE == "0":
        return False, "حالت زنده خاموش است", None
    path = "/api/measurements"
    payload = {"mac": str(mac or "").strip().lower(), "actor": str(actor or "").strip().lower(),
               "vitals": False}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    try:
        headers.update(sign_request("POST", path, body, payload["actor"]))
        req = urllib.request.Request(BRIDGE + path, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            doc = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            doc = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return False, "پل درخواست اندازه‌گیری را رد کرد", None
    except Exception as exc:
        applog.error("manual measurement request failed — %s: %s", type(exc).__name__, exc)
        return False, "پل پاسخ نداد", None
    if not doc.get("ok"):
        error = str(doc.get("error") or "measurement request failed")
        translated = {
            "forbidden": "این حساب اجازهٔ اندازه‌گیری ندارد",
            "invalid mac": _ERROR_FA["invalid mac"],
            "not found": "کارکن در دفتر ثبت نشده است",
            "employee monitoring is paused or outside scheduled hours": "پایش این کارکن متوقف است یا اکنون خارج از شیفت است",
            "band unavailable": "مچ‌بند در بازهٔ اخیر در دید هیچ گیت‌وی نصب‌شده‌ای نبوده است",
            "gateway unavailable": "گیت‌وی‌ای که مچ‌بند را دیده اکنون آنلاین نیست",
            "gateway update required": "برای این قابلیت باید فریم‌ور جدید گیت‌وی نصب شود",
            "gateway policy unavailable": "مجوز پایش هنوز به گیت‌وی نرسیده است؛ چند ثانیه بعد دوباره تلاش کنید",
            "assigned gateway unavailable": "گیت‌وی مجازِ متصل به این مچ‌بند اکنون در دسترس نیست",
            "measurement already pending": "برای این مچ‌بند درخواست اندازه‌گیری در حال اجراست",
            "publish failed": "پل نتوانست فرمان را به بروکر بفرستد",
        }
        return False, translated.get(error, error), doc.get("info")
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    _cache["t"] = 0.0
    applog.info("manual measurement queued for band %s via %s",
                applog.mask_mac(payload["mac"]), info.get("gw", "unknown"))
    return True, "درخواست به گیت‌وی ارسال شد؛ نتیجه پس از اندازه‌گیری واقعی نمایش داده می‌شود", info


def send_measure(mac: str, *, actor: str):
    """Data-layer facade: return the request outcome without implying a sensor result."""
    ok, message, _info = request_manual_measurement(mac, actor=actor)
    return ok, message


# ─────────────────────── دفتر کارکنان — روی پل ───────────────────────

# ترجمهٔ خطاهای پل به پیام فارسی برای نمایش
_ERROR_FA = {
    "invalid mac": "مک مچ‌بند معتبر نیست — قالب درست: f3:b6:d6:b7:47:d7",
    "name required": "نام لازم است",
    "forbidden": "این حساب اجازهٔ تغییر پایش را ندارد",
    "unauthorized": "هویت درخواست پایش تأیید نشد؛ برنامه و پل را دوباره اجرا کنید",
    "invalid schedule": "ساعت‌های برنامهٔ هفتگی معتبر نیست",
    "invalid scan state": "وضعیت توقف پایش معتبر نیست",
    "invalid health interval": "فاصلهٔ پایش باید بین ۱ تا ۱۴۴۰ دقیقه باشد",
    "not found": "این مورد در دفتر نیست",
    "duplicate": "این مورد از قبل ثبت شده است",
    "invalid kind": "نوع تعریف نامعتبر است",
    "invalid parent": "شرکت والد نامعتبر است",
    "invalid age": "سن معتبر نیست — عددی بین ۱ تا ۱۲۰ وارد کن",
    "invalid staff group": "گروه کارکن معتبر نیست",
    "invalid id": "شناسهٔ تعریف نامعتبر است",
    "has children": "این شرکت زیرشرکت دارد — اول زیرشرکت‌ها را حذف کن",
    "assigned": "این مچ‌بند به یک کارکن تخصیص دارد — اول تخصیص کارکن را بردار",
    "photo too large": "عکس بزرگ‌تر از حد مجاز است — عکس کوچک‌تری انتخاب کن",
    "bad photo": "فرمت عکس پشتیبانی نمی‌شود — JPG یا PNG انتخاب کن",
    "photo save failed": "ذخیرهٔ عکس روی پل ناموفق بود",
    "body too large": "حجم درخواست بیش از حد مجاز است",
    "invalid gw": "شناسهٔ گیت‌وی معتبر نیست — حروف کوچک انگلیسی، عدد، نقطه و خط تیره؛ نمونه: gw-filter-2",
    "invalid position": "موقعیت باید بین ۰ و ۱ باشد",
    "invalid_alert_id": "شناسهٔ هشدار معتبر نیست",
    "alert_not_found": "این هشدار در پل پیدا نشد",
    "alert_closed": "این هشدار دیگر فعال نیست",
    "no gateway known yet": "هنوز پیام وضعیت گیت‌وی به پل نرسیده است",
    "employee monitoring is paused or outside scheduled hours": "پایش این کارکن متوقف است یا اکنون خارج از ساعت کاری است",
    "gateway scan capacity exceeded": "ظرفیت پایش گیت‌وی پر است",
    "emergency vibration is only for HSE": "لرزش اضطراری فقط برای مچ‌بند گروه ایمنی مجاز است",
    "diagnostic busy": "یک آزمون دیگر روی این گیت‌وی در حال اجراست",
    "publish failed": "فرمان آزمون به گیت‌وی ارسال نشد؛ اتصال پیام‌رسان را بررسی کنید",

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


def _post_json(path: str, payload: dict, timeout: float = 4.0, *, actor: str | None = None) -> tuple[bool, str]:
    """POST به پل — هرگز استثنا بیرون نمی‌دهد؛ خطای پل را فارسی برمی‌گرداند."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    try:
        if actor is not None:
            headers.update(sign_request("POST", path, body, actor))
        req = urllib.request.Request(BRIDGE + path, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            doc = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return False, "پل درخواست را رد کرد"
    except Exception as exc:
        applog.error("ارسال به پل ناموفق — %s — %s: %s", path,
                     type(exc).__name__, exc)
        return False, "پل پاسخ نداد"
    if doc.get("ok"):
        _cache["t"] = 0.0  # دفعهٔ بعد مستقیم از سرور خوانده شود
        applog.info("پل درخواست %s را پذیرفت", path)
        return True, ""
    err = str(doc.get("error") or "")
    applog.warn("پل درخواست %s را رد کرد — %s", path, err or "بدون پیام")
    return False, _ERROR_FA.get(err, err or "ثبت نشد")


def save_employee(doc: dict) -> tuple[bool, str]:
    """ثبت/ویرایش کارکن در دفتر پل — کلید، مک مچ‌بند است.

    مهلت بلندتر است چون ممکن است عکس پرسنلی (base64) هم همراه باشد.
    """
    doc = dict(doc or {})
    doc["mac"] = str(doc.get("mac") or "").strip().lower()
    return _post_json("/api/employees", doc, timeout=10.0)


def acknowledge_alert(alert_id: str, *, actor: str) -> tuple[bool, str]:
    """Record acknowledgement on the bridge without closing the alert."""
    actor = str(actor or "").strip().lower()
    return _post_json("/api/alerts/ack", {"id": alert_id, "actor": actor}, actor=actor)


def save_employee_monitoring(doc: dict) -> tuple[bool, str]:
    doc = dict(doc or {})
    return _post_json("/api/monitoring", doc, actor=str(doc.get("actor") or ""))


def monitoring_settings():
    if MODE == "0":
        return None
    try:
        with urllib.request.urlopen(BRIDGE + "/api/monitoring/settings", timeout=2) as response:
            doc = json.loads(response.read().decode("utf-8"))
        return doc if doc.get("ok") else None
    except Exception:
        return None


def save_monitoring_settings(doc: dict) -> tuple[bool, str]:
    doc = dict(doc or {})
    return _post_json("/api/monitoring/settings", doc, actor=str(doc.get("actor") or ""))


def _delete_json(path: str, key: str, value, fallback: str, *, actor=None) -> tuple[bool, str]:
    """DELETE به پل — هرگز استثنا بیرون نمی‌دهد؛ خطای پل را فارسی برمی‌گرداند."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    url = (BRIDGE + path + "?" + key + "="
           + urllib.parse.quote(str(value or "").strip().lower()))
    try:
        target = urllib.parse.urlsplit(url)
        headers = sign_request("DELETE", target.path + "?" + target.query, b"", actor) if actor is not None else {}
        req = urllib.request.Request(url, method="DELETE", headers=headers)
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            doc = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return False, "پل درخواست حذف را رد کرد"
    except Exception as exc:
        applog.error("حذف از پل ناموفق — %s — %s: %s", path,
                     type(exc).__name__, exc)
        return False, "پل پاسخ نداد"
    if doc.get("ok"):
        _cache["t"] = 0.0
        applog.info("حذف روی پل انجام شد — %s", path)
        return True, ""
    err = str(doc.get("error") or "")
    applog.warn("پل حذف %s را رد کرد — %s", path, err or "بدون پیام")
    return False, _ERROR_FA.get(err, err or fallback)


def delete_employee(mac: str, *, actor="") -> tuple[bool, str]:
    """Remove an employee as the authenticated admin and release its band."""
    return _delete_json("/api/employees", "mac", mac, "حذف نشد", actor=actor)


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


def scan_local_ble(*, actor: str) -> tuple[bool, list[dict] | str]:
    """Ask the authenticated bridge to use the HSE host's own BLE radio."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    path = "/api/bands/scan"
    try:
        headers = sign_request("GET", path, b"", actor)
        request = urllib.request.Request(BRIDGE + path, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            doc = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            doc = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            return False, "پل درخواست جست‌وجو را رد کرد"
    except Exception:
        return False, "پل محلی پاسخ نداد؛ اتصال برنامه و دانگل را بررسی کنید"
    if doc.get("ok"):
        return True, doc.get("devices") or []
    error = str(doc.get("error") or "جست‌وجوی بلوتوث کامل نشد")
    if error == "forbidden":
        return False, "جست‌وجوی بلوتوث فقط برای ادمین اصلی مجاز است"
    return False, _ERROR_FA.get(error, error)


def photo_src(emp) -> str | None:
    """نشانی کامل عکس پرسنلی کارکن برای ft.Image — None یعنی عکسی نیست."""
    photo = emp.get("photo") if isinstance(emp, dict) else None
    if not photo:
        return None
    if not str(photo).startswith("/api/photo/"):
        return None
    # Fetch on the app host: a remote browser's localhost is another computer.
    try:
        import base64
        with urllib.request.urlopen(BRIDGE + str(photo), timeout=3) as response:
            mime = response.headers.get("Content-Type", "").split(";")[0]
            blob = response.read(1_600_001)
        if mime not in ("image/png", "image/jpeg", "image/webp") or len(blob) > 1_600_000:
            return None
        return "data:" + mime + ";base64," + base64.b64encode(blob).decode("ascii")
    except Exception:
        return None


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


def discover_gateways(*, actor: str) -> tuple[bool, list[dict] | str]:
    """Ask the bridge host to send the gateway discovery query on its LAN."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    path = "/api/gateways/discover"
    actor = str(actor or "").strip().lower()
    body = json.dumps({"actor": actor}).encode("utf-8")
    try:
        headers = {"Content-Type": "application/json", **sign_request("POST", path, body, actor)}
        req = urllib.request.Request(BRIDGE + path, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12.0) as response:
            doc = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            with exc:
                doc = json.load(exc)
        except (ValueError, OSError):
            return False, "پل درخواست جستجوی شبکه را رد کرد"
    except (OSError, ValueError) as exc:
        applog.error("Gateway discovery request failed: %s", type(exc).__name__)
        return False, "پل به درخواست جستجوی شبکه پاسخ نداد"
    if not isinstance(doc, dict):
        return False, "پاسخ پل برای جستجوی شبکه معتبر نیست"
    if doc.get("ok") is True and isinstance(doc.get("gateways"), list):
        _cache["t"] = 0.0
        return True, doc["gateways"]
    error = doc.get("error")
    if error == "forbidden":
        return False, "جستجوی شبکه فقط برای ادمین اصلی مجاز است"
    if error == "unauthorized":
        return False, _ERROR_FA["unauthorized"]
    return False, "جستجوی شبکه ناموفق بود؛ اتصال شبکهٔ محلی را بررسی کنید"


def gateway_diagnostic(*, actor: str, action: str, gw: str = "", mac: str = "",
                       request_id: str = "") -> tuple[bool, dict | str]:
    """Start or poll an owner-only gateway BLE diagnostic over the signed bridge API."""
    if MODE == "0":
        return False, "حالت زنده خاموش است"
    path = "/api/gateways/diagnostics"
    actor = str(actor or "").strip().lower()
    payload = {"actor": actor, "action": str(action or "").strip()}
    if gw:
        payload["gw"] = str(gw).strip().lower()
    if mac:
        payload["mac"] = str(mac).strip().lower()
    if request_id:
        payload["request_id"] = str(request_id).strip()
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    try:
        headers = {"Content-Type": "application/json", **sign_request("POST", path, body, actor)}
        request = urllib.request.Request(BRIDGE + path, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=8.0) as response:
            doc = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            with exc:
                doc = json.load(exc)
        except (ValueError, OSError):
            return False, "پل درخواست آزمون را رد کرد"
    except (OSError, ValueError):
        return False, "پل برای آزمون گیت‌وی پاسخ نداد"
    if not isinstance(doc, dict):
        return False, "پاسخ پل برای آزمون گیت‌وی معتبر نیست"
    if doc.get("ok") is True and isinstance(doc.get("info"), dict):
        return True, doc["info"]
    error = doc.get("error")
    if error == "forbidden":
        return False, "آزمون مستقیم گیت‌وی فقط برای ادمین اصلی مجاز است"
    if error == "unauthorized":
        return False, _ERROR_FA["unauthorized"]
    if error == "invalid gw":
        return False, _ERROR_FA["invalid gw"]
    if error == "invalid mac":
        return False, _ERROR_FA["invalid mac"]
    if error == "not found":
        return False, "این درخواست آزمون پیدا نشد"
    return False, _ERROR_FA.get(error if isinstance(error, str) else "", "آزمون گیت‌وی پذیرفته نشد")


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
