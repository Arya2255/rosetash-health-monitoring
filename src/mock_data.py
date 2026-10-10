# -*- coding: utf-8 -*-
"""داده‌های نمونه برای نمونهٔ اولیهٔ رابط کاربری — فاز ۱ طراحی.

دادهٔ واقعی در فاز ۲ از بک‌اند (WebSocket) جایگزین می‌شود؛
همهٔ اعداد این فایل نمایشی‌اند.
"""

import datetime as _dt
import math
import random

random.seed(11)

_now = _dt.datetime.now()


def _hm(td: _dt.datetime) -> str:
    return td.strftime("%H:%M")


INCIDENT_TIME = _hm(_now - _dt.timedelta(minutes=14))

# ═══════════ مناطق کارخانه و گیت‌وی‌های BLE ═══════════
# هر منطقه یک گیت‌وی دارد — نزدیک‌ترین گیت‌وی محل کارکن را ثبت می‌کند
FACTORY_ZONES = [
    ("درب ورودی",           "GW-01"),
    ("محوطه",               "GW-02"),
    ("رختکن",               "GW-03"),
    ("سالن تولید ۱",         "GW-04"),
    ("سالن تولید ۲",         "GW-05"),
    ("سالن پلاستیک",        "GW-06"),
    ("سالن بسته‌بندی",      "GW-07"),
    ("انبار مواد اولیه",    "GW-08"),
    ("انبار محصول",         "GW-09"),
    ("محوطه انبار",         "GW-10"),
    ("کارگاه تعمیرات",      "GW-11"),
    ("دفتر اداری",          "GW-12"),
    ("آبدارخانه و نمازخانه", "GW-13"),
]
ZONE_GW = {name: gw for name, gw in FACTORY_ZONES}
ZONE_NAMES = [name for name, _ in FACTORY_ZONES]

# رنگ هر منطقه — برای نوار زمانی مکان‌ها
ZONE_COLORS = {
    "درب ورودی":           "#1A5FB4",
    "محوطه":               "#5B6B7B",
    "رختکن":               "#8E7CC3",
    "سالن تولید ۱":         "#E30613",
    "سالن تولید ۲":         "#F06A2E",
    "سالن پلاستیک":        "#0E9488",
    "سالن بسته‌بندی":      "#1E8E4E",
    "انبار مواد اولیه":    "#B26900",
    "انبار محصول":         "#B58A00",
    "محوطه انبار":         "#7A8B99",
    "کارگاه تعمیرات":      "#2F6FB8",
    "دفتر اداری":          "#6B4FA0",
    "آبدارخانه و نمازخانه": "#C2569A",
}

