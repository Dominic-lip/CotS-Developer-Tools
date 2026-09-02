#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import CotSProductionLifecycle as lifecycle


class ProductionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old_production = lifecycle.PRODUCTION
        self.old_project = lifecycle.PROJECT
        self.old_state = lifecycle.STATE_FILE
        self.old_manifest = lifecycle.MANIFEST_DIR
        lifecycle.PRODUCTION = root / "CotS"
        lifecycle.PROJECT = lifecycle.PRODUCTION / "CotS.uproject"
        lifecycle.STATE_FILE = root / "state" / "production-lifecycle.json"
        lifecycle.MANIFEST_DIR = root / "manifests"

    def tearDown(self) -> None:
        lifecycle.PRODUCTION = self.old_production
        lifecycle.PROJECT = self.old_project
        lifecycle.STATE_FILE = self.old_state
        lifecycle.MANIFEST_DIR = self.old_manifest
        self.temp.cleanup()

    def test_path_escape_and_git_metadata_are_refused(self):
        for value in ("../escape.txt", r"C:\\Other\\x.txt", ".git/config"):
            with self.subTest(value=value), self.assertRaises(lifecycle.Refused):
                lifecycle._safe_relpath(value)

    def test_completion_allows_only_the_fixed_task015_binary_map(self):
        lifecycle.PRODUCTION.mkdir(parents=True)
        entry_map = lifecycle.PRODUCTION / "Content" / "Maps" / "CotS_Entry.umap"
        entry_map.parent.mkdir(parents=True)
        entry_map.write_bytes(b"map")
        self.assertEqual(lifecycle._safe_completion_path("Content/Maps/CotS_Entry.umap"), entry_map.resolve())
        with self.assertRaises(lifecycle.Refused):
            lifecycle._safe_completion_path("Content/Maps/Other.umap")

    def test_task015_smoke_is_fixed_and_disables_mcp_only_for_the_commandlet(self):
        self.assertIn("LevelEditorSubsystem", lifecycle.ENTRY_MAP_SMOKE_SCRIPT)
        self.assertTrue(any(
            isinstance(value, str) and "bAutoStartServer=False" in value
            for value in lifecycle.smoke.__code__.co_consts
        ))

    def test_bootstrap_creates_fixed_minimal_project_without_git_side_effect(self):
        result = lifecycle.bootstrap(initialize_git=False)
        self.assertTrue(result["success"])
        self.assertTrue((lifecycle.PRODUCTION / "CotS.uproject").is_file())
        self.assertTrue((lifecycle.PRODUCTION / "Source" / "CotS" / "CotS.cpp").is_file())
        self.assertTrue((lifecycle.PRODUCTION / "Source" / "CotSServer.Target.cs").is_file())
        self.assertIn(
            "BuildSettingsVersion.V7",
            (lifecycle.PRODUCTION / "Source" / "CotSEditor.Target.cs").read_text(encoding="utf-8"),
        )
        descriptor = json.loads((lifecycle.PRODUCTION / "CotS.uproject").read_text(encoding="utf-8"))
        self.assertEqual(
            [plugin["Name"] for plugin in descriptor["Plugins"]],
            ["ModelContextProtocol", "AllToolsets"],
        )
        self.assertTrue((lifecycle.PRODUCTION / "Config" / "DefaultEditorPerProjectUserSettings.ini").is_file())
        self.assertFalse((lifecycle.PRODUCTION / ".git").exists())

    def test_bootstrap_never_overwrites_conflicting_existing_file(self):
        lifecycle.PRODUCTION.mkdir(parents=True)
        target = lifecycle.PRODUCTION / "CotS.uproject"
        target.write_text("custom\n", encoding="utf-8")
        result = lifecycle.bootstrap(initialize_git=False)
        self.assertFalse(result["success"])
        self.assertIn("CotS.uproject", result["conflicts"])
        self.assertEqual(target.read_text(encoding="utf-8"), "custom\n")

    def _write_manifest(self, name: str, value: dict) -> None:
        lifecycle.MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        (lifecycle.MANIFEST_DIR / name).write_text(json.dumps(value), encoding="utf-8")

    def test_manifest_allows_task015_bounded_text_write(self):
        self._write_manifest("task015.json", {
            "task": "TASK-015",
            "files": [{"path": "Source/CotS/Public/CotSBootstrap.h", "content": "#pragma once\n"}],
        })
        result = lifecycle.apply_manifest("task015.json")
        self.assertTrue(result["success"])
        self.assertEqual(result["changed"], ["Source/CotS/Public/CotSBootstrap.h"])
        self.assertTrue((lifecycle.PRODUCTION / "Source" / "CotS" / "Public" / "CotSBootstrap.h").is_file())

    def test_manifest_rejects_unauthorized_task_and_path_escape(self):
        self._write_manifest("bad-task.json", {
            "task": "TASK-099",
            "files": [{"path": "Config/DefaultGame.ini", "content": "x"}],
        })
        with self.assertRaises(lifecycle.Refused):
            lifecycle.apply_manifest("bad-task.json")

        self._write_manifest("bad-path.json", {
            "task": "TASK-015",
            "files": [{"path": "../Shardlands/Nope.txt", "content": "x"}],
        })
        with self.assertRaises(lifecycle.Refused):
            lifecycle.apply_manifest("bad-path.json")

    def test_manifest_normalize_eof_preserves_content(self):
        lifecycle.PRODUCTION.mkdir(parents=True)
        target = lifecycle.PRODUCTION / "Config" / "DefaultInput.ini"
        target.parent.mkdir()
        target.write_text("[Input]\nValue=True\n\n", encoding="utf-8")
        self._write_manifest("normalize.json", {
            "task": "TASK-015",
            "files": [{"path": "Config/DefaultInput.ini", "mode": "normalize_eof"}],
        })
        result = lifecycle.apply_manifest("normalize.json")
        self.assertEqual(result["changed"], ["Config/DefaultInput.ini"])
        self.assertEqual(target.read_text(encoding="utf-8"), "[Input]\nValue=True\n")

    def test_mcp_diagnostics_reports_fixed_project_configuration(self):
        lifecycle.bootstrap(initialize_git=False)
        result = lifecycle.mcp_diagnostics()
        self.assertEqual(result["enabled_plugins"], ["AllToolsets", "ModelContextProtocol"])
        self.assertTrue(result["settings_exists"])
        self.assertEqual(result["server_url_path"], "/mcp")
        self.assertTrue(result["auto_start_server"])

    def test_manifest_filename_itself_is_bounded(self):
        with self.assertRaises(lifecycle.Refused):
            lifecycle._manifest_path("../outside.json")


if __name__ == "__main__":
    unittest.main()
