"""Keep windowed PyInstaller apps compatible with loggers that expect streams."""
from __future__ import annotations

import os
import sys


def _null_stream(name: str):
    if getattr(sys, name, None) is None:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))


_null_stream("stdout")
_null_stream("stderr")
