# -*- coding: utf-8 -*-
"""تست لاگر فایل‌محور برنامه — بدون رابط گرافیکی و بدون اینترنت.

بررسی می‌کند که:
  - هر اجرا یک فایل سشن می‌سازد؛ سطرها مهر زمانی کامل و سطح دارند؛
  - فیلتر سطح و جستجوی صفحهٔ لاگ درست کار می‌کند (سطر جدیدتر، اول)؛
  - سطرهای traceback با سطح پدرشان همراه می‌مانند؛
  - ماسک مک و حریم خصوصی (نداشتن مقدار خام سلامت در لاگ)؛
  - zip پشتیبانی چند سشن اخیر را می‌گیرد و بیرون از برنامه خواندنی است؛
  - نگهداری سشن‌ها سقف دارد و ROZTASH_LOG=0 لاگ را خاموش می‌کند؛
  - خطای نادیده‌گرفته‌شده (قلاب) و خطای اتصال به پل ثبت می‌شوند؛
  - اتصال پل در گذار ثبت می‌شود (بدون اسپم) و بازگشت به دادهٔ زنده لاگ دارد.

اجرا از ریشهٔ مخزن:
    uv run python tests/test_applog.py
"""
import json
import os
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

TMP = tempfile.mkdtemp(prefix="roztash-applog-test-")
os.environ["ROZTASH_LOG_DIR"] = TMP

import applog  # noqa: E402
import live  # noqa: E402

fails = []


def check(name, cond):
    print(("OK   — " if cond else "FAIL — ") + name)
    if not cond:
        fails.append(name)


