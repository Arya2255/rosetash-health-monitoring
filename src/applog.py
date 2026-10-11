# -*- coding: utf-8 -*-
"""لاگ فایل‌محور برنامه — برای عیب‌یابی روی سیستم HSE.

هر اجرای برنامه یک فایل سشن می‌سازد، در پوشهٔ `logs` کنار برنامه:

    logs/app-YYYYMMDD-HHMMSS.log

قواعد فایل:
  - مهر زمانی کامل (دقیقه تا ثانیه) + سطح (info/warn/error) در هر سطر
  - چرخش حجمی: هر فایل بیش از MAX_BYTES که شد، به نسخهٔ پشتیبان می‌چرخد
  - نگهداری: فقط MAX_SESSIONS سشن آخر می‌ماند؛ قدیمی‌ترها پاک می‌شوند
  - خروجی زیپ پشتیبانی: چند سشن اخیر + فایل توضیح session-info.txt

حریم خصوصی: هیچ مقدار خام سلامت (ضربان، اکسیژن و…) در لاگ نوشته
نمی‌شود. شناسهٔ مچ‌بند در صورت نیاز با mask_mac کوتاه می‌شود و فقط
بازهٔ اول و آخر مک باقی می‌ماند.

قواعد مثل live.py: فقط کتابخانهٔ استاندارد، هرگز استثنا بیرون نمی‌دهد —
لاگ نباید خودش برنامه را زمین بزند. متغیرهای محیطی (هر دو املای
ROZTASH_* و ROSETASH_* پذیرفته می‌شود):
    ROZTASH_LOG_DIR   مسیر پوشهٔ لاگ (پیش‌فرض: logs کنار برنامه)
    ROZTASH_LOG=0     خاموش کردن کامل لاگ فایلی
"""
from __future__ import annotations

import glob
import logging
import logging.handlers
import os
import platform
import re
import socket
import sys
import threading
import zipfile
from datetime import datetime

APP_NAME = "rosetash-health-monitoring"
VERSION_FALLBACK = "0.1.0"

LOG_PREFIX = "app-"
MAX_BYTES = 256 * 1024      # سقف حجم هر فایل سشن
BACKUPS = 2                 # نسخه‌های پشتیبان چرخش داخل هر سشن
MAX_SESSIONS = 12           # تنها این تعداد سشن اخیر نگه داشته می‌شود
EXPORT_SESSIONS = 5         # zip پشتیبانی از چند سشن اخیر

_LOGGER_NAME = "roztash"
_LOCK = threading.RLock()
_SESSION = {"path": None, "logger": None, "disabled": False, "hooks": False}

_HEADER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+)\s* \| (\S+) \| (.*)$")
_RANK = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def _env(*names, default: str = "") -> str:
    """نخستین متغیر محیطی موجود — مثل live.py هر دو املا پذیرفته است."""
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v
    return default


def log_dir() -> str:
    """پوشهٔ لاگ — کنار برنامه؛ با ROZTASH_LOG_DIR قابل تغییر."""
    custom = _env("ROZTASH_LOG_DIR", "ROSETASH_LOG_DIR")
    if custom:
        return os.path.abspath(os.path.expanduser(custom))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "logs")


def app_version() -> str:
    """نسخهٔ برنامه از بستهٔ نصب‌شده — با عقب‌نشینی امن."""
    try:
        from importlib.metadata import version
        return str(version(APP_NAME))
    except Exception:
        return VERSION_FALLBACK


def _disabled() -> bool:
    return _env("ROZTASH_LOG", "ROSETASH_LOG", default="1") == "0"


def _norm_level(level) -> str:
    """یکسان‌سازی نام سطح — WARN یعنی WARNING."""
    name = str(level or "").upper()
    return "WARNING" if name == "WARN" else name


def mask_mac(mac) -> str:
    """ماسک شناسهٔ مچ‌بند — فقط دو اکتت اول و دو اکتت آخر می‌ماند.

    نمونه: 88:57:21:B8:AC:29 → 88:57:**:**:AC:29
    """
    s = str(mac or "").strip()
    parts = s.split(":")
    if len(parts) == 6 and all(parts):
        return ":".join([parts[0], parts[1], "**", "**", parts[4], parts[5]])
    return (s[:4] + "…") if len(s) > 5 else s


def _is_backup(path: str) -> bool:
    return bool(re.search(r"\.\d+$", path))


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def session_files(directory=None):
    """فایل‌های سشن (و چرخش‌هایشان) — تازه‌ترین اول."""
    d = os.path.abspath(directory) if directory else log_dir()
    try:
        files = glob.glob(os.path.join(d, LOG_PREFIX + "*.log*"))
    except OSError:
        return []
    files = [p for p in files if os.path.isfile(p)]
    files.sort(key=_mtime, reverse=True)
    return files


