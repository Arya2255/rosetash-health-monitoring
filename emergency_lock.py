# -*- coding: utf-8 -*-
"""قفل اضطراری — غیرفعال‌سازی فوری برنامه.

فایل قفل: ~/.config/roztash/.emergency_lock

روش قفل کردن:
    1. Route مخفی: https://panel.rosetash-moe.ir/emergency-lock?key=SECRET_KEY
    2. یا دستی: touch ~/.config/roztash/.emergency_lock

روش باز کردن:
    rm ~/.config/roztash/.emergency_lock
"""

import os
import secrets

LOCK_FILE = os.path.expanduser("~/.config/roztash/.emergency_lock")
KEY_FILE = os.path.expanduser("~/.config/roztash/.emergency_key")


def is_locked() -> bool:
    """آیا برنامه قفل است؟"""
    return os.path.exists(LOCK_FILE)


def lock():
    """قفل کردن برنامه."""
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, "w") as f:
        f.write("locked")
    return True


def unlock():
    """باز کردن قفل."""
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
    return True


def get_or_create_key() -> str:
    """دریافت یا ساخت کلید امن.
    
    کلید یک رشته ۳۲ کاراکتری تصادفی است.
    فقط یک بار ساخته می‌شود و در فایل ذخیره می‌شود.
    """
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "r") as f:
            return f.read().strip()
    
    # ساخت کلید جدید
    key = secrets.token_urlsafe(24)
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    with open(KEY_FILE, "w") as f:
        f.write(key)
    return key


def verify_key(key: str) -> bool:
    """بررسی صحت کلید."""
    if not key:
        return False
    correct_key = get_or_create_key()
    return secrets.compare_digest(key, correct_key)


def get_lock_url() -> str:
    """دریافت آدرس قفل (برای نمایش به ادمین اصلی)."""
    from data import remote_status
    key = get_or_create_key()
    rs = remote_status() or {}
    base_url = rs.get("url", "")
    if not base_url:
        return ""
    return f"{base_url}/emergency-lock?key={key}"
