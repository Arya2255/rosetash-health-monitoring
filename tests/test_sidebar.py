"""Focused regression checks for the shared desktop and mobile sidebar."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from components.sidebar import NAV_ITEMS, build_drawer, build_sidebar
import main as app_main


def collect_text(control):
    result = []
    value = getattr(control, "value", None)
    if isinstance(value, str):
        result.append(value)
    content = getattr(control, "content", None)
    if content is not None:
        if isinstance(content, str):
            result.append(content)
        else:
            result.extend(collect_text(content))
    for child in getattr(control, "controls", None) or []:
        result.extend(collect_text(child))
    return result


def main():
    removed = {"reports": "گزارش‌ها", "management": "مدیریت"}
    navigation_keys = {key for key, _label, _icon in NAV_ITEMS}
    for key in removed:
        assert key not in navigation_keys, f"removed page remains in navigation: {key}"
        assert key not in app_main.BUILDERS, f"removed page remains routable: {key}"
        assert not (ROOT / "src/views" / f"{key}.py").exists(), f"removed page module remains: {key}"
    for name, control in (
        ("desktop sidebar", build_sidebar("employees", lambda _key: None, role="owner")),
        ("mobile drawer", build_drawer("employees", lambda _key: None, role="owner")),
    ):
        text = "\n".join(collect_text(control))
        assert "مهندس رستگاری" not in text, f"obsolete profile remains in {name}"
        assert "مسئول HSE" not in text, f"obsolete role remains in {name}"
        assert "کارکنان" in text, f"navigation missing from {name}"
        assert "تنظیمات" in text, f"settings navigation missing from {name}"
        for label in removed.values():
            assert label not in text, f"removed page remains visible in {name}: {label}"
        print(f"OK — {name}: obsolete profile and removed pages absent")


if __name__ == "__main__":
    main()
