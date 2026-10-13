#!/usr/bin/env python3
"""Band distance calibration system - precise distance measurement for BLE bands.

Usage:
    # Start calibration mode - record RSSI at various distances
    python3 tools/band_distance.py --calibrate
    
    # Measure distance in real-time using saved calibration
    python3 tools/band_distance.py

The calibration system:
1. Records RSSI samples at known distances (1m, 2m, 3m, etc.)
2. Builds a path-loss model: RSSI = P_tx - 10*n*log10(d) + noise
3. Uses the model to estimate distance from RSSI
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import numpy as np

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


BRIDGE_URL = os.environ.get("ROZTASH_BRIDGE_URL", "http://127.0.0.1:8726")
CALIBRATION_FILE = PROJECT_ROOT / "tools" / "band" / "distance_calibration.json"


def fetch_snapshot(url=f"{BRIDGE_URL}/api/snapshot", timeout=3.0):
    """Fetch snapshot from bridge."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def load_calibration():
    """Load saved calibration data."""
    if CALIBRATION_FILE.exists():
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    return {"samples": [], "model": None, "measured_power": -82, "path_loss": 2.5}


def save_calibration(data):
    """Save calibration data."""
    CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def rssi_to_distance(rssi, measured_power=-82, path_loss=2.5):
    """Convert RSSI to distance using Log-distance path loss model.
    
    Formula: d = 10 ^ ((P_tx - RSSI) / (10 * n))
    
    Args:
        rssi: Received signal strength in dBm
        measured_power: RSSI at 1 meter (calibrated: -82 for PDMB1062)
        path_loss: Path loss exponent (2.0 free space, 2.5 indoor)
    
    Returns:
        Estimated distance in meters
    """
    if rssi is None or rssi >= 0:
        return None
    
    try:
        distance = math.pow(10, (measured_power - rssi) / (10 * path_loss))
        return max(0.1, min(distance, 100))  # Clamp to reasonable range
    except (ValueError, OverflowError):
        return None


def distance_to_rssi(distance, measured_power=-82, path_loss=2.5):
    """Convert distance to expected RSSI (for calibration)."""
    if distance <= 0:
        return None
    return measured_power - 10 * path_loss * math.log10(distance)


def build_model_from_samples(samples):
    """Build calibration model from recorded samples.
    
    samples: list of {"distance": float, "rssi": float}
    Returns: {"measured_power": float, "path_loss": float, "std_error": float}
    """
    if len(samples) < 2:
        return None
    
    distances = np.array([s["distance"] for s in samples])
    rssis = np.array([s["rssi"] for s in samples])
    
    # Use log-distance path loss model
    # RSSI = P_tx - 10 * n * log10(d)
    # Rearranged: RSSI - P_tx = -10 * n * log10(d)
    # Let y = RSSI, x = log10(d), fit: y = P_tx + slope * x
    
    log_distances = np.log10(distances)
    
    # Linear regression
    n = len(distances)
    sum_x = np.sum(log_distances)
    sum_y = np.sum(rssis)
    sum_xy = np.sum(log_distances * rssis)
    sum_xx = np.sum(log_distances * log_distances)
    
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x * sum_x)
    intercept = (sum_y - slope * sum_x) / n
    
    # slope = -10 * n, so n = -slope / 10
    path_loss = -slope / 10
    measured_power = intercept
    
    # Calculate standard error
    predictions = intercept + slope * log_distances
    residuals = rssis - predictions
    std_error = np.std(residuals)
    
    return {
        "measured_power": float(measured_power),
        "path_loss": float(path_loss),
        "std_error": float(std_error),
        "sample_count": len(samples)
    }


def format_distance(d):
    """Format distance nicely."""
    if d is None:
        return "---"
    if d < 1:
        return f"{d*100:.0f}cm"
    elif d < 10:
        return f"{d:.1f}m"
    else:
        return f"{d:.0f}m"


def format_rssi(rssi):
    """Color-coded RSSI."""
    if rssi is None:
        return "---"
    if rssi >= -50:
        return f"🟢 {rssi}"
    elif rssi >= -60:
        return f"🟡 {rssi}"
    elif rssi >= -70:
        return f"🟠 {rssi}"
    elif rssi >= -80:
        return f"🔴 {rssi}"
    else:
        return f"⚫ {rssi}"


def find_bands(snap):
    """Find all bands in snapshot."""
    return snap.get("bands", [])


