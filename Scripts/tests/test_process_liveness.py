from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from CotSProcessLiveness import process_live


def test_current_process_is_live() -> None:
    assert process_live(os.getpid()) is True


def test_invalid_process_ids_are_not_live() -> None:
    assert process_live(None) is False
    assert process_live(0) is False
    assert process_live(-1) is False
    assert process_live(True) is False


def test_impossible_process_id_is_nonfatal() -> None:
    # Maximum 32-bit unsigned PID-shaped value. Windows OpenProcess and POSIX
    # kill probes should simply report it absent, never raise into the watchdog.
    assert process_live(0xFFFFFFFF) is False
