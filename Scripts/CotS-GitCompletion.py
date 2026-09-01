#!/usr/bin/env python3
"""Compatibility entry point for the V4 profile-aware Git completion helper."""
from __future__ import annotations

from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("CotS-GitCompletionV4.py")), run_name="__main__")
