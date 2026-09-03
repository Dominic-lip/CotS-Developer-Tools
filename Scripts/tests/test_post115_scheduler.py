#!/usr/bin/env python3
"""Focused regression tests for the post-TASK-115 scheduling boundary."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import CotSAgentSupervisor24x7 as sup24


class TestTask116Scheduler(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sup24.install_hardening()

    def test_checked_in_state_schedules_task_116(self) -> None:
        self.assertEqual(sup24.base.next_required_task(), "TASK-116")
        instruction = sup24.hardened_scheduled_task_instruction()
        self.assertIn("TASK-116", instruction)

    def test_task_116_does_not_receive_production_mutation_bridge(self) -> None:
        self.assertFalse(sup24._production_task("TASK-116"))
        instruction = sup24.hardened_scheduled_task_instruction("TASK-116")
        self.assertNotIn("explicit authorization to modify C:\\Dev\\CotS", instruction)
        self.assertTrue(sup24._production_task("TASK-115"))

    def test_loader_accepts_exact_task_116_boundary(self) -> None:
        document = sup24.hardened_load_foundation_completion_state()
        self.assertEqual(document["tasks"][-1]["id"], "TASK-116")
        self.assertEqual(document["tasks"][-1]["status"], "NOT_STARTED")

    def test_loader_rejects_missing_task_116(self) -> None:
        document = json.loads(sup24.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"] = [entry for entry in document["tasks"] if entry["id"] != "TASK-116"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup24.base.AppServerError):
                sup24.hardened_load_foundation_completion_state(path)

    def test_loader_rejects_unreviewed_task_117(self) -> None:
        document = json.loads(sup24.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"].append({"id": "TASK-117", "status": "NOT_STARTED"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup24.base.AppServerError):
                sup24.hardened_load_foundation_completion_state(path)

    def test_verified_task_116_requires_durable_evidence(self) -> None:
        document = json.loads(sup24.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"][-1] = {"id": "TASK-116", "status": "COMPLETE_VERIFIED"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup24.base.AppServerError):
                sup24.hardened_load_foundation_completion_state(path)


if __name__ == "__main__":
    unittest.main()
