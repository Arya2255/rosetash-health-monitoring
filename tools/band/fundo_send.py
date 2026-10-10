#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fundo_send.py — FunDo/KCT band protocol talker (Porodo PDMB1062).

Frame format reverse-engineered from the app's own SDK and VERIFIED against
live notification captures (CRC16 matched on real frames):

  OUTER:  BA | 21 | len_hi len_lo | crc_hi crc_lo | seq0 seq1 | INNER
  INNER:  cmd1 | 00 | cmd2 | dlen_hi dlen_lo | payload...
  len    = length of INNER
  crc16  = oi.f.u() from the SDK (validated): init 0xFFFF, per byte:
             x  = ((i << 8) | (i >> 8)) & 0xFFFF  ^  byte
             x ^= (x & 0xFF) >> 4
             x ^= (x << 12) & 0xFFFF
             i  = (x ^ ((x & 0xFF) << 5)) & 0xFFFF

Modes
-----
  listen                subscribe + decode notifications for --listen seconds
  send --cmd "C1 C2 [payload hex]" ...   connect once, send the commands
                        spaced --gap seconds apart, decode everything

Known command pairs (from static analysis of the app):
  A6 05   start/stop realtime report  (candidate!)
  A7 1F   command sent after connect/pairing
  A7 37   auto-HR schedule: [enable, sh, sm, eh, em, interval]
  02 70   watch active measurement: [0/1, type]
  02 20   time sync [yy-2000, month, day, hh, mm, ss, flags, tz*2]
  device -> app:  04 41 battery [pct, state]
  device -> app:  A6 AB realtime HR push (bpm)   <<< target
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    sys.exit("bleak is not installed in this venv")

WRITE_UUID = "4cdabaa1-2cea-c0c1-b38d-a0481ae60a97"
NOTIFY_UUID = "4cdabaa2-2cea-c0c1-b38d-a0481ae60a97"


def crc16(data: bytes) -> int:
    i = 0xFFFF
    for b in data:
        x = ((((i << 8) & 0xFFFF) | ((i >> 8) & 0xFF)) ^ (b & 0xFF)) & 0xFFFF
        x ^= (((x & 0xFF) >> 4) & 0xFFFF)
        x ^= ((x << 12) & 0xFFFF)
        i = (x ^ (((x & 0xFF) << 5) & 0xFFFF)) & 0xFFFF
    return i


def build(counter: int, cmd1: int, cmd2: int, payload: bytes = b"") -> bytes:
    inner = bytes([cmd1 & 0xFF, 0x00, cmd2 & 0xFF,
                   (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload
    crc = crc16(inner)
    h = f"{counter:x}"
    if len(h) % 2:
        h = "0" + h
    sb = bytes.fromhex(h)
    if len(sb) == 1:
        seq = bytes([0, sb[0]])
    elif len(sb) == 2:
        seq = bytes([sb[1], sb[0]])
    else:
        seq = sb[-2:]
    return bytes([0xBA, 0x21,
                  (len(inner) >> 8) & 0xFF, len(inner) & 0xFF,
                  (crc >> 8) & 0xFF, crc & 0xFF]) + seq + inner


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hexs(d: bytes) -> str:
    return " ".join(f"{b:02X}" for b in d)


def decode(data: bytes) -> str:
    if len(data) < 8 or data[0] != 0xBA:
        return "  (not a FunDo frame)"
    inner = data[8:]
    ilen = (data[2] << 8) | data[3]
    crc_ok = crc16(inner) == ((data[4] << 8) | data[5])
    if len(inner) >= 5:
        c1, _mid, c2 = inner[0], inner[1], inner[2]
        dlen = (inner[3] << 8) | inner[4]
        payload = inner[5:5 + dlen]
        tag = f"  cmd=({c1:02X},{c2:02X}) len={dlen} data={hexs(payload)}"
        if (c1, c2) == (0x04, 0x41) and len(payload) >= 2:
            tag += f"   [BATTERY {payload[0]}% state={payload[1]}]"
        elif (c1, c2) == (0xA6, 0xAB) and payload:
            tag += f"   [REALTIME HR = {payload[0]} bpm]"
        elif (c1, c2) == (0xA6, 0xAC) and len(payload) >= 3:
            steps = payload[0] | (payload[1] << 8) | (payload[2] << 16)
            tag += f"   [steps={steps}]"
    else:
        tag = "  (short inner)"
    return f"  inner_len={ilen} crc={'OK' if crc_ok else 'BAD'}{tag}"


async def run(args):
    cmds = []
    for spec in (args.cmd or []):
        parts = spec.split()
        if len(parts) < 2:
            sys.exit(f"bad --cmd spec: {spec!r} (need 'C1 C2 [payload...]')")
        c1, c2 = int(parts[0], 16), int(parts[1], 16)
        payload = bytes.fromhex("".join(parts[2:])) if len(parts) > 2 else b""
        cmds.append((c1, c2, payload))

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
    try:
        print(f"Connected: {client.address}")

        def on_notify(_ch, data: bytearray):
            d = bytes(data)
            print(f"[{ts()}] RX {hexs(d)}")
            print(f"          {decode(d)}", flush=True)

        await client.start_notify(NOTIFY_UUID, on_notify)
        print(f"subscribed: {NOTIFY_UUID}")

        counter = args.start_counter
        elapsed = 0.0
        for c1, c2, payload in cmds:
            frame = build(counter, c1, c2, payload)
            counter += 1
            print(f"[{ts()}] TX {hexs(frame)}   <= ({c1:02X},{c2:02X}) "
                  f"payload={hexs(payload)}")
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
            print(f"          waiting {args.gap:.0f}s ...", flush=True)
            await asyncio.sleep(args.gap)
            elapsed += args.gap

        tail = args.listen - elapsed
        if tail > 0:
            print(f"Done sending. Listening {tail:.0f}s more ...")
            await asyncio.sleep(tail)
    finally:
        await client.disconnect()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", required=True)
    ap.add_argument("--cmd", action="append", default=[],
                    help="command spec, e.g. \"A6 05\" or \"A7 37 01 08 00 17 00 3C\"")
    ap.add_argument("--gap", type=float, default=15.0,
                    help="seconds between commands (default 15)")
    ap.add_argument("--listen", type=float, default=40.0,
                    help="total listen time (default 40)")
    ap.add_argument("--scan", type=float, default=0.0,
                    help="scan this many seconds before connecting (default 0)")
    ap.add_argument("--retry", type=int, default=3,
                    help="connect attempts (default 3)")
    ap.add_argument("--start-counter", type=int, default=0)
    args = ap.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
