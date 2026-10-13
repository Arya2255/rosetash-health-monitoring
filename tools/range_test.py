#!/usr/bin/env python3
"""Range test logger -- record band RSSI/presence from the live bridge to CSV.

Run while walking around with the band (bridge must be up):

    python3 tools/range_test.py --out baseline.csv

One row per second: ts, band_seen, rssi, gw_online, health_state.
Ctrl+C stops; a summary prints (percent seen, rssi min/avg/max).
Compare "before" and "after" runs (e.g. antenna upgrade) at fixed spots.
"""
import argparse
import csv
import json
import time
import urllib.request
from datetime import datetime


def fetch_snapshot(url, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description="Log band RSSI/presence to CSV via the live bridge.")
    ap.add_argument("--out", default="range_test.csv", help="output CSV path")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between samples")
    ap.add_argument("--mac", default="", help="only track this band MAC (default: first seen)")
    ap.add_argument("--url", default="http://127.0.0.1:8726/api/snapshot")
    args = ap.parse_args()

    rows = 0
    seen = 0
    rssis = []
    print("logging to %s -- Ctrl+C to stop" % args.out)
    try:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts", "band_seen", "rssi", "gw_online", "health_state"])
            while True:
                ts = datetime.now().isoformat(timespec="seconds")
                try:
                    snap = fetch_snapshot(args.url)
                except Exception as e:
                    w.writerow([ts, "bridge_down", "", "", str(e)])
                    f.flush()
                    print("\r%s  bridge down: %s" % (ts, e))
                    time.sleep(args.interval)
                    continue
                band = None
                for item in snap.get("bands") or []:
                    if not args.mac or item.get("mac") == args.mac:
                        band = item
                        break
                gw_on = any(g.get("online") for g in snap.get("gateways") or [])
                health = ""
                hlist = snap.get("health") or []
                if hlist:
                    health = hlist[0].get("state", "") or ""
                if band is not None:
                    r = band.get("rssi")
                    rdisp = str(r) if r is not None else "-"
                    w.writerow([ts, 1, r, int(gw_on), health])
                    seen += 1
                    if isinstance(r, (int, float)):
                        rssis.append(float(r))
                else:
                    rdisp = "-"
                    w.writerow([ts, 0, "", int(gw_on), health])
                rows += 1
                f.flush()
                print("\r%s  seen=%d  rssi=%5s  samples=%d   " %
                      (ts, 1 if band else 0, rdisp, rows), end="")
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    print()
    if rows:
        pct = 100.0 * seen / rows
        if rssis:
            print("samples=%d  seen=%d (%.1f%%)  rssi min/avg/max = %.0f / %.1f / %.0f" %
                  (rows, seen, pct, min(rssis), sum(rssis) / len(rssis), max(rssis)))
        else:
            print("samples=%d  seen=%d (%.1f%%)  -- no rssi samples" % (rows, seen, pct))
    else:
        print("no samples recorded")


if __name__ == "__main__":
    main()
