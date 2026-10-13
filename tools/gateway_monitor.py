#!/usr/bin/env python3
"""Gateway monitor - find and monitor gateway connected to phone in real-time.

Usage:
    python3 tools/gateway_monitor.py

Shows:
    - All gateways from bridge API
    - Real-time RSSI, online status, presence count
    - Gateway connected to phone (if detectable)
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


BRIDGE_URL = os.environ.get("ROZTASH_BRIDGE_URL", "http://127.0.0.1:8726")


def fetch_snapshot(url=f"{BRIDGE_URL}/api/snapshot", timeout=3.0):
    """Fetch snapshot from bridge."""
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def format_rssi(rssi):
    """Color-coded RSSI display."""
    if rssi is None:
        return "---"
    if rssi >= -50:
        return f"🟢 {rssi}"  # Excellent
    elif rssi >= -60:
        return f"🟡 {rssi}"  # Good
    elif rssi >= -70:
        return f"🟠 {rssi}"  # Fair
    elif rssi >= -80:
        return f"🔴 {rssi}"  # Weak
    else:
        return f"⚫ {rssi}"  # Very weak


def format_uptime(seconds):
    """Format uptime nicely."""
    if seconds is None:
        return "?"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h{mins}m"
    elif mins > 0:
        return f"{mins}m{secs}s"
    else:
        return f"{secs}s"


def find_phone_gateway(snap):
    """Try to detect which gateway phone is connected to.
    
    This requires the bridge to track MQTT messages from phone app,
    or we can infer from gateway that recently published presence.
    """
    gateways = snap.get("gateways", [])
    
    # Gateway with most recent activity might be the one phone uses
    # In a real scenario, phone app sends data to specific gateway
    online_gateways = [g for g in gateways if g.get("online")]
    if online_gateways:
        # Sort by last_seen or adv_seen (advertisement count)
        most_active = max(online_gateways, key=lambda g: g.get("adv_seen", 0))
        return most_active.get("gw")
    return None


def main():
    ap = argparse.ArgumentParser(description="Monitor gateway(s) in real-time.")
    ap.add_argument("--gateway", "-g", default="", 
                    help="Filter to specific gateway ID (e.g., gw-test-1)")
    ap.add_argument("--interval", "-i", type=float, default=1.0,
                    help="Update interval in seconds (default: 1.0)")
    ap.add_argument("--json", "-j", action="store_true",
                    help="Output JSON format")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Show detailed information")
    args = ap.parse_args()

    print("=" * 60)
    print("🔌 Gateway Monitor")
    print("=" * 60)
    print(f"Bridge: {BRIDGE_URL}")
    print(f"Update: {args.interval}s")
    if args.gateway:
        print(f"Filter: {args.gateway}")
    print("-" * 60)
    print("Press Ctrl+C to stop")
    print("-" * 60)
    
    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")
            
            try:
                snap = fetch_snapshot()
            except Exception as e:
                print(f"\r[{ts}] ❌ Bridge unreachable: {e}")
                time.sleep(args.interval)
                continue

            gateways = snap.get("gateways", [])
            
            # Filter if specific gateway requested
            if args.gateway:
                gateways = [g for g in gateways if g.get("gw") == args.gateway]
            
            if not gateways:
                print(f"\r[{ts}] No gateways found")
                time.sleep(args.interval)
                continue

            # Try to detect phone gateway
            phone_gw = find_phone_gateway(snap)
            
            if args.json:
                # JSON output
                print(json.dumps({
                    "timestamp": ts,
                    "gateways": gateways,
                    "phone_gateway": phone_gw
                }, ensure_ascii=False))
            else:
                # Human-readable
                lines = []
                for gw in gateways:
                    gw_id = gw.get("gw", "?")
                    online = gw.get("online", False)
                    rssi = gw.get("rssi")
                    uptime = gw.get("uptime_s")
                    adv_seen = gw.get("adv_seen", 0)
                    zone = gw.get("zone", "")
                    fw = gw.get("fw", "")
                    ip = gw.get("ip", "")
                    
                    # Status indicator
                    status = "🟢 آنلاین" if online else "⚫ آفلاین"
                    phone_indicator = " 📱" if gw_id == phone_gw else ""
                    
                    line = f"[{ts}] {gw_id}{phone_indicator}: {status}"
                    line += f" | RSSI: {format_rssi(rssi)}"
                    line += f" | Uptime: {format_uptime(uptime)}"
                    
                    if args.verbose:
                        line += f" | Zone: {zone}"
                        line += f" | FW: {fw}"
                        line += f" | IP: {ip}"
                        line += f" | Adv: {adv_seen:,.0f}"
                    
                    lines.append(line)
                
                # Print all on separate lines, then clear
                output = "\n".join(lines)
                # Pad with spaces to clear previous longer output
                pad = " " * 40
                print(f"\r{output}{pad}\r", end="")
                # New line for first item
                if len(lines) > 0:
                    print()
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n\n👋 Stopped")


if __name__ == "__main__":
    main()