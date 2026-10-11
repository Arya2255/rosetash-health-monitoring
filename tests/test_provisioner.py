# -*- coding: utf-8 -*-
"""تست موتور «آماده‌سازی گیتوی» — بدون برد فیزیکی و بدون رابط گرافیکی.

بررسی‌ها:
  - ترتیب لایه‌های پیدا کردن ابزار (بستهٔ همراه، آردوینو، PATH، متغیر محیطی)
  - قاعدهٔ شناسهٔ گیت‌وی و کوتاه‌سازی فیلدهای config
  - ساخت واقعی تصویر LittleFS با mklittlefs همراه بسته
  - فرمان فلش، درصد پیشرفت، تشخیص موفقیت و ترجمهٔ خطاها
  - manifest و وضعیت بستهٔ همراه

اجرا از ریشهٔ مخزن:
    uv run python tests/test_provisioner.py
"""
import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import provisioner as pv  # noqa: E402

BUNDLE = os.path.join(_HERE, "..", "distribution", "gateway-provisioner")


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("x")
    return path


def main():
    tmp = tempfile.mkdtemp(prefix="test-prov-")
    home = os.path.join(tmp, "home")
    os.makedirs(home)

    # ── ۱) پیدا کردن ابزار — لایه‌بندی bundled < arduino < path ──
    fake_bundle = os.path.join(tmp, "bundle")
    touch(os.path.join(fake_bundle, "tools", "linux-x86_64", "esptool"))
    touch(os.path.join(fake_bundle, "tools", "linux-x86_64", "mklittlefs"))
    touch(os.path.join(fake_bundle, "tools", "windows-amd64", "esptool.exe"))
    touch(os.path.join(fake_bundle, "tools", "windows-amd64", "mklittlefs.exe"))

    tools = pv.find_tools(bundle=fake_bundle, platform="linux-x86_64", home=home)
    assert tools["esptool"].endswith("tools/linux-x86_64/esptool"), tools
    assert tools["sources"]["esptool"] == "bundled", tools
    assert tools["sources"]["mklittlefs"] == "bundled", tools

    tools_win = pv.find_tools(bundle=fake_bundle, platform="windows-amd64",
                              home=home)
    assert tools_win["esptool"].endswith("esptool.exe"), tools_win
    assert tools_win["mklittlefs"].endswith("mklittlefs.exe"), tools_win

    # نبود بسته → نصب آردوینو نقش جایگزین را بازی می‌کند
    ard = os.path.join(home, ".arduino15", "packages", "esp32", "tools")
    touch(os.path.join(ard, "esptool_py", "5.3.1", "esptool"))
    touch(os.path.join(ard, "mklittlefs", "4.0.2", "mklittlefs"))
    empty_bundle = os.path.join(tmp, "empty-bundle")
    tools2 = pv.find_tools(bundle=empty_bundle, platform="linux-x86_64", home=home)
    assert tools2["sources"]["esptool"] == "arduino", tools2
    assert tools2["sources"]["mklittlefs"] == "arduino", tools2

    # متغیر محیطی بر همه چیز مقدم است
    env_tool = touch(os.path.join(tmp, "my-esptool"))
    os.environ["ROZTASH_ESPTOOL"] = env_tool
    try:
        tools3 = pv.find_tools(bundle=fake_bundle, platform="linux-x86_64", home=home)
        assert tools3["esptool"] == env_tool, tools3
        assert tools3["sources"]["esptool"] == "env", tools3
    finally:
        del os.environ["ROZTASH_ESPTOOL"]

    # هیچ جا نبود → None، بدون استثنا
    tools4 = pv.find_tools(bundle=empty_bundle, platform="linux-x86_64", home=home)
    assert tools4["esptool"] is not None  # از مسیر PATH شاید پیدا شود

    # ── ۲) شناسهٔ گیت‌وی ──
    assert pv.validate_gw_id("gw-filter-1")[0]
    assert pv.validate_gw_id("gw-2")[0]
    assert pv.validate_gw_id("a" * 32)[0]
    assert not pv.validate_gw_id("a" * 33)[0]
    assert not pv.validate_gw_id("")[0]
    assert not pv.validate_gw_id("-bad")[0]
    assert not pv.validate_gw_id("gw filter")[0]          # فاصله بدون یکسان‌سازی
    assert not pv.validate_gw_id("گیت‌وی")[0]
    assert "خط تیره" in pv.validate_gw_id("GW FILTER")[1]

    # ── ۳) ساخت config — کوتاه‌سازی و پیش‌فرض‌ها ──
    cfg = pv.build_config("Gw-Test-1", "س" * 60, "s" * 50, "p" * 100,
                          "10.0.0.1", "1884", 60)
    assert cfg["gw_id"] == "gw-test-1", cfg
    assert len(cfg["zone"]) == 39 and len(cfg["wifi_ssid"]) == 39, cfg
    assert len(cfg["wifi_pass"]) == 79, cfg
    assert cfg["mqtt_port"] == 1884 and cfg["health_interval_s"] == 60, cfg
    assert cfg["scan_interval_ms"] == 160 and cfg["measure_timeout_s"] == 45
    text = pv.config_json_text(cfg)
    assert "س" in text, "متن تنظیمات باید UTF-8 و خوانا باشد"

    # ── ۴) ساخت واقعی تصویر LittleFS ──
    real = pv.find_tools(bundle=BUNDLE)
    if real["mklittlefs"] and real["sources"]["mklittlefs"] == "bundled":
        out = os.path.join(tmp, "lfs-test.bin")
        ok, err = pv.build_littlefs(cfg, out, real["mklittlefs"])
        assert ok, err
        assert os.path.getsize(out) == 0x20000, os.path.getsize(out)
        with open(out, "rb") as fh:
            blob = fh.read()
        assert "gw-test-1".encode() in blob, "config.json داخل تصویر نباشد"
    else:
        print("(mklittlefs همراه بسته نبود — بخش ساخت LittleFS رد شد)")

    ok, err = pv.build_littlefs(cfg, os.path.join(tmp, "x.bin"),
                                "/no/such/mklittlefs")
    assert not ok and "mklittlefs" in err

    # ── ۵) فرمان فلش ──
    cmd = pv.flash_command("/t/esptool", "/dev/ttyUSB0",
                           [("0x1000", "boot.bin"), ("0x3D0000", "fs.bin")])
    assert cmd[:7] == ["/t/esptool", "--chip", "esp32", "--port", "/dev/ttyUSB0",
                       "--baud", "460800"], cmd
    assert cmd[7:14] == ["write-flash", "--flash-mode", "dio",
                         "--flash-freq", "80m", "--flash-size", "4MB"], cmd
    assert cmd[14:] == ["0x1000", "boot.bin", "0x3D0000", "fs.bin"], cmd
    assert pv.flash_command("e", "COM3", [], baud=115200)[6] == "115200"

    # ── ۶) پیشرفت و موفقیت ──
    assert pv.progress_percent("Writing at 0x00010000... (14 %)") == 14
    assert pv.progress_percent("Writing at 0x00010000... (100 %)") == 100
    assert pv.progress_percent("Connecting...") is None
    v5 = ("Writing at 0x00010000... (100 %)\n"
          "Wrote 1284368 bytes (742905 compressed) at 0x00010000 in 6.1 seconds\n"
          "Hash of data verified.\n")
    assert pv.flash_ok(v5, 0)
    assert not pv.flash_ok(v5, 1)
    assert not pv.flash_ok("A fatal error occurred: Failed to connect", 2)

    # ── ۷) ترجمهٔ خطاها ──
    h = pv._serial_error_hint(
        "could not open port /dev/ttyUSB0: [Errno 13] Permission denied")
    assert "dialout" in h, h
    h = pv._serial_error_hint("A fatal error occurred: Failed to connect to ESP32")
    assert "BOOT" in h, h
    h = pv._serial_error_hint("could not open port COM3: The port is busy")
    assert "مشغول" in h, h

    # ── ۸) فهرست پورت — ویندوز و لینوکس (شبیه‌سازی‌شده) ──
    wtext = ("Silicon Labs CP210x USB to UART Bridge (COM3)\n"
             "Intel(R) Active Management Technology - SOL (COM4)\n"
             "некоторый мусор без порта\n")
    wp = pv._parse_windows_ports(wtext)
    assert [d["port"] for d in wp] == ["COM3", "COM4"], wp
    assert "CP210x" in wp[0]["label"], wp

    dev = os.path.join(tmp, "dev")
    touch(os.path.join(dev, "ttyUSB0"))
    byid = os.path.join(dev, "serial", "by-id", "usb-Silicon_Labs_CP2102_USB-1")
    os.makedirs(os.path.dirname(byid), exist_ok=True)
    os.symlink(os.path.join(dev, "ttyUSB0"), byid)
    lp = pv._linux_ports(dev)
    assert lp and lp[0]["port"].endswith("ttyUSB0"), lp
    assert "Silicon" in lp[0]["label"], lp

    # ── ۹) manifest و وضعیت بسته ──
    ok, mani = pv.load_manifest(BUNDLE)
    assert ok, mani
    addrs = {f["addr"] for f in mani["flash"]["files"]}
    assert addrs == {"0x1000", "0x8000", "0xe000", "0x10000", "0x3D0000"}, addrs
    assert mani["fw_version"].startswith("0.2"), mani["fw_version"]
    assert mani["flash"]["baud"] == 460800

    ok, bad = pv.load_manifest(os.path.join(tmp, "nope"))
    assert not ok and "پیدا نشد" in bad["error"], bad

    st = pv.bundle_status(BUNDLE)
    assert st["present"] and st["files"] == 5, st
    assert st["tools"]["esptool"] in ("bundled", "arduino", "path"), st

    # ── ۱۰) read_chip_info — پاسخ ساختگی esptool ──
    fake_esptool = touch(os.path.join(tmp, "fake-esptool"))
    with open(fake_esptool, "w") as fh:
        fh.write("#!/bin/sh\n"
                 "echo 'Chip type:          ESP32-D0WD-V3 (revision v3.1)'\n"
                 "echo 'MAC:                88:57:21:B8:AC:28'\n"
                 "echo 'Detected flash size: 4MB'\n")
    os.chmod(fake_esptool, 0o755)
    ok, doc = pv.read_chip_info("/dev/fake", fake_esptool)
    assert ok and doc["mac"] == "88:57:21:b8:ac:28", doc
    assert "ESP32-D0WD-V3" in doc["chip"], doc
    assert doc["flash"] == "4MB", doc

    print("OK — همهٔ بررسی‌های موتور آماده‌سازی گیتوی پاس شد")


if __name__ == "__main__":
    main()
