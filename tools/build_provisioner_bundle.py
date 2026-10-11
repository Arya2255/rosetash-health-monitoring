#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build (or refresh) the gateway-provisioning bundle shipped with the app.

Produces `distribution/gateway-provisioner/`:

    firmware/   prebuilt flash images (bootloader, partitions, boot_app0, app,
                blank LittleFS) — what the in-app provisioner flashes
    tools/      esptool / mklittlefs per platform — no Python/Arduino needed
                on the target (Windows) machine
    manifest.json   addresses, baud, flash mode + sha256 of every file

Steps:
  1. compile the gateway sketch (arduino-cli, min_spiffs partition scheme)
  2. copy the fresh binaries (the compile-output-dir pitfall stays avoided:
     everything is copied from the output dir of THIS compile)
  3. build the blank LittleFS image (board then boots into its setup AP)
  4. fetch platform tools when missing (--fetch-tools) or hash existing ones
  5. write manifest.json

Examples:
    python3 tools/build_provisioner_bundle.py                  # compile + refresh
    python3 tools/build_provisioner_bundle.py --no-compile     # just refresh/hash
    python3 tools/build_provisioner_bundle.py --fetch-tools    # download tools too
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "gateway"
DIST = ROOT / "distribution" / "gateway-provisioner"
FQBN = "esp32:esp32:esp32:PartitionScheme=min_spiffs"

# verified flash procedure (docs/gateway-setup.md): 4 files + littlefs, 460800
FLASH = {"baud": 460800, "mode": "dio", "freq": "80m", "size": "4MB"}
LFS = {"offset": "0x3D0000", "size": 0x20000, "page": 256, "block": 4096}

# pinned tool releases (versions the project has tested)
ESPTOOL_VER = "v5.5.0"
ESPTOOL_WIN_URL = (
    f"https://github.com/espressif/esptool/releases/download/{ESPTOOL_VER}"
    "/esptool-v5.5.0-windows-amd64.zip")
MKLFS_VER = "4.1.0"
MKLFS_REV = "42acb97"
MKLFS_WIN_URL = (
    f"https://github.com/earlephilhower/mklittlefs/releases/download/{MKLFS_VER}"
    f"/x86_64-w64-mingw32-mklittlefs-{MKLFS_REV}.zip")
MKLFS_LIN_URL = (
    f"https://github.com/earlephilhower/mklittlefs/releases/download/{MKLFS_VER}"
    f"/x86_64-linux-gnu-mklittlefs-{MKLFS_REV}.tar.gz")
MKLFS_LICENSE_URLS = [
    "https://raw.githubusercontent.com/earlephilhower/mklittlefs/master/LICENSE.txt",
]


