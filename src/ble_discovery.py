"""Bounded host-side BLE discovery; never connects, pairs or writes to a band.

The authenticated bridge endpoint owns permission checks. Results may include
other BLE devices; the operator must identify and select the intended band.
"""
from __future__ import annotations
import asyncio
import os
import re
import sys

_MAC = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


async def discover_nearby(timeout_s=6.0, passive=False):
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise RuntimeError("پویشگر بلوتوث در این نسخه نصب نشده است") from exc
    options = {}
    # The HSE host may have a legacy built-in radio and a USB BLE controller.
    # On Linux the explicitly selected controller is passed to BlueZ.
    adapter = os.environ.get("ROZTASH_BLE_ADAPTER", "")
    if sys.platform.startswith("linux") and adapter:
        options["bluez"] = {"adapter": adapter}
    try:
        found = await asyncio.wait_for(BleakScanner.discover(
            timeout=max(2.0, min(float(timeout_s), 12.0)), return_adv=True,
            scanning_mode="passive" if passive else "active", **options), timeout=16.0)
    except Exception as exc:
        raise RuntimeError("اتصال رادیوی بلوتوث، پشتیبانی نقش مرکزی، روشن‌بودن Bluetooth، مجوز Windows Location/Privacy و دسترسی برنامه را بررسی کنید") from exc
    unique = {}
    for device, advertisement in (found or {}).values():
        address = (getattr(device, "address", "") or "").strip().lower()
        if not _MAC.fullmatch(address):
            continue
        name = str(getattr(advertisement, "local_name", None)
                   or getattr(device, "name", None) or "").strip()[:100]
        signal = getattr(advertisement, "rssi", None)
        rssi = int(signal) if isinstance(signal, (int, float)) and not isinstance(signal, bool) else -127
        row = unique.get(address)
        if row is None:
            unique[address] = {"mac": address, "name": name or "بدون نام", "rssi": rssi}
        else:
            row["rssi"] = max(row["rssi"], rssi)
            if row["name"] == "بدون نام" and name:
                row["name"] = name
    return sorted(unique.values(), key=lambda row: (-row["rssi"], row["mac"]))
