# -*- coding: utf-8 -*-
"""دسترسی از اینترنت — پیش‌نیازهای کلادفلر همراه خود برنامه.

هدف: اتصال از اینترنت محدود به یک لپ‌تاپ خاص نباشد؛ هر سیستمی که برنامه
روی آن نصب شود، خودش تونل را بالا می‌آورد و پنل را از بیرون باز می‌کند.

سه کار این‌جا انجام می‌شود:

  1) تنظیمات همراه برنامه — شناسهٔ حساب، دامنه و تونل در فایل تنظیمات
     ذخیره می‌شوند. اگر فایل نبود، برنامه خودش از روی توکن API آن‌ها را
     از حساب کلادفلر می‌کشد و همان‌جا می‌نویسد؛ یعنی روی هر سیستم تازه
     هم هیچ مقداری دستی وارد نمی‌شود و همه‌چیز برای همان حساب تنظیم است.

  2) تونل — برنامه پیش‌نیاز کلادفلر (cloudflared) را کنار خودش نگه
     می‌دارد و تونل را با همان توکن بالا می‌آورد. روی لینوکس یک سرویس
     دائمی می‌سازد تا بعد از بستن برنامه هم پنل از بیرون در دسترس بماند.

  3) قفل ورود ایمیلی — ادمین‌ها داخل خود برنامه اضافه/حذف می‌شوند و
     برنامه سیاست Cloudflare Access را خودش می‌سازد و به‌روز می‌کند؛
     کلادفلر کد یک‌بارمصرف را به همان ایمیل‌ها می‌فرستد.

قواعد (مثل بقیهٔ لایهٔ داده):
  - فقط کتابخانهٔ استاندارد پایتون
  - هیچ استثنایی به بیرون نمی‌دهد؛ خطا به شکل پیام فارسی برمی‌گردد
  - همهٔ کارهای شبکه‌ای فقط با توکن API محدود و بدون تاریخ انقضا
  - دادهٔ حساس بیرون از مخزن نگه داشته می‌شود

محل فایل‌ها — پوشهٔ ~/.cloudflared (قابل تغییر با ROZTASH_CF_HOME):
    rosetash-cf-api-token     توکن API — تنها چیزی که یک‌بار دستی گذاشته می‌شود
    rosetash-tunnel-token     توکن تونل — برنامه خودش پر می‌کند
    rosetash-tunnel.env       برای سرویس systemd
    rosetash-remote.json      تنظیمات همراه برنامه — حساب، دامنه، ایمیل‌ها
    cloudflared               نسخهٔ همراه برنامه — اگر در سیستم نصب نباشد

متغیرهای محیطی (هر دو املای ROZTASH_* و ROSETASH_* پذیرفته می‌شود):
    ROZTASH_CF_HOME      پوشهٔ نگه‌داری فایل‌ها — پیش‌فرض ~/.cloudflared
    ROZTASH_CF_API_TOKEN توکن API از محیط (برای نصب خودکار بدون فایل)
    ROZTASH_REMOTE_HOST  میزبان عمومی — پیش‌فرض panel.<zone>
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request

import applog

API = "https://api.cloudflare.com/client/v4"
RELEASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
TIMEOUT = 15
SVC = "cloudflared-rosetash.service"

_apps_cache: dict = {"t": 0.0, "rows": None}


def _env(*names, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v
    return default


def _home() -> str:
    """پوشهٔ نگه‌داری فایل‌های کلادفلر — همراه خود برنامه."""
    p = os.path.expanduser(
        _env("ROZTASH_CF_HOME", "ROSETASH_CF_HOME", default="~/.cloudflared"))
    try:
        os.makedirs(p, exist_ok=True)
        os.chmod(p, 0o700)
    except Exception:
        pass
    return p


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _write(path: str, text: str, mode: int = 0o600) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    try:
        os.chmod(path, mode)
    except Exception:
        pass


def _token() -> str:
    """توکن API کلادفلر — از محیط، یا از فایل کنار برنامه."""
    t = _env("ROZTASH_CF_API_TOKEN", "ROSETASH_CF_API_TOKEN")
    if t:
        return t.strip()
    return _read(os.path.join(_home(), "rosetash-cf-api-token"))


# ═══════════ تنظیمات همراه برنامه ═══════════

def _cfg_path() -> str:
    return os.path.join(_home(), "rosetash-remote.json")


def config() -> dict:
    try:
        with open(_cfg_path(), encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _save_config(doc: dict) -> None:
    try:
        _write(_cfg_path(), json.dumps(doc, ensure_ascii=False, indent=2))
    except Exception:
        pass


def _cf(path: str, method: str = "GET", body: dict | None = None,
        token: str = "") -> tuple[bool, object, str]:
    """یک درخواست به API کلادفلر — نتیجه: (موفق، داده، پیام خطا)."""
    tok = token or _token()
    if not tok:
        return False, {}, "توکن API کلادفلر تنظیم نشده است"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            doc = json.loads(exc.read().decode("utf-8"))
            errs = doc.get("errors") or []
            msg = errs[0].get("message") if errs else str(exc)
        except Exception:
            msg = "%s %s" % (exc.code, exc.reason)
        applog.error("کلادفلر — %s %s — %s", method, path, msg)
        return False, {}, msg
    except Exception as exc:
        applog.error("کلادفلر — %s %s — %s", method, path, exc)
        return False, {}, "اتصال به کلادفلر برقرار نشد"
    if not doc.get("success", True):
        errs = doc.get("errors") or []
        return False, doc, (errs[0].get("message") if errs else "خطای کلادفلر")
    return True, doc.get("result") or {}, ""


def ensure_config(force: bool = False) -> dict:
    """تنظیمات را می‌خواند و اگر ناقص بود، از روی توکن کامل می‌کند.

    برمی‌گرداند: {'ok', 'account_id', 'zone_id', 'zone', 'host', 'err'}
    """
    cfg = config()
    ok = bool(cfg.get("zone_id") and cfg.get("account_id") and cfg.get("zone"))
    if not ok or force:
        got, res, err = _cf("/zones")
        if not got:
            return {"ok": False, "err": err, **cfg}
        zones = res if isinstance(res, list) else []
        if not zones:
            return {"ok": False, "err": "دامنه‌ای روی این حساب کلادفلر نیست",
                    **cfg}
        # اگر چند دامنه باشد، اولی — در فایل تنظیمات قابل تغییر است
        z = zones[0]
        cfg["zone"] = z.get("name", "")
        cfg["zone_id"] = z.get("id", "")
        cfg["account_id"] = (z.get("account") or {}).get("id", "")
        cfg["host"] = cfg.get("host") or ("panel." + cfg["zone"])
        _save_config(cfg)
        applog.info("تنظیمات کلادفلر همراه برنامه ساخته شد — دامنه %s",
                    cfg.get("zone"))
    return {"ok": bool(cfg.get("zone_id")), "err": "", **cfg}


def public_url() -> str:
    cfg = config()
    host = _env("ROZTASH_REMOTE_HOST", "ROSETASH_REMOTE_HOST",
                default="") or cfg.get("host") or ""
    return ("https://" + host) if host else ""


# ═══════════ پیش‌نیاز کلادفلر (cloudflared) ═══════════

def _bin_name() -> str:
    return "cloudflared.exe" if os.name == "nt" else "cloudflared"


def _bin_path() -> str:
    return os.path.join(_home(), _bin_name())


def bin_ready() -> bool:
    return bool(shutil.which("cloudflared")) or os.path.exists(_bin_path())


def ensure_binary() -> tuple[bool, str]:
    """اگر cloudflared در سیستم نبود، نسخهٔ همراه برنامه را می‌گذارد."""
    if bin_ready():
        return True, ""
    sysname = platform.system().lower()
    if sysname == "windows":
        url = RELEASE + "cloudflared-windows-amd64.exe"
    elif sysname == "linux":
        url = RELEASE + "cloudflared-linux-amd64"
    else:
        return False, "این سیستم پشتیبانی نمی‌شود — cloudflared را دستی نصب کن"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "rosetash-health-monitoring"})
        with urllib.request.urlopen(req, timeout=180) as resp, \
                open(_bin_path(), "wb") as fh:
            shutil.copyfileobj(resp, fh)
        os.chmod(_bin_path(), 0o755)
        applog.info("cloudflared همراه برنامه نصب شد — %s", _bin_path())
        return True, ""
    except Exception as exc:
        applog.error("دریافت cloudflared ناکام ماند — %s", exc)
        return False, "دریافت cloudflared ناموفق بود — اینترنت سیستم را بررسی کن"


def _exe() -> str:
    return shutil.which("cloudflared") or _bin_path()


def _run(args: list[str], timeout: int = 40) -> tuple[int, str]:
    try:
        p = subprocess.run([_exe()] + args, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:
        return 1, str(exc)


def tunnel_id() -> str:
    """شناسهٔ تونل — از تنظیمات، یا با جست‌وجو در حساب."""
    cfg = config()
    if cfg.get("tunnel_id"):
        return cfg["tunnel_id"]
    acc = cfg.get("account_id")
    if not acc:
        return ""
    got, res, _ = _cf("/accounts/%s/cfd_tunnel" % acc)
    if got:
        for row in (res if isinstance(res, list) else []):
            if row.get("name") == "rosetash-panel":
                cfg["tunnel_id"] = row.get("id", "")
                _save_config(cfg)
                return cfg["tunnel_id"]
    return ""


def tunnel_token() -> str:
    """توکن تونل — اول فایل کنار برنامه، بعد از حساب کلادفلر."""
    t = _read(os.path.join(_home(), "rosetash-tunnel-token"))
    if t:
        return t
    cfg = config()
    tid = cfg.get("tunnel_id") or tunnel_id()
    if tid and cfg.get("account_id"):
        got, res, _ = _cf("/accounts/%s/cfd_tunnel/%s/token"
                          % (cfg["account_id"], tid))
        if got and isinstance(res, dict) and res.get("token"):
            _write(os.path.join(_home(), "rosetash-tunnel-token"),
                   res["token"])
            return res["token"]
    return ""


# ═══════════ تونل — سرویس دائمی یا فرایند خود برنامه ═══════════

def _pid_path() -> str:
    return os.path.join(_home(), "rosetash-tunnel.pid")


def _read_pid() -> int:
    try:
        return int(_read(_pid_path()) or "0")
    except Exception:
        return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid],
                                 capture_output=True, text=True,
                                 timeout=8).stdout
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except Exception:
        return False
    try:  # پردازهٔ زامبی هنوز «زنده» به نظر می‌رسد — از /proc رد می‌شود
        with open("/proc/%d/stat" % pid, encoding="utf-8") as fh:
            if fh.read().split()[2] == "Z":
                return False
    except Exception:
        pass
    return True


def _svc_exists() -> bool:
    if platform.system().lower() != "linux" or not shutil.which("systemctl"):
        return False
    return os.path.exists(
        os.path.expanduser("~/.config/systemd/user/" + SVC))


def _svc_active() -> bool:
    if not _svc_exists():
        return False
    try:
        p = subprocess.run(["systemctl", "--user", "is-active", SVC],
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() == "active"
    except Exception:
        return False


def tunnel_running() -> bool:
    """تونل بالاست؟ — سرویس دائمی یا فرایند خود برنامه."""
    return _svc_active() or _pid_alive(_read_pid())


def tunnel_up() -> tuple[bool, str]:
    """بالا آوردن تونل — سرویس اگر باشد، وگرنه فرایند خود برنامه."""
    cfg = ensure_config()
    if not cfg.get("ok"):
        return False, cfg.get("err") or "تنظیمات کلادفلر کامل نشد"
    ok, err = ensure_binary()
    if not ok:
        return False, err
    tok = tunnel_token()
    if not tok:
        return False, "توکن تونل به دست نیامد — دسترسی Tunnel توکن API را بررسی کن"
    if _svc_exists():
        try:
            p = subprocess.run(["systemctl", "--user", "start", SVC],
                               capture_output=True, text=True, timeout=30)
            if p.returncode == 0:
                return True, "اتصال فعال شد"
            return False, "فعال‌سازی سرویس تونل ناموفق بود"
        except Exception as exc:
            return False, "فعال‌سازی سرویس تونل ناموفق بود — %s" % exc
    if _pid_alive(_read_pid()):
        return True, "تونل همین حالا در حال اجراست"
    env = dict(os.environ)
    env["TUNNEL_TOKEN"] = tok
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # detached
    else:
        kwargs["start_new_session"] = True
    try:
        log = open(os.path.join(_home(), "rosetash-tunnel.log"), "ab")
        proc = subprocess.Popen(
            [_exe(), "--no-autoupdate", "tunnel", "run", "--protocol", "http2"],
            stdout=log, stderr=subprocess.STDOUT, env=env, **kwargs)
        _write(_pid_path(), str(proc.pid), 0o644)
        applog.info("تونل از داخل برنامه اجرا شد — pid=%s", proc.pid)
        return True, "اتصال شروع شد — چند لحظه صبر کن"
    except Exception as exc:
        applog.error("اجرای تونل ناموفق — %s", exc)
        return False, "اجرای تونل ناموفق بود"


def tunnel_down() -> tuple[bool, str]:
    """قطع تونل — فقط چیزی که خود برنامه/سرویس بالا آورده است."""
    if _svc_exists() and _svc_active():
        try:
            p = subprocess.run(["systemctl", "--user", "stop", SVC],
                               capture_output=True, text=True, timeout=30)
            if p.returncode == 0:
                return True, "اتصال قطع شد"
            return False, "قطع سرویس تونل ناموفق بود"
        except Exception as exc:
            return False, "قطع سرویس تونل ناموفق بود — %s" % exc
    pid = _read_pid()
    if not _pid_alive(pid):
        try:
            os.remove(_pid_path())
        except Exception:
            pass
        return True, "تونل اجرا نبود"
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=15)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(16):
                if not _pid_alive(pid):
                    break
                time.sleep(0.5)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    except Exception as exc:
        applog.error("توقف تونل ناموفق — %s", exc)
        return False, "توقف تونل ناموفق بود"
    try:
        os.remove(_pid_path())
    except Exception:
        pass
    applog.info("تونل از داخل برنامه متوقف شد — pid=%s", pid)
    return True, "اتصال قطع شد"


def autostart() -> None:
    """هنگام بالا آمدن برنامه — اگر اتصال خودکار روشن است، تونل را بالا بیار."""
    try:
        cfg = config()
        if not cfg and not _token():
            return  # روی سیستمی که هیچ‌چیز تنظیم نشده، بی‌صدا رد شو
        if cfg.get("auto_start", True):
            ok, msg = tunnel_up()
            applog.info("اتصال خودکار تونل — %s", msg)
    except Exception:
        applog.exception("اتصال خودکار تونل با خطا متوقف شد")


def set_autostart(on: bool) -> tuple[bool, str]:
    cfg = config()
    if not cfg:
        cfg = ensure_config()
    cfg = {k: v for k, v in cfg.items() if k != "err"}
    cfg["auto_start"] = bool(on)
    _save_config(cfg)
    return True, ("اتصال خودکار روشن شد" if on else "اتصال خودکار خاموش شد")


def _install_service() -> tuple[bool, str]:
    """سرویس کاربری systemd — تا بعد از بستن برنامه هم تونل بماند."""
    if platform.system().lower() != "linux" or not shutil.which("systemctl"):
        return False, "سرویس دائمی روی این سیستم پشتیبانی نمی‌شود"
    unit_dir = os.path.expanduser("~/.config/systemd/user")
    try:
        os.makedirs(unit_dir, exist_ok=True)
        unit = (
            "[Unit]\n"
            "Description=Cloudflare Tunnel - rosetash-panel\n"
            "Wants=network-online.target\n"
            "After=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "EnvironmentFile=%h/.cloudflared/rosetash-tunnel.env\n"
            "ExecStart=%s --no-autoupdate tunnel run --protocol http2\n"
            "Restart=on-failure\n"
            "RestartSec=5\n\n"
            "[Install]\n"
            "WantedBy=default.target\n" % _exe())
        with open(os.path.join(unit_dir, SVC), "w", encoding="utf-8") as fh:
            fh.write(unit)
        for args in (["--user", "daemon-reload"],
                     ["--user", "enable", "--now", SVC]):
            p = subprocess.run(["systemctl"] + args, capture_output=True,
                               text=True, timeout=30)
            if p.returncode != 0:
                msg = (p.stderr or p.stdout or "").strip()[-160:]
                applog.error("سرویس دائمی — systemctl %s — %s",
                             " ".join(args), msg)
                return False, msg
        return True, ""
    except Exception as exc:
        applog.error("ساخت سرویس دائمی ناکام ماند — %s", exc)
        return False, str(exc)


# ═══════════ قفل ورود ایمیلی — Cloudflare Access ═══════════

APP_NAME = "rosetash-panel"


def _list_apps() -> list:
    now = time.time()
    if _apps_cache["rows"] is not None and (now - _apps_cache["t"]) < 60:
        return _apps_cache["rows"]
    cfg = config()
    got, res, _ = _cf("/accounts/%s/access/apps" % cfg.get("account_id", ""))
    rows = res if (got and isinstance(res, list)) else []
    if got:
        _apps_cache.update({"t": now, "rows": rows})
    return rows


def _find_app() -> dict:
    for app in _list_apps():
        if app.get("name") == APP_NAME or app.get("domain") == \
                config().get("host"):
            return app
    return {}


def allowed_emails() -> list[str]:
    """ایمیل‌هایی که کلادفلر کد ورود را به آن‌ها می‌فرستد."""
    cfg = config()
    app = _find_app()
    if not app:
        return list(cfg.get("emails") or [])
    got, res, _ = _cf("/accounts/%s/access/apps/%s/policies"
                      % (cfg["account_id"], app["id"]))
    emails: list[str] = []
    if got and isinstance(res, list) and res:
        for inc in (res[0].get("include") or []):
            if inc.get("email"):
                emails.append(inc["email"].get("email", ""))
    return [e for e in emails if e] or list(cfg.get("emails") or [])


def set_allowed_emails(emails: list[str]) -> tuple[bool, str]:
    """سیاست ورود را با همین فهرست ایمیل می‌سازد یا به‌روز می‌کند."""
    cfg = config()
    if not cfg.get("zone_id"):
        cfg = ensure_config()
    if not cfg.get("zone_id"):
        return False, cfg.get("err") or "تنظیمات کلادفلر کامل نشد"

    clean: list[str] = []
    for e in emails:
        e = (e or "").strip().lower()
        if "@" in e and e not in clean:
            clean.append(e)
    if not clean:
        return False, "حداقل یک ایمیل لازم است"

    policy_body = {
        "name": "admins",
        "decision": "allow",
        "include": [{"email": {"email": e}} for e in clean],
    }
    app = _find_app()
    if not app:
        body = {
            "name": APP_NAME,
            "domain": cfg["host"],
            "type": "self_hosted",
            "session_duration": "24h",
            "app_launcher_visible": False,
            "policies": [policy_body],
        }
        got, res, err = _cf("/accounts/%s/access/apps" % cfg["account_id"],
                            "POST", body)
        if not got:
            return False, "ساخت قفل ورود ناموفق بود — %s" % err
        app = res if isinstance(res, dict) else {}
        _apps_cache.update({"t": 0.0, "rows": None})
        if isinstance(app.get("policies"), list) and app["policies"]:
            # سیاست همراه اپ ساخته شد؛ فقط فهرست را در تنظیمات ثبت کن
            cfg["emails"] = clean
            _save_config(cfg)
            applog.info("قفل ورود ایمیلی ساخته شد — %d ایمیل", len(clean))
            return True, "قفل ورود ساخته شد — کد ورود به همین ایمیل‌ها می‌آید"
    else:
        # سیاست‌های قبلی کنار می‌روند و سیاست تازه می‌نشیند
        got, res, _ = _cf("/accounts/%s/access/apps/%s/policies"
                          % (cfg["account_id"], app["id"]))
        if got and isinstance(res, list):
            for old in res:
                _cf("/accounts/%s/access/apps/%s/policies/%s"
                    % (cfg["account_id"], app["id"], old.get("id")), "DELETE")
        got, _, err = _cf("/accounts/%s/access/apps/%s/policies"
                          % (cfg["account_id"], app["id"]), "POST",
                          policy_body)
        if not got:
            return False, "ثبت فهرست ایمیل‌ها ناموفق بود — %s" % err

    cfg["emails"] = clean
    _save_config(cfg)
    applog.info("قفل ورود ایمیلی به‌روز شد — %d ایمیل", len(clean))
    return True, "فهرست ایمیل‌های مجاز ذخیره شد"


def add_email(addr: str) -> tuple[bool, str]:
    addr = (addr or "").strip().lower()
    if ("@" not in addr or " " in addr
            or "." not in addr.rsplit("@", 1)[-1]):
        return False, "ایمیل معتبر نیست"
    cur = allowed_emails()
    if addr in cur:
        return True, "این ایمیل از قبل در فهرست است"
    return set_allowed_emails(cur + [addr])


def remove_email(addr: str) -> tuple[bool, str]:
    addr = (addr or "").strip().lower()
    cur = allowed_emails()
    if addr not in cur:
        return True, "این ایمیل در فهرست نبود"
    left = [e for e in cur if e != addr]
    if not left:
        return False, "حداقل یک ایمیل باید بماند — قفل ورود نباید خالی شود"
    return set_allowed_emails(left)


# ═══════════ راه‌اندازی یک‌مرحله‌ای ═══════════

def setup(progress=None) -> tuple[bool, str]:
    """راه‌اندازی کامل: پیش‌نیاز + تونل + سرویس + آدرس — به‌ترتیب امن.

    آدرس عمومی فقط وقتی باز می‌شود که قفل ورود ایمیل داشته باشد.
    """
    def note(msg):
        applog.info("راه‌اندازی دسترسی از اینترنت — %s", msg)
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    note("بررسی توکن و تنظیمات همراه برنامه")
    cfg = ensure_config()
    if not cfg.get("ok"):
        return False, cfg.get("err") or "تنظیمات کلادفلر کامل نشد"

    note("بررسی پیش‌نیاز cloudflared")
    ok, err = ensure_binary()
    if not ok:
        return False, err

    note("ساخت/یافتن تونل")
    tid = tunnel_id()
    if not tid:
        got, res, err = _cf(
            "/accounts/%s/cfd_tunnel" % cfg["account_id"], "POST",
            {"name": "rosetash-panel", "config_src": "cloudflare"})
        if not got:
            return False, "ساخت تونل ناموفق بود — %s" % err
        tid = res.get("id", "") if isinstance(res, dict) else ""
        c2 = config()
        c2["tunnel_id"] = tid
        _save_config(c2)
    if not tid:
        return False, "شناسهٔ تونل به دست نیامد"

    note("توکن تونل")
    tok = tunnel_token()
    if not tok:
        return False, ("توکن تونل به دست نیامد — دسترسی Tunnel توکن API را "
                       "بررسی کن")
    _write(os.path.join(_home(), "rosetash-tunnel-token"), tok)
    _write(os.path.join(_home(), "rosetash-tunnel.env"),
           "TUNNEL_TOKEN=%s\n" % tok)

    note("نصب سرویس دائمی")
    svc_ok, svc_msg = _install_service()

    note("بالا آوردن تونل")
    up_ok, up_msg = tunnel_up()
    if not up_ok:
        return False, up_msg

    emails = allowed_emails()
    if not emails:
        return True, ("راه‌اندازی انجام شد — برای باز شدن آدرس، اول ایمیل "
                      "ادمین را در همین صفحه اضافه کن")
    note("اتصال مسیر پنل به تونل")
    code, out = _run(["--no-autoupdate", "tunnel", "route", "dns", tid,
                      cfg["host"]], timeout=60)
    if code != 0 and "already" not in out.lower():
        applog.error("ثبت رکورد DNS ناموفق — %s", out.strip()[-200:])
        return True, "راه‌اندازی انجام شد ولی ثبت آدرس ناموفق بود — بعداً دوباره امتحان کن"
    note("بررسی پایانی")
    if not svc_ok:
        applog.info("سرویس دائمی فعال نشد — %s", svc_msg)
    return True, "دسترسی از اینترنت فعال شد — %s" % public_url()


# ═══════════ یک نگاه ═══════════

def status() -> dict:
    """خلاصهٔ وضعیت برای نمایش در صفحهٔ تنظیمات — هرگز استثنا نمی‌دهد."""
    try:
        cfg = ensure_config()
        running = tunnel_running()
        emails = allowed_emails() if cfg.get("ok") else []
        locked = bool(emails)
        if not cfg.get("ok"):
            label = "تنظیم نشده"
            detail = cfg.get("err") or "توکن API کلادفلر روی این سیستم نیست"
        elif running and locked:
            label = "فعال"
            detail = "پنل از اینترنت با قفل ایمیلی کلادفلر باز است"
        elif running and not locked:
            label = "بدون قفل"
            detail = ("تونل وصل است ولی ایمیل ادمین تعریف نشده — تا آن موقع "
                      "آدرس عمومی را باز نکن")
        else:
            label = "غیرفعال"
            detail = "تونل وصل نیست"
        return {
            "ok": bool(cfg.get("ok")),
            "zone": cfg.get("zone", ""),
            "host": cfg.get("host", ""),
            "url": public_url(),
            "installed": bin_ready(),
            "running": running,
            "locked": locked,
            "emails": emails,
            "auto_start": bool(cfg.get("auto_start", True)),
            "label": label,
            "detail": detail,
            "err": cfg.get("err", ""),
        }
    except Exception as exc:
        applog.exception("خواندن وضعیت دسترسی از اینترنت ناکام ماند")
        return {"ok": False, "zone": "", "host": "", "url": "",
                "installed": False, "running": False, "locked": False,
                "emails": [], "auto_start": True, "label": "نامعلوم",
                "detail": str(exc), "err": str(exc)}
