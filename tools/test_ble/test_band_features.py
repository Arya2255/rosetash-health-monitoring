#!/usr/bin/env python3
"""
تست ویژگی‌های BLE مچ‌بند PDMB1062
اسکن و نمایش سرویس‌ها و характеристики‌های موجود
"""

import asyncio
from bleak import BleakScanner, BleakClient

# رنگ‌های ANSI
GREEN = '\033[92m'
YELLOW = '\033[93m'
CYAN = '\033[96m'
MAGENTA = '\033[95m'
RESET = '\033[0m'
BOLD = '\033[1m'

# آدرس‌های هدف
TARGET_DEVICES = []
CONNECTED = False


def on_advertisement(device, advertisement_data):
    """کالبک برای کشف دستگاه‌ها"""
    global TARGET_DEVICES
    
    name = device.name or ""
    
    # فیلتر برای مچ‌بند PDMB1062
    if any(x in name.upper() for x in ['PDMB', 'BAND', 'HEALTH', 'WRIST']) or \
       'PDMB1062' in name or device.address.upper().startswith('D4:'):
        
        if device.address not in [d['address'] for d in TARGET_DEVICES]:
            TARGET_DEVICES.append({
                'address': device.address,
                'name': name,
                'rssi': advertisement_data.rssi
            })
            print(f"\n{GREEN}✓{RESET} کشف شد: {name} ({device.address}) RSSI: {advertisement_data.rssi} dBm")


async def explore_services(client, device_info):
    """کاوش سرویس‌ها و ویژگی‌های دستگاه"""
    print(f"\n{BOLD}{CYAN}═══════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  بررسی ویژگی‌های: {device_info['name']}{RESET}")
    print(f"{BOLD}{CYAN}══════════════════　　　　{RESET}\n")
    
    services = await client.get_services()
    
    for service in services:
        print(f"\n{MAGENTA}سرویس:{RESET} {service.uuid}")
        if service.name:
            print(f"         نام: {service.name}")
        
        for char in service.characteristics:
            props = []
            if "read" in char.properties:
                props.append("READ")
            if "write" in char.properties:
                props.append("WRITE")
            if "notify" in char.properties:
                props.append("NOTIFY")
            if "indicate" in char.properties:
                props.append("INDICATE")
            
            print(f"  {CYAN}├─{RESET} {char.uuid}")
            if char.name:
                print(f"  │  نام: {char.name}")
            print(f"  │  ویژگی‌ها: {', '.join(props)}")
            
            # تلاش برای خواندن مقدار
            if "read" in char.properties:
                try:
                    value = await client.read_gatt_char(char.uuid)
                    print(f"  │  {GREEN}مقدار:{RESET} {value.hex()}")
                except Exception as e:
                    print(f"  │  {YELLOW}(خواندن ممکن نیست){RESET}")
            
            # نمایش descriptors
            for desc in char.descriptors:
                print(f"  │  Descriptor: {desc.uuid}")


async def main():
    global CONNECTED
    
    print(f"\n{BOLD}{CYAN}═══════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}  اسکن برای کشف مچ‌بند PDMB1062 (۱۰ ثانیه){RESET}")
    print(f"{BOLD}{CYAN}════════════　　　　{RESET}\n")
    
    try:
        # مرحله ۱: کشف دستگاه‌ها
        scanner = BleakScanner(detection_callback=on_advertisement)
        await scanner.start()
        await asyncio.sleep(10)
        await scanner.stop()
        
        if not TARGET_DEVICES:
            print(f"\n{YELLOW}هیچ دستگاه PDMB1062 پیدا نشد!{RESET}")
            print("مچ‌بند را روشن کنید و مطمئن شوید در حالت جفت‌سازی است.")
            return
        
        print(f"\n{GREEN}✓{RESET} {len(TARGET_DEVICES)} دستگاه کشف شد")
        
        # مرحله ۲: اتصال و کاوش
        for device in TARGET_DEVICES[:1]:  # فقط اولین دستگاه
            print(f"\n{YELLOW}در حال اتصال به {device['address']}...{RESET}")
            
            async with BleakClient(device['address']) as client:
                if await client.is_connected():
                    print(f"{GREEN}✓ متصل شد!{RESET}")
                    CONNECTED = True
                    await explore_services(client, device)
                    
    except KeyboardInterrupt:
        print(f"\n{YELLOW}لغو شد{RESET}")
    except Exception as e:
        print(f"\n{RED}خطا: {e}{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
