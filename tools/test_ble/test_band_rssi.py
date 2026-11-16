#!/usr/bin/env python3
"""
تست RSSI مچ‌بند PDMB1062
اسکن BLE و نمایش قدرت سیگنال به صورت لایو
"""

import asyncio
from bleak import BleakScanner

# رنگ‌های ANSI برای نمایش بهتر
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
CYAN = '\033[96m'
RESET = '\033[0m'
BOLD = '\033[1m'


def get_rssi_color(rssi):
    """رنگ بر اساس قدرت سیگنال"""
    if rssi >= -60:
        return GREEN
    elif rssi >= -80:
        return YELLOW
    else:
        return RED


def on_advertisement(device, advertisement_data):
    """کالبک برای دریافت تبلیغات BLE"""
    # فیلتر برای مچ‌بند PDMB1062
    name = device.name or ""
    
    # نام‌های احتمالی مچ‌بند
    if any(x in name.upper() for x in ['PDMB', 'BAND', 'HEALTH', 'WRIST']) or \
       'PDMB1062' in name or device.address.upper().startswith('D4:'):
        
        rssi = advertisement_data.rssi
        color = get_rssi_color(rssi)
        
        print(f"\r{BOLD}{CYAN}[PDMB1062]{RESET} "
              f"نام: {name:20s} "
              f"آدرس: {device.address} "
              f"RSSI: {color}{rssi:>3d} dBm{RESET}  ", end='', flush=True)


async def main():
    print(f"\n{BOLD}{CYAN}═══════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  اسکن RSSI مچ‌بند PDMB1062{RESET}")
    print(f"{BOLD}{CYAN}════════════════════════════════════════════════════　　　　{RESET}")
    print(f"\n  {YELLOW}سبز{RESET}: عالی (≥-60)  |  {YELLOW}زرد{RESET}: متوسط (-60 تا -80)  |  {RED}قرمز{RESET}: ضعیف (<-80)")
    print(f"  {CYAN}آداپتور: hci0 (CSR8510 USB Dongle BLE 5.0){RESET}")
    print(f"  برای خروج Ctrl+C بزنید\n")
    
    # استفاده از دانگل USB hci0 (CSR8510 BLE 5.0) به جای پیش‌فرض BlueZ
    try:
        scanner = BleakScanner(detection_callback=on_advertisement, bluez={"adapter": "hci0"})
        await scanner.start()
        
        # منتظر بمان تا کاربر کنسل کند
        while True:
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        print(f"\n\n{GREEN}خروج از اسکن...{RESET}")
    finally:
        await scanner.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{GREEN}خداحافظ!{RESET}")
