# -*- coding: utf-8 -*-
"""بررسی دسترسی به اینترنت — نشان «زنده» نوار بالا از همین‌جا پر می‌شود.

چرا این ماژول جدا است: نشان نوار بالا پیش‌تر وضعیت «پل محلی» را نشان می‌داد
و چون پل همیشه روی همین سیستم بالا بود، عملاً همیشه سبز و «زنده» می‌ماند —
حتی وقتی اینترنت نبود. این‌جا فقط چیزی سنجیده می‌شود که واقعاً می‌تواند
قطع شود: دسترسی به اینترنت.

قواعد:
  - فقط کتابخانهٔ استاندارد پایتون
  - هرگز استثنا به بیرون نمی‌دهد؛ نبود شبکه یعنی False
  - نتیجه چند ثانیه کش می‌شود تا هر فراخوانی، سرور بیرونی را نزند
  - چند مقصد پشت سر هم امتحان می‌شود؛ در ایران بعضی مقصدها بسته‌اند، پس
    «هر پاسخی از هر مقصد» یعنی اینترنت هست — حتی 403 یا 404، چون یعنی
    بسته به سرور رسیده و برگشته است
  - متغیرهای محیطی (هر دو املای ROZTASH_* و ROSETASH_* پذیرفته می‌شود):
      ROZTASH_NET_TTL   عمر کش به ثانیه، پیش‌فرض ۸
      ROZTASH_NETCHECK=0  بررسی خاموش — نشان همیشه «زنده» می‌ماند
"""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.error
import urllib.request

import applog


def _env(*names, default: str = "") -> str:
    """نخستین متغیر محیطی موجود — پذیرش هر دو املای ROZTASH/ROSETASH."""
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v
    return default


ENABLED = _env("ROZTASH_NETCHECK", "ROSETASH_NETCHECK", default="1") != "0"
TTL = float(_env("ROZTASH_NET_TTL", "ROSETASH_NET_TTL", default="8"))
TIMEOUT = float(_env("ROZTASH_NET_TIMEOUT", "ROSETASH_NET_TIMEOUT", default="1.6"))

# مقصدها به ترتیب امتحان می‌شوند — همه از کلادفلر است چون پنل خودش با
# تونل کلادفلر بیرون می‌رود و این مقصدها از ایران هم باز می‌شوند.
_TARGETS = (
    "https://www.cloudflare.com/cdn-cgi/trace",
    "https://one.one.one.one/cdn-cgi/trace",
    "https://api.cloudflare.com/client/v4/",
)
_TCP_FALLBACK = ("www.cloudflare.com", 443)

_lock = threading.Lock()
_state: dict = {"ok": False, "checked": 0.0}


def _probe_url(url: str, timeout: float) -> bool:
    """یک GET کوتاه — هر پاسخی (حتی 403/404) یعنی شبکه بیرون باز است."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Roztash-Health/1.0",
                      "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(64)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def _probe_tcp(host: str, port: int, timeout: float) -> bool:
    """اتصال TCP خالی — اگر HTTP جایی جواب نداد، دست‌کم DNS و مسیر را می‌سنجد."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _probe() -> bool:
    for url in _TARGETS:
        if _probe_url(url, TIMEOUT):
            return True
    return _probe_tcp(*_TCP_FALLBACK, TIMEOUT)


def internet_available(force: bool = False) -> bool:
    """آیا اینترنت هست؟ نتیجه تا TTL ثانیه از حافظه می‌آید.

    فراخوانی مسدودکننده است (حداکثر چند ثانیه)؛ در حلقهٔ رابط کاربری با
    asyncio.to_thread صدا زده شود تا پنجره قفل نشود.
    """
    if not ENABLED:
        return True
    now = time.time()
    with _lock:
        if not force and _state["checked"] and (now - _state["checked"]) < TTL:
            return bool(_state["ok"])
    ok = _probe()
    with _lock:
        had = bool(_state["checked"])
        prev = bool(_state["ok"])
        _state["ok"] = ok
        _state["checked"] = time.time()
    if had and prev != ok:
        applog.info("اینترنت %s", "وصل شد" if ok else "قطع شد")
    return ok


def last_check_age() -> float:
    """چند ثانیه از آخرین بررسی گذشته — برای نمایش/عیب‌یابی."""
    with _lock:
        return time.time() - _state["checked"] if _state["checked"] else -1.0