def calibrate_mode(args):
    """Interactive calibration mode."""
    cal_data = load_calibration()
    samples = cal_data.get("samples", [])
    
    print("=" * 60)
    print("📏 کالیبراسیون فاصله مچ‌بند")
    print("=" * 60)
    print("هدف: ثبت RSSI در فاصله‌های مشخص برای ساخت مدل دقیق")
    print()
    print("دستورالعمل:")
    print("  1. مچ‌بند را در فاصله مشخصی (مثل ۱ متر) قرار دهید")
    print("  2. دستور 'record <distance>' را وارد کنید (مثل: record 1)")
    print("     سیستم چند ثانیه RSSI نمونه‌برداری می‌کند")
    print("  3. فاصله را عوض کنید و دوباره record کنید (۲، ۳، ۵ متر...)")
    print("  4. بعد از حداقل ۲ فاصله، 'build' بزنید تا مدل ساخته شود")
    print("  5. با 'save' ذخیره و با 'exit' خروج")
    print()
    print("فاصله‌های پیشنهادی: 0.5m, 1m, 2m, 3m, 5m, 8m, 10m")
    print()
    
    if samples:
        print(f"📊 نمونه‌های ثبت‌شده: {len(samples)}")
        for s in samples:
            print(f"   {s['distance']}m → RSSI: {s['rssi']:.1f}")
        print()
    
    if cal_data.get("model"):
        m = cal_data["model"]
        print(f"✅ مدل فعال: P_tx={m['measured_power']:.1f} dBm, n={m['path_loss']:.2f}")
        print(f"   خطای استاندارد: ±{m['std_error']:.1f} dBm")
    else:
        print("⚠️ مدل کالیبراسیون وجود ندارد")
    print()
    
    record_buffer = []
    
    while True:
        try:
            cmd = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n\n⏹️ خروج")
            break
        
        if not cmd:
            continue
            
        parts = cmd.split()
        action = parts[0]
        
        if action == "help":
            print("""
دستورات:
  record <distance>  - ثبت نمونه در فاصله مشخص (مثل: record 1)
  build              - ساخت مدل از نمونه‌ها
  save               - ذخیره مدل در فایل
  clear              - پاک کردن همه نمونه‌ها
  list               - نمایش نمونه‌ها
  info               - نمایش مدل فعلی
  exit               - خروج
            """)
            
        elif action == "record":
            if len(parts) < 2:
                print("❌用法: record <distance>")
                continue
            try:
                distance = float(parts[1].replace(',', '.'))
            except ValueError:
                print("❌ فاصله باید عدد باشد")
                continue
                
            print(f"📡 نمونه‌برداری از RSSI در فاصله {distance}m...")
            print("   ۱۰ ثانیه صبر کنید یا Ctrl+C برای قطع")
            
            rssi_samples = []
            start_time = time.time()
            
            try:
                while time.time() - start_time < 10:
                    try:
                        snap = fetch_snapshot()
                        bands = find_bands(snap)
                        if bands:
                            rssi = bands[0].get("rssi")
                            if rssi is not None:
                                rssi_samples.append(rssi)
                                print(f"\r   نمونه: {rssi} dBm     ", end="")
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"\n   خطا: {e}")
            except KeyboardInterrupt:
                pass
            
            if rssi_samples:
                avg_rssi = sum(rssi_samples) / len(rssi_samples)
                samples.append({"distance": distance, "rssi": avg_rssi, "time": datetime.now().isoformat()})
                cal_data["samples"] = samples
                print(f"\n✅ ثبت شد: {distance}m → میانگین RSSI: {avg_rssi:.1f} dBm ({len(rssi_samples)} نمونه)")
            else:
                print("\n❌ هیچ نمونه‌ای دریافت نشد - مچ‌بند در دید نیست")
        
        elif action == "build":
            if len(samples) < 2:
                print("❌ حداقل ۲ نمونه لازم است")
                continue
                
            model = build_model_from_samples(samples)
            if model:
                cal_data["model"] = model
                print(f"""
✅ مدل ساخته شد:
   توان اندازه‌گیری (P_tx): {model['measured_power']:.1f} dBi
   تلفات مسیر (n): {model['path_loss']:.2f}
   خطای استاندارد: ±{model['std_error']:.1f} dBm
   تعداد نمونه‌ها: {model['sample_count']}
                """)
            else:
                print("❌ خطا در ساخت مدل")
        
        elif action == "save":
            save_calibration(cal_data)
            print("💾 ذخیره شد")
        
        elif action == "clear":
            samples.clear()
            cal_data["samples"] = []
            cal_data["model"] = None
            print("🗑️ پاک شد")
        
        elif action == "list":
            if not samples:
                print("هیچ نمونه‌ای نیست")
            for i, s in enumerate(samples):
                print(f"  {i+1}. {s['distance']}m → {s['rssi']:.1f} dBm")
        
        elif action == "info":
            if cal_data.get("model"):
                m = cal_data["model"]
                print(f"""مدل فعلی:
  P_tx = {m['measured_power']:.1f} dBm
  n = {m['path_loss']:.2f}
  خطا = ±{m['std_error']:.1f} dBm
  نمونه‌ها = {m['sample_count']}
                """)
            else:
                print("مدلی وجود ندارد")
        
        elif action == "exit":
            break
        
        else:
            print(f"❓ دستور ناشناس: {action}")
    
    # Offer to save before exit
    if samples:
        save_calibration(cal_data)
        print("\n💾 داده‌ها ذخیره شد")


