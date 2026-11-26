# -*- coding: utf-8 -*-
"""نماهای تشخیص و رفع مشکل شبکه سوئیچ — قابل اجرا از داخل برنامه هرMes.

این بخش از داخل هرMes اجرا می‌شود و نیاز به اجرای دستی PowerShell ندارد:
  • شناسایی کارت Ethernet ویندوز
  • تنظیم آی‌پی ثابت ۱۹۲.۱۶۸.۵۰.۱۰ روی کارت Ethernet
  • پینگ به ESP32 (۱۹۲.۱۶۸.۵۰.۱۰۰)
  • بررسی پورت‌های discovery (۱۸۸۴) و bridge (۸۷۲۶)
  • تولید فایل لاگ برای ارسال از راه دور
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import flet as ft

from theme import BORDER, DANGER, FONT, FONT_B, FONT_MED, INK, OK, TEXT_MAIN, TEXT_MUTED, WARN, WHITE, fa_clock, txt

# ثابتهای شبکه (باید با فریم‌ور ESP32 یکی باشد)
ESP32_STATIC_IP = "192.168.50.100"
WINDOWS_STATIC_IP = "192.168.50.10"
SUBNET_MASK = "255.255.255.0"
GATEWAY = "192.168.50.1"
DNS = "8.8.8.8"
DISCOVERY_PORT = 1884
BRIDGE_PORT = 8726

LOG_DIR = Path.home() / "Desktop" / "roztash_network_diag"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _log_file() -> Path:
    return LOG_DIR / f"network_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"


def _write_log(line: str, fh) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {line}"
    print(entry)
    fh.write(entry + "\n")
    fh.flush()


def _run_cmd(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    """اجرا یک دستور shell و برگشت (موفقیت، خروجی)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode == 0:
            return True, out or err
        return False, out or err or f"کد خطا {result.returncode}"
    except FileNotFoundError:
        return False, "دستور پیدا نشد"
    except subprocess.TimeoutExpired:
        return False, f"تایم‌اوت ({timeout}s)"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _get_ethernet_adapters() -> list[dict]:
    """لیست کارت‌های Ethernet فعال روی ویندوز."""
    if not _is_windows():
        return []
    ok, out = _run_cmd(["powershell", "-Command",
                        "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | "
                        "Select-Object Name, InterfaceDescription | ConvertTo-Json"])
    if not ok or not out:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return [data]
        return data
    except json.JSONDecodeError:
        return []


def _set_static_ip(adapter_name: str) -> tuple[bool, str]:
    """تنظیم آی‌پی ثابت روی کارت Ethernet ویندوز."""
    if not _is_windows():
        return False, "فقط روی ویندوز قابل اجرا است"
    ok, out = _run_cmd([
        "powershell", "-Command",
        f"New-NetIPAddress -InterfaceAlias '{adapter_name}' -IPAddress {WINDOWS_STATIC_IP} "
        f"-PrefixLength 24 -DefaultGateway {GATEWAY} -ErrorAction Stop"
    ])
    if not ok:
        return False, out
    ok2, out2 = _run_cmd([
        "powershell", "-Command",
        f"Set-DnsClientServerAddress -InterfaceAlias '{adapter_name}' -ServerAddresses {DNS}"
    ])
    if not ok2:
        return False, out2
    return True, "آی‌پی ثابت تنظیم شد"


