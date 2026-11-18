"""Keep bridge replies alive when the Windows service console uses a legacy codec."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import bridge


class Cp1252Console:
    encoding = "cp1252"

    def __init__(self):
        self.parts = []

    def write(self, value):
        value.encode(self.encoding)  # Simulate the active Windows stdout codec.
        self.parts.append(value)
        return len(value)

    def flush(self):
        pass


class BridgeConsoleEncodingTests(unittest.TestCase):
    def test_persian_audit_message_does_not_raise_on_legacy_windows_console(self):
        console = Cp1252Console()
        with patch.object(bridge.sys, "stdout", console):
            bridge.log("پایش کارکن تغییر کرد — رضا")
        output = "".join(console.parts)
        self.assertIn(r"\u067e", output)
        self.assertIn(r"\u0631", output)


if __name__ == "__main__":
    unittest.main()
