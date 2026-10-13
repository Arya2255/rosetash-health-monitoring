#!/usr/bin/env python3
"""Real-time RSSI monitor with Kalman filter for BLE bands"""

import asyncio
import sys
import math
from datetime import datetime
from bleak import BleakScanner

TARGET_ADDR = "F3:B6:D6:B7:47:D7"  # PDMB1062
TARGET_NAME = "PDMB1062"

# Calibration: measured at ~1m
TX_POWER = -82  # Measured RSSI at 1 meter
PATH_LOSS_EXPONENT = 2.5  # Indoor path loss


class KalmanFilter:
    """1D Kalman filter for RSSI smoothing"""
    def __init__(self, initial_value=-70, process_noise=2, measurement_noise=5, estimation_error=5):
        self.q = process_noise
        self.r = measurement_noise
        self.p = estimation_error
        self.x = initial_value
        
    def update(self, measurement):
        self.p = self.p + self.q
        k = self.p / (self.p + self.r)
        self.x = self.x + k * (measurement - self.x)
        self.p = (1 - k) * self.p
        return self.x


def rssi_to_distance(rssi, tx_power=TX_POWER, n=PATH_LOSS_EXPONENT):
    """RSSI to distance using calibrated log-distance model"""
    if rssi >= 0:
        return None
    try:
        distance = 10 ** ((tx_power - rssi) / (10 * n))
        return max(0.1, min(distance, 100))
    except:
        return None


async def monitor(interval=2.0):
    """Continuously monitor with Kalman filter"""
    kalman = KalmanFilter(initial_value=-70, process_noise=2, measurement_noise=5)
    
    print(f"🌊 RSSI Monitor with Kalman Filter (Calibrated)")
    print(f"   Config: TX_POWER={TX_POWER}, n={PATH_LOSS_EXPONENT}")
    print("=" * 50)
    print(f"{'Time':<8} {'Raw':>8} {'Filtered':>10} {'Distance':>12}")
    print("-" * 50)
    
    reading_count = 0
    
    while True:
        try:
            devices = await BleakScanner.discover(timeout=5, filter_duplicates=False)
            
            found = False
            for d in devices:
                if d.address.upper() == TARGET_ADDR.upper():
                    raw_rssi = d.details['props'].get('RSSI', 0) if d.details else 0
                    found = True
                    reading_count += 1
                    
                    # Apply Kalman
                    filtered_rssi = kalman.update(raw_rssi)
                    
                    # Calculate distance
                    distance = rssi_to_distance(filtered_rssi)
                    
                    ts = datetime.now().strftime("%H:%M:%S")
                    dist_str = f"{distance:.2f}m" if distance else "N/A"
                    
                    print(f"{ts:<8} {raw_rssi:>8} dBm {filtered_rssi:>10.1f} {dist_str:>12}")
                    break
            
            if not found:
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"{ts:<8} {'...searching for device':>30}")
            
            await asyncio.sleep(interval)
            
        except KeyboardInterrupt:
            print("\n⏹ Stopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(interval)


if __name__ == "__main__":
    interval = 2.0
    if len(sys.argv) > 1:
        try:
            interval = float(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [interval_seconds]")
            sys.exit(1)
    
    asyncio.run(monitor(interval))