def measure_mode(args):
    """Real-time distance measurement."""
    cal_data = load_calibration()
    model = cal_data.get("model")
    
    # Settings
    measured_power = model.get("measured_power", -59) if model else -59
    path_loss = model.get("path_loss", 2.5) if model else 2.5
    
    if not model:
        print("⚠️ هشدار: مدل کالیبراسیون وجود ندارد - از مقادیر پیش‌فرض استفاده می‌شود")
        print("   برای کالیبراسیون: python3 tools/band_distance.py --calibrate")
        print()
    
    print("=" * 60)
    print("📏 سنجش فاصله زنده مچ‌بند")
    print("=" * 60)
    print(f"Bridge: {BRIDGE_URL}")
    print(f"مدل: P_tx={measured_power} dBm, n={path_loss}")
    if model:
        print(f"خطا: ±{model['std_error']:.1f} dBm")
    print("-" * 60)
    print("Press Ctrl+C to stop")
    print("-" * 60)
    
    # History for smoothing
    rssi_history = defaultdict(list)
    max_history = 5
    
    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            
            try:
                snap = fetch_snapshot()
            except Exception as e:
                print(f"\r[{ts}] ❌ Bridge unreachable: {e}")
                time.sleep(1)
                continue
            
            bands = find_bands(snap)
            
            if not bands:
                print(f"\r[{ts}] 🔍 جستجوی مچ‌بند...", end="")
                time.sleep(1)
                continue
            
            for band in bands:
                mac = band.get("mac", "?")
                rssi = band.get("rssi")
                gw = band.get("gw", "")
                
                if rssi is None:
                    continue
                
                # Add to history for smoothing
                rssi_history[mac].append(rssi)
                if len(rssi_history[mac]) > max_history:
                    rssi_history[mac].pop(0)
                
                # Average RSSI for smoother reading
                avg_rssi = sum(rssi_history[mac]) / len(rssi_history[mac])
                
                # Calculate distance
                distance = rssi_to_distance(avg_rssi, measured_power, path_loss)
                
                # Format output
                dist_str = format_distance(distance)
                rssi_str = format_rssi(avg_rssi)
                
                mac_short = mac[-8:] if len(mac) > 8 else mac
                
                print(f"\r[{ts}] {mac_short} | RSSI: {rssi_str} | فاصله: {dist_str} |Gw: {gw}")
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n\n👋 متوقف شد")


def main():
    ap = argparse.ArgumentParser(description="Band distance calibration and measurement.")
    ap.add_argument("--calibrate", "-c", action="store_true",
                    help="Enter calibration mode")
    ap.add_argument("--interval", "-i", type=float, default=0.5,
                    help="Update interval in seconds (default: 0.5)")
    ap.add_argument("--reset", "-r", action="store_true",
                    help="Reset calibration data")
    args = ap.parse_args()
    
    if args.reset:
        cal = load_calibration()
        cal["samples"] = []
        cal["model"] = None
        save_calibration(cal)
        print("✅ کالیبراسیون ریست شد")
        return
    
    if args.calibrate:
        calibrate_mode(args)
    else:
        measure_mode(args)


if __name__ == "__main__":
    main()