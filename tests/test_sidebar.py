"""Focused regression checks for the shared desktop and mobile sidebar."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from components.sidebar import build_drawer, build_sidebar


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
    for name, control in (
        ("desktop sidebar", build_sidebar("reports", lambda _key: None)),
        ("mobile drawer", build_drawer("reports", lambda _key: None)),
    ):
        text = "\n".join(collect_text(control))
        assert "مهندس رستگاری" not in text, f"obsolete profile remains in {name}"
        assert "مسئول HSE" not in text, f"obsolete role remains in {name}"
        assert "گزارش‌ها" in text, f"navigation missing from {name}"
        print(f"OK — {name}: obsolete profile removed")


if __name__ == "__main__":
    main()
