#!/usr/bin/env python3
"""Regression tests for the reviewed post-TASK-115 continuous campaign."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import CotSAgentSupervisorCampaign as sup
import CotSFactoryControllerCampaign as fac


class TestPost115CampaignScheduler(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sup.install_campaign()
        sup.h.install_hardening()
        fac.install_campaign()

    def test_checked_in_state_schedules_task_117(self) -> None:
        self.assertEqual(sup.h.base.next_required_task(), "TASK-117")
        self.assertEqual(fac.campaign_next_required_task(), "TASK-117")

    def test_campaign_production_authorization_is_bounded(self) -> None:
        self.assertFalse(sup.campaign_production_task("TASK-116"))
        for task in range(117, 122):
            self.assertTrue(sup.campaign_production_task(f"TASK-{task}"))
        self.assertFalse(sup.campaign_production_task("TASK-122"))

    def test_loader_accepts_exact_task_121_boundary(self) -> None:
        document = sup.campaign_load_completion_state()
        self.assertEqual(document["tasks"][-1]["id"], "TASK-121")
        self.assertEqual(document["tasks"][-1]["status"], "NOT_STARTED")

    def test_loader_rejects_missing_campaign_task(self) -> None:
        document = json.loads(sup.h.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"] = [entry for entry in document["tasks"] if entry["id"] != "TASK-119"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup.h.base.AppServerError):
                sup.campaign_load_completion_state(path)

    def test_loader_rejects_unreviewed_task_122(self) -> None:
        document = json.loads(sup.h.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"].append({"id": "TASK-122", "status": "NOT_STARTED"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup.h.base.AppServerError):
                sup.campaign_load_completion_state(path)

    def test_verified_task_requires_durable_evidence(self) -> None:
        document = json.loads(sup.h.base.FOUNDATION_COMPLETION_STATE.read_text(encoding="utf-8"))
        document["tasks"][-1] = {"id": "TASK-121", "status": "COMPLETE_VERIFIED"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(sup.h.base.AppServerError):
                sup.campaign_load_completion_state(path)

    def test_completed_task_116_checkpoint_reconciles_to_117(self) -> None:
        checkpoint = {
            "state": "COMPLETE", "task": "TASK-116", "phase": "complete",
            "scheduled_task": "ROADMAP_COMPLETE", "active_agent": None,
            "compact_task_context": {"task_id": "TASK-116", "phase": "complete"},
            "codex": {"status": "IDLE", "thread_id": "old-thread"},
            "claude": {"status": "IDLE", "session_id": "old-session"},
        }
        reconciled, changed = fac.campaign_reconcile_checkpoint(checkpoint)
        self.assertTrue(changed)
        self.assertEqual(reconciled["task"], "TASK-117")
        self.assertEqual(reconciled["phase"], "RECONCILING")
        self.assertNotIn("thread_id", reconciled["codex"])
        self.assertNotIn("session_id", reconciled["claude"])

    def test_current_117_checkpoint_is_preserved(self) -> None:
        checkpoint = {
            "state": "RUNNING_CODEX", "task": "TASK-117", "phase": "observability",
            "active_agent": "codex",
            "compact_task_context": {"task_id": "TASK-117", "phase": "observability"},
            "codex": {"status": "ACTIVE", "thread_id": "current-thread"},
        }
        reconciled, changed = fac.campaign_reconcile_checkpoint(checkpoint)
        self.assertFalse(changed)
        self.assertEqual(reconciled, checkpoint)


if __name__ == "__main__":
    unittest.main()
