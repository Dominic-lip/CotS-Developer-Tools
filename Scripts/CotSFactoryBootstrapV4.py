#!/usr/bin/env python3
"""V4 bootstrap entry point: proven recovery loop, V4 Factory controller."""
from __future__ import annotations

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import CotSFactoryBootstrap as legacy

legacy.FACTORY = SCRIPT_DIR / "CotSFactoryControllerV4.py"

if __name__ == "__main__":
    raise SystemExit(legacy.run())