# ═══════════ کارکنان (۲۴ نفر) ═══════════
# name, dept, line, shift, status, location, hr, spo2, present, note
_ROWS = [
    ("رضا محمدی",   "تولید روغن",    "خط روغن ۲",       "صبح", "danger", "سالن تولید ۲",     118, 94, True,  "سقوط شناسایی شد — نیازمند اقدام فوری"),
    ("مهدی کریمی",  "تعمیرات",       "کارگاه تعمیرات",  "صبح", "warn",   "کارگاه تعمیرات",   132, 96, True,  "ضربان قلب بالاتر از حد مجاز"),
    ("امیر تهرانی", "تولید روغن",    "خط روغن ۱",       "صبح", "warn",   "سالن تولید ۱",      88, 91, True,  "افت اکسیژن خون"),
    ("حسین احمدی",  "انبار",         "مواد اولیه",      "صبح", "ok",     "انبار مواد اولیه",  77, 97, True,  ""),
    ("علی رضایی",   "تولید روغن",    "خط روغن ۱",       "صبح", "ok",     "سالن تولید ۱",      74, 98, True,  ""),
    ("سعید نوری",   "تولید پلاستیک", "خط پلاستیک ۱",    "صبح", "ok",     "سالن پلاستیک",      81, 97, True,  ""),
    ("محمد قاسمی",  "خط بسته‌بندی",  "خط بسته‌بندی ۱",  "صبح", "ok",     "سالن بسته‌بندی",    79, 98, True,  ""),
    ("فاطمه حسینی", "خط بسته‌بندی",  "خط بسته‌بندی ۲",  "صبح", "ok",     "سالن بسته‌بندی",    72, 99, True,  ""),
    ("زهرا مرادی",  "اداری",         "دفتر",            "صبح", "ok",     "دفتر اداری",        70, 98, True,  ""),
    ("کاظم شریفی",  "انبار",         "محصول",           "صبح", "ok",     "انبار محصول",       76, 97, True,  ""),
    ("یاسر کاظمی",  "تولید پلاستیک", "خط پلاستیک ۱",    "صبح", "ok",     "سالن پلاستیک",      84, 96, True,  ""),
    ("ناصر بیگی",   "حراست",         "محوطه",           "صبح", "off",    "محوطه",             None, None, True, "خارج از پوشش گیت‌وی"),
    ("بهرام سلطانی","تعمیرات",       "کارگاه تعمیرات",  "صبح", "off",    "—",                 None, None, False, "مرخصی امروز"),
    ("سمیرا اکبری", "اداری",         "دفتر",            "صبح", "ok",     "دفتر اداری",        69, 99, True,  ""),
    ("حسین یوسفی",  "خط بسته‌بندی",  "خط بسته‌بندی ۱",  "صبح", "ok",     "سالن بسته‌بندی",    78, 97, True,  ""),
    ("مرتضی کمالی", "انبار",         "محصول",           "صبح", "ok",     "محوطه انبار",       80, 96, True,  ""),
    ("ایمان رستمی", "تولید پلاستیک", "خط پلاستیک ۱",    "صبح", "ok",     "سالن پلاستیک",      75, 98, True,  ""),
    ("وحید عباسی",  "تولید روغن",    "خط روغن ۲",       "صبح", "ok",     "سالن تولید ۲",      73, 97, True,  ""),
    ("حمید جعفری",  "تعمیرات",       "کارگاه تعمیرات",  "صبح", "ok",     "کارگاه تعمیرات",    82, 97, True,  ""),
    ("سارا نجفی",   "اداری",         "دفتر",            "صبح", "ok",     "دفتر اداری",        71, 99, True,  ""),
    ("بابک صادقی",  "انبار",         "مواد اولیه",      "صبح", "ok",     "انبار مواد اولیه",  79, 96, True,  ""),
    ("جواد محمودی", "خط بسته‌بندی",  "خط بسته‌بندی ۲",  "صبح", "ok",     "سالن بسته‌بندی",    85, 97, True,  ""),
    ("اکبر رحیمی",  "تولید روغن",    "خط روغن ۱",       "صبح", "ok",     "سالن تولید ۱",      77, 98, True,  ""),
    ("پیمان اسدی",  "حراست",         "درب ورودی",       "صبح", "ok",     "درب ورودی",         83, 97, True,  ""),
]


def _series(base_hr, status):
    """سری زمانی ضربان قلب — از ابتدای شیفت تاکنون."""
    pts = []
    for i in range(36):
        v = base_hr + int(6 * math.sin(i / 3.1)) + random.randint(-4, 5)
        pts.append(max(48, min(140, v)))
    if status == "danger":
        pts[-5:] = [96, 105, 112, 118, 118]
    elif status == "warn":
        pts[-4:] = [125, 129, 132, 132]
    elif status == "off":
        pts = [None] * 36
    return pts