def read_log(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def msgs(entries):
    return [e["msg"] for e in entries]


# ── ۱) سشن و قالب سطر ──
p1 = applog.setup(directory=TMP, force=True)
applog.info("شروع تست لاگ")
applog.warn("هشدار نمونه در تست")
applog.error("خطای نمونه در تست")

txt = read_log(p1)
check("فایل سشن ساخته شد", os.path.exists(p1))
check("نام فایل با پیشوند app-", os.path.basename(p1).startswith("app-"))
check("مهر زمانی کامل + سطح INFO",
      time.strptime(txt.split(" | ")[0].strip(), "%Y-%m-%d %H:%M:%S") is not None)
check("سطربندی INFO", " | INFO    | " in txt)
check("سطربندی WARNING", " | WARNING | " in txt)
check("سطربندی ERROR", " | ERROR   | " in txt)
check("متن پیام‌ها", all(m in txt for m in ("شروع تست لاگ", "هشدار نمونه در تست",
                                          "خطای نمونه در تست")))

# ── ۲) tail: ترتیب، فیلتر سطح، جستجو ──
entries = applog.tail(limit=10, directory=TMP)
check("تازه‌ترین سطر اول است", entries and entries[0]["msg"] == "خطای نمونه در تست")
check("سطح در خروجی tail", entries[0]["level"] == "ERROR")
check("ساعت در خروجی tail", len(entries[0]["ts"]) == 19)
lvl_err = msgs(applog.tail(limit=10, level="error", directory=TMP))
check("فیلتر error فقط خطا", "خطای نمونه در تست" in lvl_err
      and "هشدار نمونه در تست" not in lvl_err)
lvl_warn = msgs(applog.tail(limit=10, level="warn", directory=TMP))
check("فیلتر warn شامل هشدار و خطا",
      "هشدار نمونه در تست" in lvl_warn and "خطای نمونه در تست" in lvl_warn
      and "شروع تست لاگ" not in lvl_warn)
check("جستجو",
      msgs(applog.tail(limit=10, search="هشدار نمونه", directory=TMP))
      == ["هشدار نمونه در تست"])

# ── ۳) traceback با سطح پدرش ──
try:
    raise ValueError("راز خطا در تست")
except ValueError:
    applog.exception("خطای همراه traceback")
tb = applog.tail(limit=30, level="error", directory=TMP)
joined = "\n".join(msgs(tb))
check("خطای traceback در لاگ", "خطای همراه traceback" in joined)
check("رد کامل (Traceback) پیوست شده", "Traceback (most recent call last)" in joined)
check("پیام خطای اصلی در رد", "ValueError" in joined and "راز خطا در تست" in joined)

# ── ۴) ماسک مک ──
check("ماسک مک کامل",
      applog.mask_mac("88:57:21:B8:AC:29") == "88:57:**:**:AC:29")
check("ماسک مک خالی", applog.mask_mac("") == "")
check("ماسک رشتهٔ بی‌قالب", applog.mask_mac("abcdef") == "abcd…")

# ── ۵) قلاب خطای نادیده‌گرفته‌شده ──
seen = {}
_real_hook = sys.excepthook


def _capture(exc_type, exc, tb_):
    """قلاب قبلی — مثل نمایش پیش‌فرض پایتون؛ باید بعد از لاگ صدا شود."""
    seen["type"] = exc_type


sys.excepthook = _capture
applog.install_hooks()              # قلاب قبلی را می‌پوشاند و به آن می‌سپارد
_installed = sys.excepthook
applog.install_hooks()              # بار دوم بی‌اثر است (همان قلاب می‌ماند)
try:
    raise RuntimeError("انفجار آزمایشی")
except RuntimeError as exc:
    sys.excepthook(type(exc), exc, exc.__traceback__)   # همان کاری که مفسر می‌کند
_idempotent = sys.excepthook is _installed
sys.excepthook = _real_hook
check("نصب قلاب بار دوم بی‌اثر است", _idempotent)
check("قلاب به قلاب قبلی می‌سپارد", seen.get("type") is RuntimeError)
hook_entries = msgs(applog.tail(limit=60, search="نادیده", directory=TMP))
check("خطای نادیده‌گرفته‌شده در لاگ",
      any("RuntimeError" in m for m in hook_entries))
hook_tb = "\n".join(msgs(applog.tail(limit=80, level="error", directory=TMP)))
check("رد کامل خطای نادیده‌گرفته‌شده", "انفجار آزمایشی" in hook_tb)

# ── ۶) live: پل خاموش، گذار وضعیت، بازگشت به زنده، لرزش با مک ماسک‌شده ──
MACS = "88:57:21:B8:AC:29"


class _Handler(BaseHTTPRequestHandler):
    def _send(self, doc):
        body = json.dumps(doc).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # دادهٔ جعلی سلامت — هیچ‌کدام نباید در لاگ بیفتد
        self._send({"ok": True, "fetched_at": time.time(),
                    "gateways": [{"gw": "gw-test-1", "online": True}],
                    "bands": [{"mac": MACS, "rssi": -70}],
                    "health": [{"state": "done", "avg": 187, "bpm": [187]}],
                    "vitals": [{"spo2_raw": ["0A,B2:987654321"], "battery": 90}]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        self._send({"ok": True})

    def log_message(self, *args):
        pass


live.MODE = "auto"
live._bridge_state.update({"ok": None, "since": 0.0})
live.BRIDGE = "http://127.0.0.1:9"          # پل خاموش (پورت بسته)
before = int(time.time())
d1 = live.live_status(force=True)
d2 = live.live_status(force=True)
d3 = live.live_status(force=True)
check("پل خاموش None برمی‌گرداند", d1 is None and d2 is None and d3 is None)
down_entries = applog.tail(limit=200, search="پل برقرار نشد", directory=TMP)
down = msgs(down_entries)
check("خطای اتصال فقط یک‌بار ثبت شد (بدون اسپم)", len(down) == 1)
check("جزئیات خطا در پیام (نشانی پل)",
      bool(down) and "http://127.0.0.1:9" in down[0])
check("جزئیات خطا در پیام (نوع خطا)",
      bool(down) and ("URLError" in down[0] or "Connection" in down[0]
                      or "Error" in down[0]))
check("خطای اتصال با سطح ERROR ثبت شد",
      bool(down_entries) and down_entries[0]["level"] == "ERROR")
check("مهر زمانی خطا مال امروز است",
      bool(down_entries) and down_entries[0]["ts"][:10] == time.strftime("%Y-%m-%d"))

srv = HTTPServer(("127.0.0.1", 0), _Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
live.BRIDGE = "http://127.0.0.1:%d" % port
doc = live.live_status(force=True)
check("پل تازه پاسخ می‌دهد", bool(doc and doc.get("ok")))
back = msgs(applog.tail(limit=200, search="بازگشت به دادهٔ زنده", directory=TMP))
check("بازگشت به دادهٔ زنده ثبت شد", len(back) >= 1)

ok, msg = live.send_vibrate(MACS)
check("فرمان لرزش از پل تست موفق بود", ok is True)
vib = msgs(applog.tail(limit=200, search="فرمان لرزش", directory=TMP))
check("فرمان لرزش در لاگ", len(vib) >= 1)
check("مک در لاگ ماسک شده", any(applog.mask_mac(MACS) in m for m in vib))
logtext = read_log(p1)
check("مک کامل هرگز در لاگ نیست", MACS not in logtext)
check("مقدار خام ضربان در لاگ نیست", "187" not in logtext)
check("مقدار خام اکسیژن در لاگ نیست", "987654321" not in logtext)
srv.shutdown()

# ── ۷) zip پشتیبانی: چند سشن، خواندنی بیرون از برنامه ──
applog.close()
time.sleep(1.05)
p2 = applog.setup(directory=TMP, force=True)
applog.info("سشن دوم برای zip")
applog.close()
zpath, n, size = applog.export_zip(directory=TMP)
check("zip ساخته شد", bool(zpath) and os.path.exists(zpath) and size > 0)
check("zip چند سشن اخیر را دارد", n >= 2)
with zipfile.ZipFile(zpath) as zf:
    names = zf.namelist()
    info = zf.read("session-info.txt").decode("utf-8")
    first = zf.read(os.path.basename(p1)).decode("utf-8")
check("zip فایل توضیح دارد", "session-info.txt" in names)
check("zip فایل هر دو سشن را دارد",
      os.path.basename(p1) in names and os.path.basename(p2) in names)
check("zip بیرون از برنامه خواندنی است", "شروع تست لاگ" in first)
check("فایل توضیح نسخه و سیستم دارد",
      "نسخهٔ برنامه" in info and "سیستم‌عامل" in info)
check("خود خروجی هم در لاگ ثبت شد",
      msgs(applog.tail(limit=50, search="خروجی پشتیبانی", directory=TMP)) != [])

# ── ۸) نگهداری سشن‌ها (سقف) ──
tmp3 = tempfile.mkdtemp(prefix="roztash-applog-purge-")
for i in range(20):
    fp = os.path.join(tmp3, "app-20260101-%06d.log" % i)
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write("x\n")
    os.utime(fp, (1000 + i, 1000 + i))       # mtime قدیمی، پیدرپی
applog.setup(directory=tmp3, force=True)
applog.info("سشن تازه بعد از پاک‌سازی")
applog.close()
mains = [f for f in applog.session_files(tmp3)
         if not f.endswith(".log.1")]
check("سقف نگهداری سشن‌ها رعایت شد",
      len(mains) <= applog.MAX_SESSIONS)

# ── ۹) خاموش‌کردن با ROZTASH_LOG=0 ──
tmp4 = tempfile.mkdtemp(prefix="roztash-applog-off-")
os.environ["ROZTASH_LOG"] = "0"
p_off = applog.setup(directory=tmp4, force=True)
applog.error("این سطر نباید جایی ثبت شود")
applog.close()
del os.environ["ROZTASH_LOG"]
check("با ROZTASH_LOG=0 فایلی ساخته نمی‌شود",
      p_off is None and applog.session_files(tmp4) == [])
applog.setup(directory=TMP, force=True)
check("خاموشی موقتی بود — لاگ دوباره کار می‌کند",
      applog.session_path() is not None)

print()
print("نتیجه:", "همهٔ بررسی‌ها پاس شد" if not fails else f"{len(fails)} خطا: {fails}")
sys.exit(1 if fails else 0)