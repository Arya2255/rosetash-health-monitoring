#!/usr/bin/env python3
"""Clean boot-capture for the Roztash gateway board (stdlib only).

One process, one open fd: sets raw mode 115200, performs a hardware reset
via the auto-reset circuit (RTS -> EN), then streams the UART for ~22 s
with chunk timestamps. No baud changes mid-stream, no external tools.
"""
import fcntl
import os
import select
import struct
import sys
import termios
import time

PORT = "/dev/ttyUSB0"
OUT = sys.argv[1] if len(sys.argv) > 1 else "serial_boot.log"

fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

attrs = termios.tcgetattr(fd)
iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
iflag = 0
oflag = 0
lflag = 0
cflag = termios.CREAD | termios.CLOCAL | termios.CS8
ispeed = ospeed = termios.B115200
cc[termios.VMIN] = 0
cc[termios.VTIME] = 0
termios.tcsetattr(fd, termios.TCSANOW,
                  [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])


def set_modem_bits(bits, on):
    op = termios.TIOCMBIS if on else termios.TIOCMBIC
    fcntl.ioctl(fd, op, struct.pack("I", bits))


# Hardware reset via the two-transistor auto-reset circuit:
set_modem_bits(termios.TIOCM_DTR, False)   # IO0 high -> normal boot
set_modem_bits(termios.TIOCM_RTS, True)    # EN low  -> reset asserted
time.sleep(0.45)
set_modem_bits(termios.TIOCM_RTS, False)   # EN high -> chip boots
t0 = time.time()

total = 0
with open(OUT, "wb") as f:
    while time.time() - t0 < 22:
        r, _, _ = select.select([fd], [], [], 0.25)
        if not r:
            continue
        data = os.read(fd, 8192)
        if data:
            f.write(data)
            f.flush()
            total += len(data)
            print(f"[{time.time()-t0:5.2f}s] +{len(data)}B total={total}", flush=True)

os.close(fd)
print(f"capture complete -> {OUT} ({total} bytes)")
