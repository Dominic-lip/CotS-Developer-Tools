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
import CotSFactoryController24x7 as fac24


class TestTask116Scheduler(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sup24.install_hardening()

    def test_checked_in_state_schedules_task_117(self) -> None:
        self.assertEqual(sup24.base.next_required_task(), "TASK-117")
        instruction = sup24.hardened_scheduled_task_instruction()
        self.assertIn("TASK-117", instruction)
        self.assertEqual(fac24.hardened_authoritative_next_required_task(), "TASK-117")

    def test_task_116_does_not_receive_production_mutation_bridge(self) -> None:
        self.assertFalse(sup24._production_task("TASK-116"))
        instruction = sup24.hardened_scheduled_task_instruction("TASK-116")
        self.assertNotIn("explicit authorization to modify C:\\Dev\\CotS", instruction)
        self.assertTrue(sup24._production_task("TASK-115"))

    def test_loader_accepts_reviewed_task_121_boundary(self) -> None:
        document = sup24.hardened_load_foundation_completion_state()
        self.assertEqual(document["tasks"][-1]["id"], "TASK-121")
        self.assertEqual(document["tasks"][-1]["status"], "NOT_STARTED")
        task_116 = next(task for task in document["tasks"] if task["id"] == "TASK-116")
        self.assertEqual(task_116["status"], "COMPLETE_VERIFIED")
        self.assertTrue(task_116["evidence"])

    def test_loader_rejects_missing_task_116(self) -> None:
        document = json.loads(sup24.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"] = [entry for entry in document["tasks"] if entry["id"] != "TASK-116"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup24.base.AppServerError):
                sup24.hardened_load_foundation_completion_state(path)

    def test_loader_rejects_unreviewed_task_122(self) -> None:
        document = json.loads(sup24.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"].append({"id": "TASK-122", "status": "NOT_STARTED"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup24.base.AppServerError):
                sup24.hardened_load_foundation_completion_state(path)

    def test_verified_task_116_requires_durable_evidence(self) -> None:
        document = json.loads(sup24.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"] = [task for task in document["tasks"] if task["id"] != "TASK-116"]
        document["tasks"].append({"id": "TASK-116", "status": "COMPLETE_VERIFIED"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup24.base.AppServerError):
                sup24.hardened_load_foundation_completion_state(path)

    def test_completed_checkpoint_is_reconciled_to_task_117(self) -> None:
        checkpoint = {
            "state": "GOVERNOR_PAUSED",
            "task": "TASK-013",
            "phase": "PROVIDER_ACCEPTANCE_PROOF",
            "scheduled_task": "TASK-117",
            "active_task_override": "TASK-013",
            "active_agent": "codex",
            "pending_handoff_target": "claude",
            "turn_count": 41,
            "compact_task_context": {"task_id": "TASK-013", "phase": "PROVIDER_ACCEPTANCE_PROOF"},
            "codex": {"status": "ACTIVE", "thread_id": "old-codex-thread", "reset_at": None},
            "claude": {"status": "IDLE", "session_id": "old-claude-session"},
            "deferred_verifications": [
                {"task_id": "TASK-013", "required_provider": "claude"},
            ],
            "human_gate": "old gate",
            "failure": "old failure",
        }
        reconciled, changed = fac24.reconcile_completed_checkpoint(checkpoint)
        self.assertTrue(changed)
        self.assertEqual(reconciled["state"], "STARTING")
        self.assertEqual(reconciled["task"], "TASK-117")
        self.assertEqual(reconciled["phase"], "RECONCILING")
        self.assertEqual(reconciled["scheduled_task"], "TASK-117")
        self.assertEqual(reconciled["turn_count"], 41)
        self.assertIsNone(reconciled["active_agent"])
        self.assertIsNone(reconciled["pending_handoff_target"])
        self.assertIsNone(reconciled["active_task_override"])
        self.assertNotIn("thread_id", reconciled["codex"])
        self.assertNotIn("session_id", reconciled["claude"])
        self.assertEqual(reconciled["deferred_verifications"], [])
        self.assertNotIn("human_gate", reconciled)
        self.assertNotIn("failure", reconciled)
        self.assertEqual(reconciled["compact_task_context"]["task_id"], "TASK-117")

    def test_current_incomplete_checkpoint_is_preserved(self) -> None:
        checkpoint = {
            "state": "RUNNING_CODEX",
            "task": "TASK-117",
            "phase": "source inventory",
            "active_agent": "codex",
            "compact_task_context": {"task_id": "TASK-117", "phase": "source inventory"},
            "codex": {"status": "ACTIVE", "thread_id": "current-thread"},
        }
        reconciled, changed = fac24.reconcile_completed_checkpoint(checkpoint)
        self.assertFalse(changed)
        self.assertEqual(reconciled, checkpoint)


if __name__ == "__main__":
    unittest.main()