def log(msg: str) -> None:
    print(f"[bundle] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def arduino_cli() -> str:
    for cand in ("arduino-cli", str(Path.home() / ".local" / "bin" / "arduino-cli")):
        p = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if p:
            return p
    sys.exit("arduino-cli not found — see docs/gateway-setup.md (step 2-1)")


def mklittlefs() -> str:
    cands = [
        DIST / "tools" / "linux-x86_64" / "mklittlefs",
        *sorted(glob.glob(str(Path.home() / ".arduino15" / "packages" / "esp32"
                                  / "tools" / "mklittlefs" / "*" / "mklittlefs"))),
    ]
    for c in cands:
        if Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    sys.exit("mklittlefs not found — run with --fetch-tools or install the "
             "esp32 core (see docs/gateway-setup.md)")


def fetch(url: str, dest: Path) -> None:
    log(f"fetch {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "roztash-bundle"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def compile_sketch(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cli = arduino_cli()
    cmd = [cli, "compile", "--fqbn", FQBN, str(SKETCH), "--output-dir", str(out_dir)]
    log("compile: " + " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    tail = (res.stdout or "") + (res.stderr or "")
    print(tail[-1200:])
    if res.returncode != 0:
        sys.exit(f"compile failed (exit {res.returncode})")
    return out_dir


def fw_version() -> str:
    """Read kFwVersion out of gateway.ino — single source of truth."""
    import re
    text = (SKETCH / "gateway.ino").read_text(encoding="utf-8")
    m = re.search(r'kFwVersion\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "unknown"


def core_version() -> str:
    try:
        out = subprocess.run([arduino_cli(), "core", "list"], capture_output=True,
                             text=True, timeout=60).stdout
        for line in out.splitlines():
            if line.startswith("esp32:esp32"):
                return line.split()[1]
    except Exception:
        pass
    return "unknown"


def copy_firmware(build_dir: Path, out: Path) -> list[dict]:
    """Copy the four flash images + build the blank LittleFS image."""
    out.mkdir(parents=True, exist_ok=True)
    pairs = [
        (build_dir / "gateway.ino.bootloader.bin", "bootloader.bin", "0x1000"),
        (build_dir / "gateway.ino.partitions.bin", "partitions.bin", "0x8000"),
        (build_dir / "gateway.ino.bin", "app.bin", "0x10000"),
    ]
    files = []
    for src, name, addr in pairs:
        if not src.is_file():
            sys.exit(f"missing build artifact: {src}")
        shutil.copy2(src, out / name)
        files.append({"addr": addr, "name": f"firmware/{name}", "path": out / name})

    # boot_app0.bin is not emitted by arduino-cli's output dir — take it from
    # the esp32 core's tools/partitions (or reuse a previously copied one)
    bootapp = out / "boot_app0.bin"
    if not bootapp.is_file():
        core_boot = sorted(glob.glob(str(
            Path.home() / ".arduino15" / "packages" / "esp32" / "hardware"
            / "esp32" / "*" / "tools" / "partitions" / "boot_app0.bin")))
        if not core_boot:
            sys.exit("boot_app0.bin not found (build dir or esp32 core)")
        shutil.copy2(core_boot[-1], bootapp)
    files.append({"addr": "0xe000", "name": "firmware/boot_app0.bin",
                  "path": bootapp})

    # blank LittleFS: empty filesystem -> board finds no /config.json at boot
    # and starts its setup AP (firmware/gateway/setup_portal.cpp)
    blank_dir = Path(tempfile.mkdtemp(prefix="lfs-blank-"))
    blank = out / "littlefs-blank.bin"
    cmd = [mklittlefs(), "-c", str(blank_dir), "-s", hex(LFS["size"]),
           "-p", str(LFS["page"]), str(blank)]
    log("mklittlefs: " + " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        sys.exit(f"mklittlefs failed: {res.stdout}{res.stderr}")
    shutil.rmtree(blank_dir, ignore_errors=True)
    files.append({"addr": LFS["offset"], "name": "firmware/littlefs-blank.bin",
                  "path": blank})
    return files


def ensure_tools(fetch_tools: bool) -> dict:
    """Place/fetch platform tools; return {platform: {file: sha256}}."""
    win = DIST / "tools" / "windows-amd64"
    lin = DIST / "tools" / "linux-x86_64"
    win.mkdir(parents=True, exist_ok=True)
    lin.mkdir(parents=True, exist_ok=True)

    needed = {
        "windows-amd64": {
            "esptool.exe": None, "mklittlefs.exe": None,
            "libwinpthread-1.dll": None,
            "LICENSE.esptool.txt": None, "LICENSE.mklittlefs.txt": None,
        },
        "linux-x86_64": {"mklittlefs": None},
    }
    have_all = all((DIST / "tools" / plat / f).is_file()
                   for plat, fs in needed.items() for f in fs)
    if not have_all and not fetch_tools:
        log("tools missing — run again with --fetch-tools (network) "
            "or copy them in manually")
    if fetch_tools:
        with tempfile.TemporaryDirectory(prefix="gw-tools-") as tmp:
            tmp = Path(tmp)
            if not (win / "esptool.exe").is_file():
                z = tmp / "esptool-win.zip"
                fetch(ESPTOOL_WIN_URL, z)
                with zipfile.ZipFile(z) as zf:
                    base = "esptool-windows-amd64/"
                    zf.extract(base + "esptool.exe", tmp)
                    zf.extract(base + "LICENSE", tmp)
                shutil.copy2(tmp / base / "esptool.exe", win / "esptool.exe")
                shutil.copy2(tmp / base / "LICENSE", win / "LICENSE.esptool.txt")
            if not (win / "mklittlefs.exe").is_file() or not (win / "libwinpthread-1.dll").is_file():
                z = tmp / "mklfs-win.zip"
                fetch(MKLFS_WIN_URL, z)
                with zipfile.ZipFile(z) as zf:
                    for leaf in ("mklittlefs.exe", "libwinpthread-1.dll"):
                        zf.extract(f"mklittlefs/{leaf}", tmp)
                        shutil.copy2(tmp / "mklittlefs" / leaf, win / leaf)
            if not (lin / "mklittlefs").is_file():
                t = tmp / "mklfs-lin.tar.gz"
                fetch(MKLFS_LIN_URL, t)
                with tarfile.open(t) as tf:
                    member = next(m for m in tf.getmembers()
                                  if m.name.endswith("mklittlefs") and m.isfile())
                    tf.extract(member, tmp)
                    shutil.copy2(tmp / member.name, lin / "mklittlefs")
                os.chmod(lin / "mklittlefs", 0o755)
            if not (win / "LICENSE.mklittlefs.txt").is_file():
                for url in MKLFS_LICENSE_URLS:
                    try:
                        fetch(url, win / "LICENSE.mklittlefs.txt")
                        break
                    except Exception:
                        continue

    out: dict = {}
    for plat, fs in needed.items():
        out[plat] = {}
        for f in fs:
            p = DIST / "tools" / plat / f
            if p.is_file():
                out[plat][f] = {"sha256": sha256(p), "size": p.stat().st_size}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-compile", action="store_true",
                    help="skip arduino-cli compile; reuse firmware/gateway/build")
    ap.add_argument("--fetch-tools", action="store_true",
                    help="download platform tools when missing")
    args = ap.parse_args()

    fw_dir = DIST / "firmware"
    build_dir = SKETCH / "build"
    if not args.no_compile:
        build_dir = compile_sketch(build_dir)
    else:
        log("skipping compile — using existing build outputs")

    files = copy_firmware(build_dir, fw_dir)
    tools = ensure_tools(args.fetch_tools)

    manifest = {
        "schema": "roztash-gateway-bundle/v1",
        "built_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "fw_version": fw_version(),
        "fqbn": FQBN,
        "core": f"esp32:esp32 {core_version()}",
        "flash": dict(FLASH, files=[
            {"addr": f["addr"], "file": f["name"], "sha256": sha256(f["path"]),
             "size": f["path"].stat().st_size} for f in files]),
        "littlefs": dict(LFS),
        "tools": tools,
        "notes": [
            "littlefs-blank.bin has no /config.json: the board boots into its "
            "setup AP (RoztashGw-XXXXXX) for phone configuration.",
            "The app generates a per-gateway LittleFS image at flash time "
            "(mklittlefs, same geometry as littlefs-blank.bin).",
        ],
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    total_mb = sum(f["size"] for f in manifest["flash"]["files"]) / 1e6
    log(f"manifest written — fw {manifest['fw_version']}, "
        f"{len(manifest['flash']['files'])} flash files ({total_mb:.2f} MB), "
        f"tools: { {k: len(v) for k, v in tools.items()} }")
    log(f"bundle ready: {DIST}")


if __name__ == "__main__":
    main()
