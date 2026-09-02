from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

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

    def test_tailscale_auto_serve_uses_only_private_local_telemetry_target(self) -> None:
        import CotSControlCenter24x7Final as final

        completed = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(final, "tailscale_executable", return_value=r"C:\Program Files\Tailscale\tailscale.exe"), \
             mock.patch.object(final.subprocess, "run", side_effect=[completed, completed]) as run:
            result = final.ensure_tailscale_serve()

        self.assertTrue(result["success"])
        self.assertEqual(final.TAILSCALE_TARGET, "http://127.0.0.1:8765")
        self.assertEqual(run.call_args_list[0].args[0][1:], ["status"])
        self.assertEqual(
            run.call_args_list[1].args[0][1:],
            ["serve", "--bg", "http://127.0.0.1:8765"],
        )

    def test_tailscale_disable_turns_off_serve_not_tailnet(self) -> None:
        import CotSControlCenter24x7Final as final

        completed = mock.Mock(returncode=0, stdout="off", stderr="")
        with mock.patch.object(final, "tailscale_executable", return_value=r"C:\Program Files\Tailscale\tailscale.exe"), \
             mock.patch.object(final.subprocess, "run", return_value=completed) as run:
            result = final.disable_tailscale_serve()

        self.assertTrue(result["success"])
        self.assertEqual(result["state"], "disabled")
        self.assertEqual(run.call_args.args[0][1:], ["serve", "off"])
        self.assertNotIn("down", run.call_args.args[0])

    def test_missing_tailscale_never_blocks_control_center_startup(self) -> None:
        import CotSControlCenter24x7Final as final

        with mock.patch.object(final, "tailscale_executable", return_value=None):
            result = final.ensure_tailscale_serve()
        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "not_installed")


if __name__ == "__main__":
    unittest.main()
