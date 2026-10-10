#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hr_live.py — continuous heart-rate reader for Porodo PDMB1062 (Fundo/KCT).

Live-verified flow (2026-10-10):
  connect -> subscribe 4cdabaa2
  send  (02,70,[01,01])         start watch-side measurement, type 1 = HR
  dev -> (02,71,[01])           accepted (01 = ok, 00 = wearing error)
  dev -> (0A,AB,<8 bytes>)      realtime sample, payload[0] = bpm (~every 2-3s)
  dev -> (02,72,[01])           measurement finished (type 1 = HR)

Runs N measurement rounds with a pause between them, logs every sample to CSV.

Usage:
  hr_live.py --address F3:B6:D6:B7:47:D7 --rounds 3 --interval 45 \
             --csv hr_log.csv [--scan 15] [--timeout 90]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from datetime import datetime

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak is not installed in this venv")

from fundo_send import WRITE_UUID, NOTIFY_UUID, build


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


class HRReader:
    def __init__(self) -> None:
        self.samples: list[int] = []
        self.state: str = "idle"      # idle | accepted | measuring | ended | error

    def on_notify(self, _ch, data: bytearray) -> None:
        d = bytes(data)
        if len(d) < 13 or d[0] != 0xBA:
            return
        inner = d[8:]
        if len(inner) < 5:
            return
        c1, c2 = inner[0], inner[2]
        dlen = (inner[3] << 8) | inner[4]
        p = inner[5:5 + dlen]
        if (c1, c2) == (0x0A, 0xAB) and p:
            bpm = p[0]
            self.samples.append(bpm)
            self.state = "measuring"
            print(f"[{ts()}] HR {bpm} bpm    raw={' '.join(f'{b:02X}' for b in p)}",
                  flush=True)
        elif (c1, c2) == (0x02, 0x71) and p:
            ok = p[0] == 1
            self.state = "accepted" if ok else "error"
            print(f"[{ts()}] start {'ACCEPTED' if ok else 'REJECTED (wearing error?)'}",
                  flush=True)
        elif (c1, c2) == (0x02, 0x72) and p:
            self.state = "ended"
            print(f"[{ts()}] measurement ENDED (type={p[0]})", flush=True)
        elif (c1, c2) == (0x04, 0x41) and len(p) >= 2:
            print(f"[{ts()}] battery {p[0]}%", flush=True)


async def run_round(client: BleakClient, counter: int, reader: HRReader,
                    timeout_s: float) -> tuple[int, str, list[int]]:
    reader.samples.clear()
    reader.state = "idle"
    frame = build(counter, 0x02, 0x70, bytes([1, 1]))
    counter += 1
    print(f"[{ts()}] TX start HR measurement ...")
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if reader.state in ("ended", "error"):
            break
        await asyncio.sleep(0.5)
    if reader.state not in ("ended", "error"):
        print(f"[{ts()}] (round timeout after {timeout_s:.0f}s)")
    return counter, reader.state, reader.samples[:]


async def run(args) -> None:
    client = BleakClient(args.address, timeout=30.0)
    for attempt in range(1, args.retry + 1):
        if args.scan > 0:
            print(f"[{ts()}] scanning {args.scan:.0f}s for {args.address} ...")
            try:
                dev = await BleakScanner.find_device_by_address(
                    args.address, timeout=args.scan)
                print(f"[{ts()}] scan result: {dev}")
            except Exception as e:
                print(f"[{ts()}] scan error: {e}")
        print(f"[{ts()}] connect attempt {attempt}/{args.retry} ...")
        try:
            await client.connect()
            break
        except Exception as e:
            print(f"[{ts()}] connect failed: {e}")
            if attempt == args.retry:
                raise
            await asyncio.sleep(3)

    reader = HRReader()
    csv_f = open(args.csv, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_f)
    if csv_f.tell() == 0:
        writer.writerow(["timestamp", "round", "sample_index", "bpm"])
    try:
        print(f"Connected: {client.address}")
        await client.start_notify(NOTIFY_UUID, reader.on_notify)
        print(f"subscribed: {NOTIFY_UUID}")

        counter = args.start_counter
        for rnd in range(1, args.rounds + 1):
            print(f"\n===== ROUND {rnd}/{args.rounds} =====")
            counter, state, samples = await run_round(
                client, counter, reader, args.timeout)
            now = datetime.now().isoformat(timespec="seconds")
            for i, bpm in enumerate(samples):
                writer.writerow([now, rnd, i, bpm])
            csv_f.flush()
            if samples:
                avg = sum(samples) / len(samples)
                print(f"[{ts()}] ROUND {rnd} RESULT: n={len(samples)} "
                      f"avg={avg:.1f} last={samples[-1]} state={state}")
            else:
                print(f"[{ts()}] ROUND {rnd} RESULT: no samples (state={state})")
            if rnd < args.rounds:
                print(f"[{ts()}] waiting {args.interval:.0f}s before next round "
                      f"(keep the band on your wrist) ...")
                await asyncio.sleep(args.interval)
    finally:
        csv_f.close()
        try:
            await client.disconnect()
        except Exception:
            pass
    print("Done.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", required=True)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--interval", type=float, default=45.0,
                    help="pause between rounds, seconds (default 45)")
    ap.add_argument("--timeout", type=float, default=90.0,
                    help="max seconds to wait per round (default 90)")
    ap.add_argument("--csv", default="hr_log.csv")
    ap.add_argument("--scan", type=float, default=15.0)
    ap.add_argument("--retry", type=int, default=3)
    ap.add_argument("--start-counter", type=int, default=0)
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