EMPLOYEES = []
for _i, (_n, _d, _l, _s, _st, _loc, _hr, _sp, _pr, _note) in enumerate(_ROWS, start=1):
    _work = int((_now - _now.replace(hour=6, minute=49, second=0)).total_seconds() // 60) if _pr else 0
    EMPLOYEES.append({
        "id": _i,
        "name": _n,
        "dept": _d,
        "line": _l,
        "shift": _s,
        "band": f"TRX-{_i:04d}",
        "status": _st,
        "hr": _hr,
        "spo2": _sp,
        "temp": round(random.uniform(36.4, 37.0), 1) if _st != "off" else None,
        "battery": random.choice([64, 71, 78, 82, 86, 91, 23, 96, 88, 74]),
        "signal": random.choice(["عالی", "خوب", "خوب", "متوسط"]),
        "location": _loc,
        "last_seen": random.randint(4, 90) if _st != "off" else random.randint(300, 900),
        "present": _pr,
        "entered": "06:49" if _pr else None,
        "work_min": _work,
        "note": _note,
        "hr_series": _series(_hr or 74, _st),
        "incident_time": INCIDENT_TIME if _st == "danger" else None,
    })

# ═══════════ حضور و غیاب و تاریخچهٔ مکان ═══════════
# در فاز ۲ این بخش از جریان بسته‌های تبلیغاتی BLE گیت‌وی‌ها ساخته می‌شود؛
# اینجا داده نمایشی و قطعی است.
_LATE_FROM = 7 * 60                  # تأخیر از ۰۷:۰۰ به بعد
_LEFT_IDS = {16, 21, 22}             # خروج زودهنگام امروز — نمونه
_DETOUR_ZONES = [
    "انبار مواد اولیه", "سالن بسته‌بندی", "کارگاه تعمیرات",
    "آبدارخانه و نمازخانه", "محوطه انبار", "دفتر اداری",
]


def _build_zone_log(rnd, start_dt, end_dt, home_zone, still_in):
    """توالی بازه‌های حضور در مناطق — همان چیزی که گیت‌وی‌ها ثبت می‌کنند."""
    if end_dt <= start_dt or home_zone not in ZONE_COLORS:
        return []
    detours = [z for z in _DETOUR_ZONES if z != home_zone]
    pattern = ["درب ورودی", "رختکن", home_zone]
    log = []
    t = start_dt
    step = 0
    while t < end_dt:
        if step < len(pattern):
            zone = pattern[step]
        else:
            zone = home_zone if rnd.random() < 0.68 else rnd.choice(detours)
        dur = rnd.randint(5, 12) if step < 2 else rnd.randint(16, 68)
        seg_end = min(t + _dt.timedelta(minutes=dur), end_dt)
        mins = int((seg_end - t).total_seconds() // 60)
        if mins >= 1:
            if log and log[-1]["zone"] == zone:
                log[-1]["end"] = seg_end.strftime("%H:%M")
                log[-1]["minutes"] += mins
            else:
                log.append({
                    "zone": zone, "gw": ZONE_GW.get(zone, "—"),
                    "start": t.strftime("%H:%M"),
                    "end": seg_end.strftime("%H:%M"),
                    "minutes": mins,
                })
        t = seg_end
        step += 1
    if log and still_in:
        log[-1]["ongoing"] = True
    return log


def _zone_totals(log):
    tot = {}
    for seg in log:
        tot[seg["zone"]] = tot.get(seg["zone"], 0) + seg["minutes"]
    return sorted(tot.items(), key=lambda kv: -kv[1])


_EMPTY_ATT = {
    "status": "absent", "entered": None, "exited": None, "work_min": 0,
    "late_min": 0, "coverage": False, "last_zone": None,
    "zone_log": [], "zone_totals": [],
}

for _e in EMPLOYEES:
    _rnd = random.Random(1000 + _e["id"])
    if not _e["present"]:
        _e["attendance"] = dict(
            _EMPTY_ATT,
            status="leave" if "مرخصی" in _e["note"] else "absent",
        )
        continue
    _offset = _rnd.randint(-4, 25)
    _entered_dt = _now.replace(hour=6, minute=49, second=0, microsecond=0) \
        + _dt.timedelta(minutes=_offset)
    _covered = _e["status"] != "off"
    _still_in = (_e["id"] not in _LEFT_IDS) and _covered
    _end_dt = _now
    _exited = None
    if not _still_in and _covered:
        _end_dt = min(_entered_dt + _dt.timedelta(minutes=_rnd.randint(330, 430)), _now)
        _exited = _end_dt.strftime("%H:%M")
    _log = _build_zone_log(_rnd, _entered_dt, _end_dt, _e["location"], _still_in) if _covered else []
    _e["attendance"] = {
        "status": "left" if _exited else "present",
        "entered": _entered_dt.strftime("%H:%M"),
        "exited": _exited,
        "work_min": max(0, int((_end_dt - _entered_dt).total_seconds() // 60)),
        "late_min": max(0, (_entered_dt.hour * 60 + _entered_dt.minute) - _LATE_FROM),
        "coverage": _covered,
        "last_zone": _log[-1]["zone"] if _log else None,
        "zone_log": _log,
        "zone_totals": _zone_totals(_log),
    }
    _e["entered"] = _e["attendance"]["entered"]
    _e["work_min"] = _e["attendance"]["work_min"]
    if _exited:
        _e["last_seen"] = max(_e["last_seen"], 1800)

# ═══════════ هشدارهای فعال ═══════════
ALERTS_ACTIVE = [
    {"id": "a1", "type": "سقوط", "severity": "danger",
     "emp_id": 1, "emp": "رضا محمدی", "dept": "تولید روغن — خط روغن ۲",
     "location": "سالن تولید ۲", "time": INCIDENT_TIME},
    {"id": "a2", "type": "ضربان قلب بالا", "severity": "warn",
     "emp_id": 2, "emp": "مهدی کریمی", "dept": "تعمیرات",
     "location": "کارگاه تعمیرات", "time": _hm(_now - _dt.timedelta(minutes=33))},
    {"id": "a3", "type": "افت اکسیژن خون", "severity": "warn",
     "emp_id": 3, "emp": "امیر تهرانی", "dept": "تولید روغن — خط روغن ۱",
     "location": "سالن تولید ۱", "time": _hm(_now - _dt.timedelta(minutes=21))},
]

# ═══════════ تاریخچهٔ امروز ═══════════
ALERTS_HISTORY = [
    {"time": _hm(_now - _dt.timedelta(minutes=52)),  "title": "ضربان قلب بالا — مهدی کریمی",
     "result": "بسته شد — تماس با سرشیفت"},
    {"time": _hm(_now - _dt.timedelta(minutes=125)), "title": "خروج از محدودهٔ مجاز — اکبر رحیمی",
     "result": "بازگشت به سالن تولید ۱"},
    {"time": _hm(_now - _dt.timedelta(minutes=200)), "title": "افت باتری مچ‌بند — حسین یوسفی",
     "result": "تعویض باتری — تحویل از انبار"},
    {"time": _hm(_now - _dt.timedelta(minutes=250)), "title": "ضربان پایین — کاظم شریفی",
     "result": "بررسی حضوری — وضعیت عادی"},
]

# ═══════════ ترددهای امروز (نمونه) ═══════════
TRAFFIC_TODAY = [
    ("ورود به کارخانه", "06:49"),
    ("خروج موقت — نماز و ناهار", "12:30"),
    ("ورود مجدد", "12:58"),
]

# ═══════════ ساعات کار هفته (نمونه) ═══════════
WEEK_HOURS = [
    ("شنبه", 8.5), ("یکشنبه", 8.9), ("دوشنبه", 8.2), ("سه‌شنبه", 8.6),
    ("چهارشنبه", 8.4), ("پنجشنبه", 7.5), ("جمعه", 0.0),
]


def kpis():
    """شاخص‌های کلیدی داشبورد — از داده‌های نمونه محاسبه می‌شود."""
    present = sum(1 for e in EMPLOYEES if e["present"])
    present_now = sum(1 for e in EMPLOYEES if e["present"] and e["status"] != "off")
    warn = sum(1 for e in EMPLOYEES if e["status"] == "warn")
    danger = sum(1 for e in EMPLOYEES if e["status"] == "danger")
    off = sum(1 for e in EMPLOYEES if e["status"] == "off")
    hrs = [e["hr"] for e in EMPLOYEES if e["hr"]]
    avg_hr = round(sum(hrs) / len(hrs)) if hrs else 0
    return {
        "present": present_now, "total": len(EMPLOYEES),
        "warn": warn, "danger": danger, "off": off, "avg_hr": avg_hr,
    }


def dept_summary():
    """خلاصهٔ وضعیت به تفکیک واحد — برای صفحهٔ گزارش‌ها."""
    out = {}
    for e in EMPLOYEES:
        d = out.setdefault(e["dept"], {"n": 0, "min": 0, "inc": 0})
        d["n"] += 1
        d["min"] += e["work_min"]
        if e["status"] == "danger":
            d["inc"] += 1
    rows = []
    for name, d in out.items():
        rows.append({
            "dept": name, "n": d["n"],
            "avg_h": round(d["min"] / d["n"] / 60, 1) if d["n"] else 0,
            "inc": d["inc"],
        })
    return sorted(rows, key=lambda r: -r["n"])


def attendance_summary():
    """شاخص‌های حضور و غیاب امروز — برای صفحهٔ حضور و غیاب."""
    att = [e["attendance"] for e in EMPLOYEES]
    entered = [a for a in att if a["entered"]]
    return {
        "total": len(EMPLOYEES),
        "present": sum(1 for a in att if a["status"] == "present"),
        "left": sum(1 for a in att if a["status"] == "left"),
        "leave": sum(1 for a in att if a["status"] == "leave"),
        "absent": sum(1 for a in att if a["status"] == "absent"),
        "late": sum(1 for a in att if a["late_min"] > 0),
        "avg_min": round(sum(a["work_min"] for a in entered) / len(entered)) if entered else 0,
    }


def zone_usage():
    """مجموع دقایق حضور همهٔ کارکنان در هر منطقه — امروز."""
    tot = {}
    for e in EMPLOYEES:
        for zone, mins in e["attendance"]["zone_totals"]:
            tot[zone] = tot.get(zone, 0) + mins
    return sorted(tot.items(), key=lambda kv: -kv[1])
