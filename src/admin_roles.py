# -*- coding: utf-8 -*-
"""مدیریت نقش ادمین‌ها — ادمین اصلی و ادمین‌های فرعی.

نقش‌ها:
- "owner": ادمین اصلی — دسترسی کامل، مدیریت ادمین‌های دیگر
- "viewer": ادمین فرعی — دسترسی محدود

محدودیت‌های viewer:
- پشتیبان‌گیری: ندارد
- لاگ برنامه: ندارد
- دسترسی از اینترنت: ندارد
- گیتوی‌ها: فهرست و مشاهده دارد، افزودن/حذف/ویرایش ندارد
- آماده‌سازی گیتوی‌ها: ندارد
- نقشه کارخانه: همه چیز دارد به جز چیدن روی نقشه

ذخیره‌سازی: ~/.config/roztash/admin_roles.json
"""

import json
import os
from datetime import datetime
from typing import Optional

import applog

# ═══════════ تنظیمات ═══════════

ROLES_FILE = os.path.expanduser("~/.config/roztash/admin_roles.json")

# ادمین پیش‌فرض — اولین ادمین اصلی
DEFAULT_OWNER = "i.s.1377.1999@gmail.com"

# ═══════════ توابع داخلی ═══════════

def _ensure_dir():
    """اطمینان از وجود پوشه."""
    d = os.path.dirname(ROLES_FILE)
    if d:
        os.makedirs(d, exist_ok=True)


def _read_roles() -> dict:
    """خواندن فایل نقش‌ها."""
    try:
        with open(ROLES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_roles(data: dict):
    """نوشتن فایل نقش‌ها."""
    _ensure_dir()
    data["updated_at"] = datetime.now().isoformat()
    with open(ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════ API عمومی ═══════════

def get_role(email: Optional[str]) -> str:
    """دریافت نقش ایمیل.
    
    Returns: "owner" | "viewer" | "" (اگر ایمیل نیست یا نقشی ندارد)
    """
    if not email:
        return ""
    email = email.strip().lower()
    data = _read_roles()
    
    # بررسی نقش صریح
    roles = data.get("roles", {})
    role = roles.get(email, "")
    
    # اگر نقش ندارد، ولی در فهرست ادمین‌های کلادفلر است، پیش‌فرض viewer
    if not role:
        # fallback: اگر ایمیل پیش‌فرض owner است
        if email == DEFAULT_OWNER.lower():
            return "owner"
        # ایمیل‌های جدید که نقش ندارند، viewer محسوب می‌شوند
        # (پس از لاگین موفق، نقش پیش‌فرض viewer است)
        return ""
    
    return role


def set_role(email: str, role: str) -> tuple[bool, str]:
    """تنظیم نقش ادمین.
    
    Args:
        email: ایمیل ادمین
        role: "owner" یا "viewer"
        
    Returns:
        (موفق, پیام)
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "ایمیل معتبر نیست"
    
    role = role.strip().lower()
    if role not in ("owner", "viewer"):
        return False, "نقش باید owner یا viewer باشد"
    
    # ادمین اصلی ثابت است — فقط viewer می‌توان اضافه کرد
    if email == DEFAULT_OWNER.lower():
        return False, "ادمین اصلی ثابت و غیرقابل تغییر است"
    
    data = _read_roles()
    if "roles" not in data:
        data["roles"] = {}
    
    # همه ادمین‌های جدید viewer هستند
    if role != "viewer":
        role = "viewer"
    
    data["roles"][email] = role
    _write_roles(data)
    applog.info("نقش ادمین تنظیم شد — %s → %s", email, role)
    return True, "ادمین فرعی اضافه شد"


def list_admins() -> list[dict]:
    """فهرست همه ادمین‌ها با نقش‌شان.
    
    Returns:
        [{email, role, label}, ...]
    """
    data = _read_roles()
    roles = data.get("roles", {})
    
    result = []
    
    # ادمین پیش‌فرض
    if DEFAULT_OWNER.lower() not in roles:
        result.append({
            "email": DEFAULT_OWNER,
            "role": "owner",
            "label": "ادمین اصلی",
        })
    
    # بقیه ادمین‌ها
    for email, role in roles.items():
        label = "ادمین اصلی" if role == "owner" else "ادمین فرعی"
        result.append({
            "email": email,
            "role": role,
            "label": label,
        })
    
    # مرتب‌سازی: owner اول
    result.sort(key=lambda x: (0 if x["role"] == "owner" else 1, x["email"]))
    
    return result


def remove_admin(email: str) -> tuple[bool, str]:
    """حذف ادمین.
    
    ادمین اصلی قابل حذف نیست.
    """
    email = (email or "").strip().lower()
    if not email:
        return False, "ایمیل نامعتبر"
    
    if email == DEFAULT_OWNER.lower():
        return False, "ادمین اصلی قابل حذف نیست"
    
    data = _read_roles()
    roles = data.get("roles", {})
    
    if email not in roles:
        return False, "این ایمیل ادمین نیست"
    
    del roles[email]
    data["roles"] = roles
    _write_roles(data)
    applog.info("ادمین حذف شد — %s", email)
    return True, "ادمین حذف شد"


def ensure_has_role(email: str) -> str:
    """اطمینان از اینکه ایمیل نقش دارد (حتی viewer).
    
    اگر نقش ندارد و ایمیل owner پیش‌فرض است → owner
    اگر نقش ندارد → viewer (ذخیره نمی‌شود، فقط inline تعیین می‌شود)
    
    Returns: نقش نهایی
    """
    role = get_role(email)
    if role:
        return role
    
    # اگر owner پیش‌فرض است
    if email and email.strip().lower() == DEFAULT_OWNER.lower():
        return "owner"
    
    # بقیه ایمیل‌ها viewer محسوب می‌شوند
    if email:
        return "viewer"
    
    return ""


# ═══════════ قلاب دسترسی ═══════════

def can_backup(role: str) -> bool:
    """آیا می‌تواند پشتیبان‌گیری کند؟"""
    return role == "owner"


def can_view_logs(role: str) -> bool:
    """آیا می‌تواند لاگ برنامه را ببیند؟"""
    return role == "owner"


def can_manage_remote(role: str) -> bool:
    """آیا می‌تواند دسترسی از اینترنت را مدیریت کند؟"""
    return role == "owner"


def can_manage_gateways(role: str) -> bool:
    """آیا می‌تواند گیتوی‌ها را مدیریت کند؟"""
    return role == "owner"


def can_edit_map(role: str) -> bool:
    """آیا می‌تواند گیتوی را روی نقشه بچیند؟"""
    return role == "owner"


def can_manage_admins(role: str) -> bool:
    """آیا می‌تواند ادمین‌های دیگر را مدیریت کند؟"""
    return role == "owner"
