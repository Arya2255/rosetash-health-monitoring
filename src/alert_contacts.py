"""Responsible employees are selected by explicit groups and exact unit scope."""
from __future__ import annotations
import re

_GROUP_PRIORITY = {'shift_leader': 0, 'supervisor': 1, 'hse': 2}
_GROUP_LABELS = {'shift_leader': 'سرشیفت', 'supervisor': 'سرپرست', 'hse': 'واحد ایمنی'}
_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
_MAC = re.compile(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\Z')


def _norm(value):
    text = str(value or '').casefold().translate(_DIGITS)
    return ' '.join(text.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ').split())


def _group(person):
    # Free-text job titles never grant an emergency recipient role.
    return person.get('staff_group') if person.get('staff_group') in _GROUP_PRIORITY else ''


def _valid(person):
    return (isinstance(person, dict) and person.get('registered') is True
            and isinstance(person.get('mac'), str) and bool(_MAC.fullmatch(person['mac'])))


def _scope(alert):
    parts = re.split(r'\s+[—–•]\s+|\s+-\s+', str(alert.get('dept') or alert.get('unit') or ''), maxsplit=1)
    return _norm(parts[0]), _norm(alert.get('line') or (parts[1] if len(parts) > 1 else ''))


def _match_score(alert, person, group):
    unit, line = _scope(alert)
    dept, target_line = _norm(person.get('dept')), _norm(person.get('line'))
    if not unit:
        return None
    company = _norm(alert.get('company'))
    if company and _norm(person.get('company')) != company:
        return None
    if dept != unit:
        if not (group == 'hse' and dept in ('hse', 'واحد hse') and target_line == unit):
            return None
        return 2
    if line and target_line and line != target_line:
        return None
    return 0 if line and target_line == line else 1


def hse_contacts(employees):
    seen = {}
    for person in employees or []:
        if _valid(person) and _group(person) == 'hse':
            mac = person['mac'].lower()
            seen.setdefault(mac, {**person, 'mac': mac, 'contact_group': 'hse',
                                  'contact_label': _GROUP_LABELS['hse']})
    return list(seen.values())


def resolve_alert_contact(alert, employees, *, groups=None):
    groups = groups or tuple(_GROUP_PRIORITY)
    source_mac = str(alert.get('mac') or alert.get('source_mac') or '').lower()
    candidates = []
    for person in employees or []:
        if not _valid(person) or person.get('present') is not True:
            continue
        if person['mac'].lower() == source_mac:
            continue
        group = _group(person)
        if group not in groups:
            continue
        if person.get('scan_paused') or person.get('scan_allowed') is False:
            continue
        score = _match_score(alert, person, group)
        if score is not None:
            candidates.append((_GROUP_PRIORITY[group], score, person['mac'].lower(), person, group))
    if not candidates:
        return None
    _, _, mac, person, group = min(candidates, key=lambda item: item[:3])
    return {**person, 'mac': mac, 'contact_group': group, 'contact_label': _GROUP_LABELS[group]}


def alert_recipients(source, employees):
    """All HSE, plus the local shift lead/supervisor for an ordinary worker."""
    recipients = {p['mac']: p for p in hse_contacts(employees)}
    if source.get('staff_group', 'employee') == 'employee':
        local = resolve_alert_contact(source, employees, groups=('shift_leader', 'supervisor'))
        if local:
            recipients.setdefault(local['mac'], local)
    return list(recipients.values())
