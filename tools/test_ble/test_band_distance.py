#!/usr/bin/env python3
"""
تست فاصله مچ‌بند PDMB1062
محاسبه فاصله تقریبی بر اساس RSSI
"""

import asyncio
import math
from bleak import BleakScanner

# رنگ‌های ANSI
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
CYAN = '\033[96m'
MAGENTA = '\033[95m'
RESET = '\033[0m'
BOLD = '\033[1m'

# پارامترهای محاسبه فاصله
TX_POWER = -59  # قدرت سیگنال در ۱ متر (معمولاً -59)
PATH_LOSS_EXPONENT = 2.0  # تعدیل‌کننده محیط (۲=فضای آزاد)


def calculate_distance(rssi):
    """
    محاسبه فاصله تقریبی از RSSI
    فرمول: distance = 10 ^ ((txPower - rssi) / (10 * N))
    """
    if rssi == 0:
        return -1
    
    ratio = (TX_POWER - rssi) / (10 * PATH_LOSS_EXPONENT)
    distance = math.pow(10, ratio)
    return distance


def get_distance_quality(distance):
    """رنگ بر اساس فاصله"""
    if distance <= 2:
        return GREEN, "عالی"
    elif distance <= 5:
        return CYAN, "خوب"
    elif distance <= 10:
        return YELLOW, "متوسط"
    else:
        return RED, "ضعیف"


def on_advertisement(device, advertisement_data):
    """کالبک برای دریافت تبلیغات BLE"""
    name = device.name or ""
    
    # فیلتر برای مچ‌بند PDMB1062
    if any(x in name.upper() for x in ['PDMB', 'BAND', 'HEALTH', 'WRIST']) or \
       'PDMB1062' in name or device.address.upper().startswith('D4:'):
        
        rssi = advertisement_data.rssi
        distance = calculate_distance(rssi)
        color, quality = get_distance_quality(distance)
        
        # نمایش نوار پیشرفت فاصله
        max_bar = 20
        bar_len = min(max_bar, int(distance * 2))
        bar = '█' * bar_len + '░' * (max_bar - bar_len)
        
        print(f"\r{BOLD}{MAGENTA}[PDMB1062]{RESET} "
              f"نام: {name[:15]:15s} "
              f"RSSI: {rssi:>3d} dBm | "
              f"فاصله: {color}{distance:>5.1f}m{RESET} "
              f"[{bar}] {color}{quality}{RESET}  ", end='', flush=True)


async def main():
    print(f"\n{BOLD}{CYAN}═══════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  تخمین فاصله مچ‌بند PDMB1062 از RSSI{RESET}")
    print(f"{BOLD}{CYAN}══════════════════════　　　　{RESET}")
    print(f"\n  {GREEN}عالی{RESET}: <2m  |  {CYAN}خوب{RESET}: 2-5m  |  {YELLOW}متوسط{RESET}: 5-10m  |  {RED}ضعیف{RESET}: >10m")
    print(f"  برای خروج Ctrl+C بزنید\n")
    
    try:
        scanner = BleakScanner(detection_callback=on_advertisement)
        await scanner.start()
        
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
