# -*- coding: utf-8 -*-
"""آماده‌سازی گیتوی — ابزارهای همراه، پورت سریال، ساخت LittleFS و فلش کامل.

«موتور» صفحهٔ «آماده‌سازی گیتوی» است و بیرون از رابط کاربری هم کار می‌کند:

    from provisioner import find_tools, list_serial_ports, read_chip_info
    from provisioner import load_manifest, build_config, build_littlefs, flash_gateway

بستهٔ همراه برنامه در ``distribution/gateway-provisioner/`` است: باینری‌های
فریمور، esptool/mklittlefs برای ویندوز و لینوکس و manifest.json با آدرس‌های
فلش و هش‌ها. مسیر بسته با ROZTASH_PROVISIONER (یا املای ROSETASH_) عوض می‌شود.

قواعد:
  - فقط کتابخانهٔ استاندارد؛ pyserial اگر باشد فهرست پورت را بهتر می‌دهد
  - توابع هرگز استثنا بیرون نمی‌دهند — خطا به پیام فارسی تبدیل می‌شود
  - فلش بلند است؛ progress(line) خط‌های زندهٔ esptool را می‌دهد
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# PyInstaller places modules directly in _MEIPASS; source/Flet builds use src/app.
_BUNDLE_ROOT = (Path(sys._MEIPASS)
                if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")
                else _HERE.parent)
_DEFAULT_BUNDLE = _BUNDLE_ROOT / "distribution" / "gateway-provisioner"

# هندسهٔ پارتیشن min_spiffs هستهٔ ۳٫۳٫۱۲ — مطابق firmware/gateway و docs
LITTLEFS_SIZE = "0x20000"
LITTLEFS_PAGE = "256"
LITTLEFS_OFFSET = "0x3D0000"
DEFAULT_BAUD = 460800
TARGET_CHIP = "esp32s3"
TARGET_FLASH_SIZE = "16MB"
TARGET_FW_VERSION = "0.5.2-alerts"

_GW_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")  # همان قاعدهٔ پل
_LIMITS = {"gw_id": 23, "zone": 39, "mqtt_host": 47}
_PERCENT_RE = re.compile(r"\((\d+)\s?%\)")
_MAC_RE = re.compile(r"MAC:\s*([0-9a-fA-F:]{17})")


def _env(*names: str, default: str = "") -> str:
    """نخستین متغیر محیطی موجود — پذیرش هر دو املای ROZTASH/ROSETASH."""
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v
    return default


def bundle_dir() -> Path:
    """مسیر بستهٔ همراه — پیش‌فرض کنار مخزن، قابل تغییر با متغیر محیطی."""
    raw = _env("ROZTASH_PROVISIONER", "ROSETASH_PROVISIONER")
    return Path(raw) if raw else _DEFAULT_BUNDLE


def platform_dir() -> str:
    """پوشهٔ ابزارهای همین سیستم داخل بسته."""
    if sys.platform.startswith("win"):
        return "windows-amd64"
    if sys.platform == "darwin":
        return "macos"
    return "linux-x86_64"


def _run(args: list[str], timeout: float) -> subprocess.CompletedProcess | None:
    """اجرای فرمان — CompletedProcess یا None؛ هرگز استثنا نمی‌دهد."""
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout)
    except Exception:
        return None


def _text(res: subprocess.CompletedProcess | None) -> str:
    if res is None:
        return ""
    return ((res.stdout or b"") + (res.stderr or b"")).decode(
        "utf-8", errors="replace")


# ─────────────────────────── ابزارها ───────────────────────────


def find_tools(bundle: Path | str | None = None, platform: str | None = None,
               home: Path | str | None = None) -> dict:
    """مسیر esptool و mklittlefs — بستهٔ همراه، بعد نصب آردوینو، بعد PATH.

    برمی‌گرداند {"esptool": str|None، "mklittlefs": str|None، "sources": {...}}
    که sources می‌گوید هر ابزار از کجا آمد (bundled/arduino/path/env).
    """
    bundle = Path(bundle or bundle_dir())
    platform = platform or platform_dir()
    home = Path(home or Path.home())
    plat = bundle / "tools" / platform
    exe = ".exe" if platform.startswith("windows") else ""

    out = {"platform": platform, "bundle": str(bundle), "sources": {}}

    def first(cands: list[tuple[str, object]]):
        for tag, p in cands:
            if p and Path(str(p)).is_file():
                return str(p), tag
        return None, ""

    esptool, src = first([
        ("env", _env("ROZTASH_ESPTOOL", "ROSETASH_ESPTOOL") or None),
        ("bundled", plat / f"esptool{exe}"),
        *[(("arduino"), Path(p)) for p in sorted(glob.glob(str(
            home / ".arduino15" / "packages" / "esp32" / "tools" / "esptool_py"
            / "*" / f"esptool{exe}")))],
        ("path", shutil.which(f"esptool{exe}")),
    ])
    out["esptool"], out["sources"]["esptool"] = esptool, src

    mklfs, src = first([
        ("env", _env("ROZTASH_MKLITTLEFS", "ROSETASH_MKLITTLEFS") or None),
        ("bundled", plat / f"mklittlefs{exe}"),
        *[(("arduino"), Path(p)) for p in sorted(glob.glob(str(
            home / ".arduino15" / "packages" / "esp32" / "tools" / "mklittlefs"
            / "*" / f"mklittlefs{exe}")))],
        ("path", shutil.which(f"mklittlefs{exe}")),
    ])
    out["mklittlefs"], out["sources"]["mklittlefs"] = mklfs, src
    return out


def bundle_status(bundle: Path | str | None = None) -> dict:
    """وضعیت بسته برای نمایش در برنامه: نسخهٔ فریمور، فایل‌ها، ابزارها."""
    bundle = Path(bundle or bundle_dir())
    status = {"bundle": str(bundle), "present": False, "fw_version": None,
              "files": 0, "tools": {}, "error": ""}
    manifest = bundle / "manifest.json"
    if not manifest.is_file():
        status["error"] = "بستهٔ همراه پیدا نشد — tools/build_provisioner_bundle.py را اجرا کن"
        return status
    ok, doc = load_manifest(bundle)
    if not ok:
        status["error"] = doc.get("error", "بستهٔ همراه ناسازگار است")
        return status
    status["present"] = True
    status["fw_version"] = doc.get("fw_version")
    status["files"] = len(doc.get("flash", {}).get("files") or [])
    tools = find_tools(bundle=bundle)
    status["tools"] = {"esptool": tools["sources"].get("esptool"),
                       "mklittlefs": tools["sources"].get("mklittlefs")}
    status["tools_paths"] = {"esptool": tools["esptool"],
                             "mklittlefs": tools["mklittlefs"]}
    return status


# ─────────────────────────── پورت سریال ───────────────────────────

_POWERSHELL_PORTS = (
    "Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match 'COM\\d+' } "
    "| ForEach-Object { $_.Name }")


def _parse_windows_ports(text: str) -> list[dict]:
    """خط‌های PowerShell/WMI را به {port,label} تبدیل می‌کند."""
    ports, seen = [], set()
    for line in (text or "").splitlines():
        line = line.strip()
        m = re.search(r"\((COM\d+)\)", line)
        if not m:
            continue
        dev = m.group(1)
        if dev in seen:
            continue
        seen.add(dev)
        label = line[:m.start()].strip(" -(") or dev
        ports.append({"port": dev, "label": label})
    return ports


def _linux_ports(dev_root: str = "/dev") -> list[dict]:
    """پورت‌های USB-سریال لینوکس + برچسب از /dev/serial/by-id."""
    labels: dict[str, str] = {}
    for link in sorted(glob.glob(os.path.join(dev_root, "serial", "by-id", "*"))):
        try:
            real = os.path.realpath(link)
        except OSError:
            continue
        labels[real] = os.path.basename(link)
    ports, seen = [], set()
    for dev, label in list(labels.items()) + [
            (p, "") for p in
            sorted(glob.glob(os.path.join(dev_root, "ttyUSB*")))
            + sorted(glob.glob(os.path.join(dev_root, "ttyACM*")))]:
        if not os.path.exists(dev) or dev in seen:
            continue
        seen.add(dev)
        ports.append({"port": dev, "label": label or os.path.basename(dev)})
    return ports


def list_serial_ports(dev_root: str = "/dev") -> list[dict]:
    """پورت‌های سریال این سیستم — pyserial اگر بود، وگرنه ابزار بومی.

    خروجی: [{"port": "/dev/ttyUSB0" یا "COM5", "label": "توضیح"}]
    """
    ports: list[dict] = []
    try:  # pyserial بهترین گزینه است اگر نصب باشد
        from serial.tools import list_ports as slp  # type: ignore
        for p in slp.comports():
            ports.append({"port": str(p.device),
                          "label": str(p.description or p.device)})
        return sorted(ports, key=lambda d: d["port"])
    except Exception:
        pass
    if sys.platform.startswith("win"):
        res = _run(["powershell", "-NoProfile", "-Command", _POWERSHELL_PORTS], 20)
        ports = _parse_windows_ports(_text(res))
        if not ports:  # نسخهٔ ساده — فقط نام پورت‌ها
            res = _run(["powershell", "-NoProfile", "-Command",
                        "[System.IO.Ports.SerialPort]::GetPortNames()"], 15)
            ports = [{"port": l.strip(), "label": l.strip()}
                     for l in _text(res).splitlines() if l.strip()]
    elif sys.platform == "darwin":
        for pat in ("cu.usbserial*", "cu.usbmodem*", "tty.usbserial*"):
            for dev in sorted(glob.glob(os.path.join(dev_root, pat))):
                ports.append({"port": dev, "label": os.path.basename(dev)})
    else:
        ports = _linux_ports(dev_root)
    return ports


# ─────────────────────────── هویت برد ───────────────────────────


def read_chip_info(port: str, esptool: str, timeout: float = 75.0) -> tuple[bool, dict]:
    """خواندن MAC + چیپ + فلش از خود برد — «تأیید هویت» قبل از فلش.

    هر خواندن یک ری‌استارت کوتاه برد است؛ طبیعی و بی‌خطر.
    """
    res = _run([esptool, "--chip", TARGET_CHIP, "--port", str(port), "flash-id"],
               timeout)
    out = _text(res)
    doc = {"port": str(port), "mac": "", "chip": "", "flash": "",
           "log": out.strip().splitlines()[-14:], "error": ""}
    m = _MAC_RE.search(out)
    if m:
        doc["mac"] = m.group(1).lower()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Chip is "):
            doc["chip"] = line[len("Chip is "):].strip()
        elif line.startswith("Chip type:"):
            doc["chip"] = line.split(":", 1)[1].strip()
        elif line.startswith("Detected flash size:"):
            doc["flash"] = line.split(":", 1)[1].strip()
        elif not doc["flash"] and line.startswith("Flash size:"):
            doc["flash"] = line.split(":", 1)[1].strip()
    chip_text = doc["chip"].lower()
    doc["chip_id"] = TARGET_CHIP if "esp32-s3" in chip_text or "esp32s3" in chip_text else ""
    flash_mib = re.search(r"(\d+)\s*mb", doc["flash"], re.I)
    doc["flash_bytes"] = (int(flash_mib.group(1)) * 1024 * 1024
                          if flash_mib else 0)
    ok = bool(res is not None and res.returncode == 0 and m is not None
              and doc["chip"] and doc["flash"])
    if ok and doc["chip_id"] != TARGET_CHIP:
        doc["error"] = "این برد ESP32-S3 نیست؛ فریمور گیتوی فعلی برای ESP32-S3 ساخته شده"
        return False, doc
    if ok and doc["flash_bytes"] != 16 * 1024 * 1024:
        doc["error"] = "حجم فلش این برد ۱۶ مگابایت نیست؛ عملیات متوقف شد"
        return False, doc
    if not ok:
        doc["error"] = _serial_error_hint(out) or "برد پاسخ نداد — اتصال را چک کن"
        if m is None and "MAC" not in out:
            doc["mac"] = ""
    return ok, doc


def _serial_error_hint(output: str) -> str:
    """تبدیل خروجی خطای esptool به راهنمای فارسی."""
    low = output.lower()
    if "permission denied" in low or "access is denied" in low:
        return ("دسترسی به پورت باز نشد — کاربر باید عضو گروه dialout باشد "
                "(لینوکس) یا درایور CP210x نصب باشد (ویندوز)")
    if "could not open" in low and "busy" in low:
        return "پورت مشغول است — برنامهٔ دیگری (مانیتور سریال) آن را باز نگه داشته"
    if "could not open" in low:
        return "پورت باز نشد — کابل دیتادار را چک کن و یک‌بار درآور و وصل کن"
    if "failed to connect" in low or "no serial data received" in low \
            or "invalid head of packet" in low:
        return ("برد در این پورت پاسخ نداد (کابل یا پورت را چک کن) — دکمهٔ BOOT را نگه دار، "
                "یک‌بار EN را بزن، بعد دوباره «خواندن مشخصات برد» را بزن")
    if "the chip stopped responding" in low or "serial exception" in low:
        return "ارتباط سریال وسط کار قطع شد — کابل USB و پورت را عوض کن"
    return ""


# ─────────────────────────── تنظیمات و LittleFS ───────────────────────────


def validate_gw_id(gw: str) -> tuple[bool, str]:
    """قاعدهٔ شناسهٔ گیت‌وی — دقیقاً همان که پل می‌پذیرد."""
    gw = str(gw or "").strip().lower()
    if not gw:
        return False, "شناسهٔ گیت‌وی خالی است — نمونه: gw-filter-1"
    if not _GW_RE.match(gw):
        return False, ("شناسهٔ گیت‌وی فقط حروف کوچک انگلیسی، عدد، نقطه و خط تیره؛ "
                       "شروع با حرف یا عدد — نمونه: gw-filter-1")
    return True, ""


def build_config(gw_id: str, zone: str, mqtt_host: str,
                 mqtt_port: int | str = 1884,
                 health_interval_s: int | str = 600) -> dict:
    """ساخت config.json اترنت — بدون SSID/رمز؛ شبکه از W5500 و DHCP است."""
    def clip(value, limit):
        return str(value or "").strip()[:limit]

    return {
        "gw_id": clip(gw_id, _LIMITS["gw_id"]).lower(),
        "zone": clip(zone, _LIMITS["zone"]),
        "mqtt_host": clip(mqtt_host, _LIMITS["mqtt_host"]),
        "mqtt_port": int(mqtt_port or 1884),
        "health_interval_s": int(health_interval_s or 600),
        "scan_interval_ms": 160,
        "scan_window_ms": 80,
        "measure_timeout_s": 45,
    }


def config_json_text(cfg: dict) -> str:
    """متن خوانا config.json — برای پیش‌نمایش و ذخیره روی LittleFS."""
    return json.dumps(cfg, ensure_ascii=False, indent=2)


def build_littlefs(cfg: dict, out_path, mklittlefs: str,
                   workdir: str | None = None) -> tuple[bool, str]:
    """ساخت ایمج LittleFS از config.json در لحظه — برای فلش همان برد."""
    out_path = Path(out_path)
    tmp = tempfile.mkdtemp(prefix="roztash-cfg-", dir=workdir)
    try:
        (Path(tmp) / "config.json").write_text(config_json_text(cfg),
                                               encoding="utf-8")
        res = _run([mklittlefs, "-c", tmp, "-s", LITTLEFS_SIZE,
                    "-p", LITTLEFS_PAGE, str(out_path)], 60)
        if res is None or res.returncode != 0 or not out_path.is_file():
            return False, ("ساخت تصویر تنظیمات (LittleFS) ناموفق بود — "
                           "ابزار mklittlefs را چک کن")
        return True, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────── فلش کامل ───────────────────────────


def load_manifest(bundle: Path | str | None = None) -> tuple[bool, dict]:
    """خواندن manifest بسته + بررسی وجود فایل‌ها."""
    bundle = Path(bundle or bundle_dir())
    path = bundle / "manifest.json"
    if not path.is_file():
        return False, {"error": "بستهٔ همراه برنامه پیدا نشد (manifest.json)"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, {"error": f"manifest خراب است: {exc}"}
    if not isinstance(doc, dict) or not isinstance(doc.get("flash"), dict):
        return False, {"error": "ساختار manifest معتبر نیست"}
    doc["_bundle"] = str(bundle)
    flash = doc["flash"]
    if (flash.get("chip") != TARGET_CHIP
            or flash.get("size") != TARGET_FLASH_SIZE
            or doc.get("fw_version") != TARGET_FW_VERSION):
        return False, {"error": ("بستهٔ فلش قدیمی یا ناسازگار است؛ "
                                 "برای ESP32-S3 با فلش 16MB بستهٔ تازه بساز")}
    # ESP32-S3 ROM loads its bootloader at 0x0, not the legacy ESP32's 0x1000.
    expected = {
        "firmware/bootloader.bin": 0x0,
        "firmware/partitions.bin": 0x8000,
        "firmware/boot_app0.bin": 0xE000,
        "firmware/app.bin": 0x10000,
        "firmware/littlefs-blank.bin": int(LITTLEFS_OFFSET, 16),
    }
    try:
        files = flash["files"]
        actual = {item["file"]: int(item["addr"], 16) for item in files}
        if len(files) != len(expected) or actual != expected:
            return False, {"error": "فهرست یا آدرس فایل‌های فلش با ESP32-S3 سازگار نیست"}
        lfs = doc["littlefs"]
        if (int(lfs["offset"], 16) != int(LITTLEFS_OFFSET, 16)
                or lfs["size"] != int(LITTLEFS_SIZE, 16)
                or lfs["page"] != int(LITTLEFS_PAGE) or lfs["block"] != 4096):
            return False, {"error": "هندسهٔ پارتیشن تنظیمات با فریمور سازگار نیست"}
        for item in files:
            artifact = bundle / item["file"]
            if not artifact.is_file():
                return False, {"error": f"فایل بستهٔ همراه نیست: {item['file']}"}
            if (artifact.stat().st_size != item["size"]
                    or hashlib.sha256(artifact.read_bytes()).hexdigest() != item["sha256"]):
                return False, {"error": f"اندازه یا هش فایل بسته معتبر نیست: {item['file']}"}
    except (KeyError, TypeError, ValueError, OSError, AttributeError):
        return False, {"error": "اطلاعات فایل‌ها یا پارتیشن‌های manifest معتبر نیست"}
    return True, doc


def flash_command(esptool: str, port: str, entries: list[tuple[str, str]],
                  baud: int = DEFAULT_BAUD, chip: str = TARGET_CHIP,
                  flash_size: str = TARGET_FLASH_SIZE) -> list[str]:
    """ساخت فرمان write-flash متناسب با سخت‌افزار گیتوی روزتاش."""
    cmd = [str(esptool), "--chip", chip, "--port", str(port),
           "--baud", str(baud), "write-flash",
           "--flash-mode", "dio", "--flash-freq", "80m",
           "--flash-size", flash_size]
    for addr, path in entries:
        cmd += [str(addr), str(path)]
    return cmd


def progress_percent(line: str) -> int | None:
    """درصد از خط پیشرفت esptool — برای نوار پیشرفت."""
    m = _PERCENT_RE.search(line or "")
    return int(m.group(1)) if m else None


def flash_ok(output: str, returncode: int) -> bool:
    """موفقیت فلش: کد خروج صفر + خط verify هش esptool."""
    return returncode == 0 and "hash of data verified" in (output or "").lower()


def flash_gateway(port: str, cfg: dict, expected_chip: str = TARGET_CHIP,
                  expected_flash_bytes: int = 16 * 1024 * 1024,
                  expected_mac: str = "",
                  bundle: Path | str | None = None, esptool: str | None = None,
                  mklittlefs: str | None = None, baud: int = DEFAULT_BAUD,
                  progress=None, timeout: float = 900.0) -> tuple[bool, dict]:
    """فلش کامل گیتوی به‌همراه config.json همان برد روی LittleFS.

    cfg اجباری است تا هر برد با شناسه و منطقهٔ یکتا فلش شود.
    """
    info = {"log": [], "verified": False, "error": "", "returncode": None,
            "cmd": []}
    bundle = Path(bundle or bundle_dir())
    tools = find_tools(bundle=bundle)
    esptool = esptool or tools["esptool"]
    mklittlefs = mklittlefs or tools["mklittlefs"]
    if not isinstance(cfg, dict) or not cfg.get("gw_id"):
        info["error"] = "شناسهٔ گیت‌وی و تنظیمات آن اجباری است؛ فلش خالی مجاز نیست"
        return False, info
    if not esptool:
        info["error"] = ("ابزار esptool پیدا نشد — بستهٔ همراه برنامه ناقص است؛ "
                         "tools/build_provisioner_bundle.py --fetch-tools را اجرا کن")
        return False, info

    ok, board = read_chip_info(port, esptool)
    info["log"].extend(board.get("log") or [])
    if not ok:
        info["error"] = board.get("error") or "تأیید مشخصات برد ناموفق بود"
        return False, info
    if board.get("chip_id") != expected_chip:
        info["error"] = "نوع برد هنگام فلش با برد تأییدشده مطابقت ندارد"
        return False, info
    if board.get("flash_bytes") != expected_flash_bytes:
        info["error"] = "حجم فلش برد هنگام فلش تغییر کرده یا ناسازگار است"
        return False, info
    if expected_mac and board.get("mac") != expected_mac.lower():
        info["error"] = "برد متصل‌شده با MAC تأییدشده مطابقت ندارد"
        return False, info

    ok, manifest = load_manifest(bundle)
    if not ok:
        info["error"] = manifest.get("error", "بستهٔ همراه ناقص است")
        return False, info

    tmp_img = None
    lfs_rel = "firmware/littlefs-blank.bin"
    try:
        entries: list[tuple[str, str]] = []
        for item in manifest["flash"]["files"]:
            path = bundle / item["file"]
            if item["file"] == lfs_rel:
                if not mklittlefs:
                    info["error"] = "ابزار mklittlefs برای ساخت تصویر تنظیمات پیدا نشد"
                    return False, info
                tmp = Path(tempfile.mkdtemp(prefix="roztash-flash-"))
                tmp_img = tmp / "littlefs.bin"
                built, err = build_littlefs(cfg, tmp_img, mklittlefs,
                                            workdir=str(tmp))
                if not built:
                    info["error"] = err
                    return False, info
                path = tmp_img
            entries.append((str(item["addr"]), str(path)))
        entries.sort(key=lambda e: int(e[0], 16))

        cmd = flash_command(esptool, port, entries, baud)
        info["cmd"] = cmd
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace",
                                bufsize=1)
        try:
            for raw in proc.stdout or []:
                line = raw.rstrip("\n").replace("\r", "")
                if not line:
                    continue
                info["log"].append(line)
                if len(info["log"]) > 500:
                    del info["log"][0]
                if progress:
                    try:
                        progress(line)
                    except Exception:
                        pass
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            info["error"] = "فلش بیش از حد طول کشید و متوقف شد"
            return False, info
    finally:
        if tmp_img is not None:
            shutil.rmtree(tmp_img.parent, ignore_errors=True)

    out = "\n".join(info["log"])
    info["returncode"] = proc.returncode
    info["verified"] = "hash of data verified" in out.lower()
    if flash_ok(out, proc.returncode):
        return True, info
    if proc.returncode == 0:
        info["error"] = "فلش انجام شد اما تأیید هش کامل نیست؛ برد را دوباره بررسی کن"
        return False, info
    info["error"] = (_serial_error_hint(out)
                     or "فلش ناموفق بود — لاگ پایین را ببین و دوباره امتحان کن")
    return False, info