def _purge_old(directory: str, keep: int = MAX_SESSIONS) -> None:
    """سشن‌های قدیمی‌تر از سقف نگهداری را بی‌سروصدا پاک می‌کند."""
    mains = [p for p in session_files(directory) if not _is_backup(p)]
    for old in mains[max(1, keep):]:
        for p in [old] + glob.glob(old + ".*"):
            try:
                os.remove(p)
            except OSError:
                pass


def _make_logger(path: str) -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUPS,
        encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(module)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    return logger


def setup(directory=None, force: bool = False):
    """شروع سشن لاگ — یک فایل برای هر اجرای برنامه.

    برمی‌گرداند مسیر فایل سشن یا None (اگر لاگ خاموش/ناموفق باشد).
    """
    with _LOCK:
        if _SESSION["path"] and not force:
            return _SESSION["path"]
        if _disabled():
            _SESSION.update({"path": None, "logger": None, "disabled": True})
            return None
        try:
            d = os.path.abspath(directory) if directory else log_dir()
            os.makedirs(d, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(d, LOG_PREFIX + ts + ".log")
            if os.path.exists(path):
                # دو اجرا در همان ثانیه — با شناسهٔ پردازه جدا شود
                path = os.path.join(d, LOG_PREFIX + ts + "-" + str(os.getpid()) + ".log")
            logger = _make_logger(path)
            _SESSION.update({"path": path, "logger": logger, "disabled": False})
            _purge_old(d, keep=MAX_SESSIONS - 1)  # جای سشن جدید هم حساب می‌شود
            return path
        except Exception:
            # لاگ هرگز نباید خودش برنامه را زمین بزند
            _SESSION.update({"path": None, "logger": None, "disabled": True})
            return None


def session_path():
    """مسیر فایل سشن جاری — None یعنی لاگ فایلی فعال نیست."""
    return _SESSION.get("path")


def _ensure() -> None:
    if _SESSION.get("path") or _SESSION.get("disabled"):
        return
    setup()


def _log(level: int, msg, args=()):
    try:
        _ensure()
        logger = _SESSION.get("logger")
        if logger is not None:
            logger.log(level, msg, *args, stacklevel=3)
    except Exception:
        # لاگ نباید مسیر اصلی برنامه را بشکند
        pass


def info(msg, *args):
    """ثبت رخداد عادی."""
    _log(logging.INFO, msg, args)


def warn(msg, *args):
    """ثبت هشدار — چیزی که ارزش بررسی دارد."""
    _log(logging.WARNING, msg, args)


def error(msg, *args):
    """ثبت خطا با جزئیات."""
    _log(logging.ERROR, msg, args)


def exception(msg, *args):
    """ثبت خطا همراه با رد کامل (traceback) — برای exception زنده."""
    try:
        _ensure()
        logger = _SESSION.get("logger")
        if logger is not None:
            logger.error(msg, *args, exc_info=True, stacklevel=2)
    except Exception:
        pass


def install_hooks() -> None:
    """قلاب سراسری خطاهای نادیده‌گرفته‌شده — هیچ خطایی بی‌صدا نماند.

    خطاهای uncaught رشتهٔ اصلی و رشته‌های فرعی را در لاگ می‌نویسد و
    سپس به قلاب قبلی (نمایش پیش‌فرض پایتون) هم می‌سپارد.
    """
    with _LOCK:
        if _SESSION.get("hooks"):
            return
        _SESSION["hooks"] = True
    prev_exc = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            _ensure()
            logger = _SESSION.get("logger")
            if logger is not None:
                logger.error("خطای نادیده‌گرفته‌شده در برنامه — %s: %s",
                             getattr(exc_type, "__name__", exc_type), exc,
                             exc_info=(exc_type, exc, tb))
        except Exception:
            pass
        try:
            prev_exc(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook

    try:
        prev_thread = threading.excepthook

        def _thread_hook(args):
            try:
                _ensure()
                logger = _SESSION.get("logger")
                if logger is not None:
                    logger.error(
                        "خطای نادیده‌گرفته‌شده در رشتهٔ فرعی %s — %s",
                        getattr(args.thread, "name", "?"), args.exc_value,
                        exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
            except Exception:
                pass
            try:
                prev_thread(args)
            except Exception:
                pass

        threading.excepthook = _thread_hook
    except Exception:
        pass


def close() -> None:
    """بستن فایل لاگ — بیشتر برای تست‌ها؛ برنامه به آن نیاز ندارد."""
    with _LOCK:
        logger = _SESSION.get("logger")
        if logger is not None:
            for h in list(logger.handlers):
                try:
                    h.close()
                except Exception:
                    pass
                logger.removeHandler(h)
        _SESSION["path"] = None
        _SESSION["logger"] = None


# ─────────────────────── خواندن برای صفحهٔ «لاگ برنامه» ───────────────────────


def tail(limit: int = 300, level=None, search: str = "",
         sessions: int = 3, directory=None):
    """آخرین خطوط لاگ — تازه‌ترین سطر اول.

    level: کمینهٔ سطح — «error» یعنی فقط خطا؛ «warn» هشدار و خطا؛
    None یعنی همه. سطرهای ادامهٔ (traceback) با سطح سطر بالای خود
    حساب می‌شوند تا با فیلتر پدرشان همراه بمانند.
    """
    limit = max(1, int(limit))
    min_rank = _RANK.get(_norm_level(level), 0)
    needle = str(search or "").strip().lower()
    out = []
    files = session_files(directory)[:max(1, int(sessions))]
    for path in files:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        batch = []
        cur = {"ts": "", "level": None, "src": ""}
        for raw in lines:
            raw = raw.rstrip("\n")
            m = _HEADER_RE.match(raw)
            if m:
                cur = {"ts": m.group(1), "level": m.group(2).upper(),
                       "src": m.group(3)}
                msg = m.group(4)
            else:
                if not raw.strip():
                    continue
                msg = raw
            if min_rank and _RANK.get(_norm_level(cur["level"]), 0) < min_rank:
                continue
            if needle and needle not in (
                    cur["ts"] + " " + cur["src"] + " " + msg).lower():
                continue
            batch.append({"ts": cur["ts"], "level": cur["level"],
                          "src": cur["src"], "msg": msg,
                          "file": os.path.basename(path)})
        batch.reverse()
        out.extend(batch)
        if len(out) >= limit:
            break
    return out[:limit]


def stats(directory=None) -> dict:
    """خلاصهٔ پوشهٔ لاگ برای نمایش در صفحه — سشن‌ها، حجم و سشن جاری."""
    d = os.path.abspath(directory) if directory else log_dir()
    files = session_files(d)
    mains = [p for p in files if not _is_backup(p)]
    total = 0
    for p in files:
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return {
        "dir": d,
        "sessions": len(mains),
        "files": len(files),
        "bytes": total,
        "kb": round(total / 1024.0, 1),
        "current": _SESSION.get("path"),
    }


def _session_info_text(directory: str, files) -> str:
    """فایل توضیح همراه zip پشتیبانی — خوانا حتی بیرون از برنامه."""
    try:
        ver = app_version()
    except Exception:
        ver = VERSION_FALLBACK
    return "\n".join([
        "rosetash-health-monitoring — support log export",
        "نسخهٔ برنامه: " + str(ver),
        "زمان خروجی: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "میزبان: " + socket.gethostname(),
        "سیستم‌عامل: " + platform.platform(),
        "پایتون: " + sys.version.split()[0],
        "پوشهٔ لاگ: " + directory,
        "سشن جاری: " + str(_SESSION.get("path") or "—"),
        "فایل‌های پیوست: " + str(len(files)),
        "",
        "هر فایل app-*.log یک اجرای برنامه است؛ تازه‌ترین سشن بیشترین مهر زمانی را دارد.",
        "سطرهای ادامه‌دار بدون مهر زمانی، بدنهٔ traceback سطر بالای خود هستند.",
    ]) + "\n"


def export_zip(directory=None, sessions: int = EXPORT_SESSIONS, dest=None):
    """zip چند سشن اخیر برای ارسال در پشتیبانی.

    برمی‌گرداند (مسیر فایل zip، تعداد فایل‌های لاگ، حجم بایت)؛
    در صورت نبود لاگ یا خطای نوشتن None برمی‌گردد.
    """
    _ensure()
    d = os.path.abspath(directory) if directory else log_dir()
    chosen = []
    mains = [p for p in session_files(d) if not _is_backup(p)]
    for m in mains[:max(1, int(sessions))]:
        chosen.append(m)
        for sib in sorted(glob.glob(m + ".*")):
            if os.path.isfile(sib):
                chosen.append(sib)
    if not chosen:
        return None, 0, 0
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest or os.path.join(d, "roztash-logs-" + ts + ".zip")
    try:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("session-info.txt", _session_info_text(d, chosen))
            for p in chosen:
                zf.write(p, arcname=os.path.basename(p))
        size = os.path.getsize(dest)
    except OSError:
        return None, 0, 0
    info("خروجی پشتیبانی ساخته شد — %s (%d فایل)",
         os.path.basename(dest), len(chosen))
    return dest, len(chosen), size