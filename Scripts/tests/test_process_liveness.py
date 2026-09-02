from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from CotSProcessLiveness import process_live


class ProcessLivenessTests(unittest.TestCase):
    def test_current_process_is_live(self) -> None:
        self.assertTrue(process_live(os.getpid()))

    def test_invalid_process_ids_are_not_live(self) -> None:
        self.assertFalse(process_live(None))
        self.assertFalse(process_live(0))
        self.assertFalse(process_live(-1))
        self.assertFalse(process_live(True))

    def test_impossible_process_id_is_nonfatal(self) -> None:
        # Maximum 32-bit unsigned PID-shaped value. Windows OpenProcess and POSIX
        # kill probes should simply report it absent, never raise into the runtime.
        self.assertFalse(process_live(0xFFFFFFFF))

    def test_production_control_center_uses_safe_probe(self) -> None:
        import CotSControlCenter24x7Final as final

        self.assertIs(final.enhanced.pid_live, process_live)
        self.assertFalse(final.enhanced.pid_live(0xFFFFFFFF))


if __name__ == "__main__":
    unittest.main()
