# -*- coding: utf-8 -*-
"""تست ماژول دسترسی از اینترنت — بدون اثر جانبی.

اجرا:
    uv run python scripts/test_remote.py

فقط می‌خواند و اعتبارسنجی می‌کند؛ تونل را بالا نمی‌آورد و چیزی روی
کلادفلر تغییر نمی‌دهد.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

import remote  # noqa: E402


def main() -> int:
    print("پوشهٔ فایل‌ها:", remote._home())
    print("توکن API تنظیم شده:", bool(remote._token()))
    print("cloudflared پیدا شد:", remote.bin_ready())

    cfg = remote.ensure_config()
    print("تنظیمات همراه برنامه:")
    for k in ("ok", "zone", "zone_id", "account_id", "host", "tunnel_id",
              "emails", "auto_start", "err"):
        print("   ", k, "=", cfg.get(k, "—"))

    st = remote.status()
    print("وضعیت:")
    for k in ("ok", "label", "detail", "running", "locked", "installed",
              "url", "emails", "auto_start"):
        print("   ", k, "=", st.get(k, "—"))

    # اعتبارسنجی — بدون تماس شبکه‌ای
    ok, msg = remote.add_email("این-ایمیل-نیست")
    print("ایمیل نامعتبر →", ok, "|", msg)
    ok, msg = remote.remove_email("nobody@example.com")
    print("حذف ایمیل ناموجود →", ok, "|", msg)

    fails = []
    if not remote._token():
        fails.append("توکن API پیدا نشد")
    if not cfg.get("ok"):
        fails.append("تنظیمات کامل نشد: %s" % cfg.get("err"))
    if not st.get("installed"):
        fails.append("cloudflared نصب نیست")
    if fails:
        print("مشکل:", "؛ ".join(fails))
        return 1
    print("تست ماژول دسترسی از اینترنت — بدون مشکل")
    return 0


if __name__ == "__main__":
    sys.exit(main())