def _ping(ip: str, count: int = 3) -> tuple[bool, str]:
    """پینگ به یک آی‌پی."""
    if _is_windows():
        cmd = ["ping", "-n", str(count), "-w", "2000", ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", "2", ip]
    ok, out = _run_cmd(cmd, timeout=15)
    return ok, out


def _check_port(ip: str, port: int, timeout: float = 3.0) -> tuple[bool, str]:
    """بررسی باز بودن یک پورت TCP."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            return True, "باز است"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def network_fix_view(app):
    """صفحه تشخیص و رفع مشکل شبکه سوئیچ."""
    state = app.state
    page = app.page

    log_output = ft.TextField(
        label="خروجی تشخیص",
        multiline=True,
        read_only=True,
        min_lines=20,
        max_lines=25,
        expand=True,
    )

    status_text = ft.Text("در انتظار اجرا…", size=13, color=TEXT_MUTED)
    result_text = ft.Text("", size=13, color=TEXT_MUTED)

    def append_log(msg: str) -> None:
        log_output.value = (log_output.value + "\n" + msg) if log_output.value else msg
        page.update()

    def run_diagnostic(e) -> None:
        log_output.value = ""
        status_text.value = "در حال اجرا…"
        status_text.color = TEXT_MUTED
        result_text.value = ""
        page.update()

        with open(_log_file(), "w", encoding="utf-8") as fh:
            _write_log("شروع تشخیص شبکه سوئیچ Roztash", fh)
            _write_log(f"سیستم عامل: {platform.system()} {platform.release()}", fh)
            _write_log(f"میزبان: {socket.gethostname()}", fh)

            # ۱. شناسایی کارت Ethernet
            _write_log("\n--- شناسایی کارت Ethernet ---", fh)
            adapters = _get_ethernet_adapters()
            if adapters:
                for a in adapters:
                    name = a.get("Name", "ناشناس")
                    desc = a.get("InterfaceDescription", "")
                    _write_log(f"کارت یافت شد: {name} — {desc}", fh)
                adapter_name = adapters[0].get("Name", "")
            else:
                _write_log("کارت Ethernet فعال پیدا نشد", fh)
                adapter_name = ""
            append_log("کارت‌های شبکه شناسایی شدند: " + (adapter_name or "هیچ"))

            # ۲. تنظیم آی‌پی ثابت
            _write_log("\n--- تنظیم آی‌پی ثابت ---", fh)
            if adapter_name:
                ok, msg = _set_static_ip(adapter_name)
                _write_log(f"تنظیم آی‌پی: {'موفق' if ok else 'ناموفق'} — {msg}", fh)
                append_log(f"تنظیم آی‌پی {WINDOWS_STATIC_IP}: {'موفق' if ok else 'ناموفق'} — {msg}")
            else:
                _write_log("کارت Ethernet پیدا نشد، تنظیم آی‌پی انجام نشد", fh)
                append_log("کارت Ethernet پیدا نشد — تنظیم آی‌پی انجام نشد")

            # ۳. پینگ به ESP32
            _write_log(f"\n--- پینگ به {ESP32_STATIC_IP} ---", fh)
            ok, out = _ping(ESP32_STATIC_IP)
            _write_log(out, fh)
            append_log(f"پینگ به {ESP32_STATIC_IP}: {'موفق' if ok else 'ناموفق'}")

            # ۴. بررسی پورت‌ها
            _write_log("\n--- بررسی پورت‌ها ---", fh)
            for port in (DISCOVERY_PORT, BRIDGE_PORT):
                ok, msg = _check_port(ESP32_STATIC_IP, port)
                _write_log(f"پورت {port}: {'باز' if ok else 'بسته'} — {msg}", fh)
                append_log(f"پورت {port}: {'باز ✓' if ok else 'بسته ✗'} ({msg})")

            # جمع‌بندی
            _write_log("\n--- جمع‌بندی ---", fh)
            ping_ok, _ = _ping(ESP32_STATIC_IP, count=1)
            port_ok_d, _ = _check_port(ESP32_STATIC_IP, DISCOVERY_PORT)
            port_ok_b, _ = _check_port(ESP32_STATIC_IP, BRIDGE_PORT)
            all_ok = ping_ok and port_ok_d and port_ok_b

            if all_ok:
                summary = "✅ شبکه آماده است — ESP32 در دسترس است"
                status_text.value = "شبکه آماده است"
                status_text.color = OK
                result_text.value = "هرMes می‌تواند با ESP32 ارتباط برقرار کند"
                result_text.color = OK
            else:
                summary = "⚠ شبکه هنوز آماده نیست — لطفاً لاگ را بررسی کنید"
                status_text.value = "شبکه آماده نیست"
                status_text.color = WARN
                result_text.value = "اتصال به ESP32 برقرار نشده است"
                result_text.color = WARN
            _write_log(summary, fh)
            append_log("\n" + summary)
            _write_log(f"فایل لاگ: {_log_file()}", fh)
            append_log(f"\nفایل لاگ ذخیره شد: {_log_file()}")
            page.update()

    def copy_log(e) -> None:
        if log_output.value:
            page.set_clipboard(log_output.value)
            page.snack_bar = ft.SnackBar(ft.Text("لاگ کپی شد"))
            page.snack_bar.open = True
            page.update()

    def open_log_folder(e) -> None:
        if _is_windows():
            os.startfile(str(LOG_DIR))
        else:
            subprocess.run(["xdg-open", str(LOG_DIR)])

    return ft.Column([
        ft.Text("تشخیص و رفع مشکل شبکه سوئیچ", size=18, weight=ft.FontWeight.BOLD, color=INK),
        ft.Text(
            "این صفحه آی‌پی کارت Ethernet ویندوز را به ۱۹۲.۱۶۸.۵۰.۱۰ تنظیم کرده و اتصال به ESP32 (۱۹۲.۱۶۸.۵۰.۱۰۰) را بررسی می‌کند.",
            size=12, color=TEXT_MUTED),
        ft.Row([
            ft.ElevatedButton("تشخیص شبکه", icon=ft.Icons.NETWORK_CHECK, on_click=run_diagnostic,
                              bgcolor=INK, color=WHITE),
            ft.ElevatedButton("باز کردن پوشهٔ لاگ", icon=ft.Icons.FOLDER, on_click=open_log_folder),
            ft.ElevatedButton("کپی لاگ", icon=ft.Icons.COPY, on_click=copy_log),
        ], spacing=10),
        ft.Divider(),
        status_text,
        result_text,
        ft.Container(
            content=log_output,
            border=ft.border.all(1, BORDER),
            border_radius=8,
            padding=10,
            expand=True,
        ),
    ], spacing=12, expand=True)
