# -*- coding: utf-8 -*-
"""اجرای نمونهٔ اولیه از ریشهٔ پروژه.

دستورهای استاندارد:
    uv run flet run
    uv run flet run --web --port 8550
"""

import os
import runpy

_HERE = os.path.dirname(os.path.abspath(__file__))
runpy.run_path(os.path.join(_HERE, "src", "main.py"), run_name="__main__")
