#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import CotSCreateBootstrapMap as bootstrap_map


class ProductionMapBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_production = bootstrap_map.PRODUCTION
        self.old_project = bootstrap_map.PROJECT
        self.old_map = bootstrap_map.MAP_FILE
        self.old_editor = bootstrap_map.EDITOR_CMD
        self.old_state = bootstrap_map.STATE_FILE
        bootstrap_map.PRODUCTION = root / "CotS"
        bootstrap_map.PROJECT = bootstrap_map.PRODUCTION / "CotS.uproject"
        bootstrap_map.MAP_FILE = bootstrap_map.PRODUCTION / "Content" / "Maps" / "CotS_Entry.umap"
        bootstrap_map.EDITOR_CMD = root / "UE_5.8" / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
        bootstrap_map.STATE_FILE = root / "state" / "map.json"

    def tearDown(self) -> None:
        bootstrap_map.PRODUCTION = self.old_production
        bootstrap_map.PROJECT = self.old_project
        bootstrap_map.MAP_FILE = self.old_map
        bootstrap_map.EDITOR_CMD = self.old_editor
        bootstrap_map.STATE_FILE = self.old_state
        self.temp.cleanup()

    def _prerequisites(self) -> None:
        bootstrap_map.PRODUCTION.mkdir(parents=True, exist_ok=True)
        bootstrap_map.PROJECT.write_text("{}\n", encoding="utf-8")
        bootstrap_map.EDITOR_CMD.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_map.EDITOR_CMD.write_text("stub\n", encoding="utf-8")

    def test_command_is_fixed_to_cots_entry_map(self) -> None:
        command = bootstrap_map.build_command()
        self.assertEqual(command[0], str(bootstrap_map.EDITOR_CMD))
        self.assertEqual(command[1], str(bootstrap_map.PROJECT))
        exec_arg = next(arg for arg in command if arg.startswith("-ExecCmds="))
        self.assertIn("MAP NEW", exec_arg)
        self.assertIn("MAP SAVE FILE=", exec_arg)
        self.assertIn(bootstrap_map.MAP_FILE.as_posix(), exec_arg)
        self.assertIn("QUIT", exec_arg)

    def test_existing_map_is_idempotent_and_spawns_nothing(self) -> None:
        self._prerequisites()
        bootstrap_map.MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_map.MAP_FILE.write_bytes(b"existing")
        with mock.patch.object(bootstrap_map.subprocess, "run") as run:
            result = bootstrap_map.create_bootstrap_map()
        self.assertTrue(result["success"])
        self.assertFalse(result["changed"])
        run.assert_not_called()

    def test_success_requires_durable_map_file(self) -> None:
        self._prerequisites()

        def fake_run(*_args, **_kwargs):
            bootstrap_map.MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            bootstrap_map.MAP_FILE.write_bytes(b"umap")
            return mock.Mock(returncode=0, stdout="created", stderr="")

        with mock.patch.object(bootstrap_map.subprocess, "run", side_effect=fake_run):
            result = bootstrap_map.create_bootstrap_map()
        self.assertTrue(result["success"])
        self.assertTrue(result["changed"])
        self.assertTrue(bootstrap_map.MAP_FILE.is_file())

    def test_zero_exit_without_map_is_failure(self) -> None:
        self._prerequisites()
        completed = mock.Mock(returncode=0, stdout="no map", stderr="")
        with mock.patch.object(bootstrap_map.subprocess, "run", return_value=completed):
            result = bootstrap_map.create_bootstrap_map()
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "bootstrap_map_not_created")


if __name__ == "__main__":
    unittest.main()
