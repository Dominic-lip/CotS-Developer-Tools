#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import CotSAgentSupervisorCampaign as sup
import CotSFactoryControllerCampaign as fac
import CotSProductionLifecycleCampaign as life
import CotSWatchdogCampaign as watch


class TestContinuousCampaign(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sup.install_campaign()
        sup.h.install_hardening()
        fac.install_campaign()
        life.install_campaign()

    def test_scheduler_advances_to_117(self) -> None:
        self.assertEqual(sup.h.base.next_required_task(), "TASK-117")
        self.assertEqual(fac.campaign_next_required_task(), "TASK-117")

    def test_campaign_tasks_are_production_authorized(self) -> None:
        for task in range(117, 122):
            self.assertTrue(sup.campaign_production_task(f"TASK-{task}"))
            self.assertIn(f"TASK-{task}", life.base.ALLOWED_TASKS)
        self.assertFalse(sup.campaign_production_task("TASK-122"))

    def test_shardlands_is_not_a_production_target(self) -> None:
        self.assertEqual(str(life.base.PRODUCTION), r"C:\Dev\CotS")
        self.assertNotIn("Shardlands", str(life.base.PRODUCTION))

    def test_task_specs_exist(self) -> None:
        expected = {
            117: "117_OPERATIONS_OBSERVABILITY_REGIONAL_DIAGNOSTICS.md",
            118: "118_SCALE_SOAK_RECOVERY_GATE.md",
            119: "119_PLATFORM_INTEGRATION_SECURITY.md",
            120: "120_LOCAL_VOICE_PRIVACY.md",
            121: "121_PERSISTENT_STREAMED_WORLD_SLICE.md",
        }
        for filename in expected.values():
            self.assertTrue((REPO / "Tasks" / filename).is_file(), filename)

    def test_campaign_is_not_complete_while_117_is_pending(self) -> None:
        self.assertFalse(watch.campaign_complete())

    def test_complete_checkpoint_is_preserved(self) -> None:
        checkpoint = {"state": "COMPLETE", "task": "TASK-121", "active_agent": "codex", "codex": {"status": "ACTIVE"}}
        # Test the policy primitive without writing the real state file.
        cleaned = fac.h.base.clear_provider_activity(checkpoint, state="COMPLETE")
        self.assertEqual(cleaned["state"], "COMPLETE")
        self.assertIsNone(cleaned["active_agent"])


if __name__ == "__main__":
    unittest.main()
