"""Serve the existing application for the local Cloudflare tunnel."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import run_app

if __name__ == "__main__":
    run_app(web=True)
