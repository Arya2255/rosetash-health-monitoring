"""Personnel categories are independent of application administrator roles."""
STAFF_GROUPS = (
    ("employee", "کارکن عادی"),
    ("hse", "واحد HSE"),
    ("supervisor", "سرپرست"),
    ("shift_leader", "سرشیفت"),
)
STAFF_GROUP_LABELS = dict(STAFF_GROUPS)
SHIFTS = ("صبح", "عصر", "شب")


def staff_group_label(value):
    return STAFF_GROUP_LABELS.get(value or "employee", STAFF_GROUP_LABELS["employee"])
