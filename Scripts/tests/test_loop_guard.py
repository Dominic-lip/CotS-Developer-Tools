#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import CotSLoopGuard as loop
import CotSWatchdog24x7Final as final_watchdog


class LoopGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.old_state = loop.STATE
        loop.STATE = Path(self.temp.name) / "loop-guard.json"

    def tearDown(self) -> None:
        loop.STATE = self.old_state
        self.temp.cleanup()

    @staticmethod
    def gate() -> dict:
        return {
            "state": "RECOVERABLE_GATE",
            "task": "TASK-015",
            "phase": "production-bootstrap-reconcile",
            "recoverable_gate": {
                "category": "RECOVERABLE_SUPERVISOR",
                "reason": "TASK-015 has no configured production lifecycle adapter.",
                "recommended_action": "configure production lifecycle adapter",
            },
        }

    @staticmethod
    def evidence(**changes: object) -> dict:
        value = {
            "head": "abc",
            "working_tree": "clean",
            "task": "TASK-015",
            "phase": "production-bootstrap-reconcile",
            "targeted_tests": 0,
            "full_suites": 0,
            "validation_count": 0,
            "acceptance_remaining": 3,
        }
        value.update(changes)
        return value

    def test_identical_gate_blocks_on_second_unchanged_observation(self):
        guard = loop.LoopGuard(threshold=2)
        evidence = self.evidence()
        first = guard.observe(self.gate(), evidence, evidence)
        second = guard.observe(self.gate(), evidence, evidence)
        self.assertFalse(first["blocked"])
        self.assertTrue(second["blocked"])
        self.assertEqual(second["repeat_count"], 2)
        self.assertEqual(second["blocked_kind"], "configuration")

    def test_durable_change_prevents_repeat_block(self):
        guard = loop.LoopGuard(threshold=2)
        before = self.evidence()
        guard.observe(self.gate(), before, before)
        after = self.evidence(head="def")
        decision = guard.observe(self.gate(), before, after)
        self.assertFalse(decision["blocked"])
        self.assertTrue(decision["durable_progress"])
        self.assertIn("commit", decision["progress_reasons"])

    def test_provider_turn_activity_is_not_durable_progress(self):
        before = self.evidence()
        after = dict(before)
        progressed, reasons = loop.durable_progress(before, after)
        self.assertFalse(progressed)
        self.assertEqual(reasons, [])

    def test_acceptance_reduction_counts_as_durable_progress(self):
        progressed, reasons = loop.durable_progress(self.evidence(acceptance_remaining=3), self.evidence(acceptance_remaining=2))
        self.assertTrue(progressed)
        self.assertIn("acceptance_reduced", reasons)

    def test_configuration_like_matches_task015_adapter_gate(self):
        self.assertTrue(loop.configuration_like("TASK-015 has no configured production lifecycle adapter."))

    def test_condition_changed_requires_evidence_or_gate_change(self):
        guard = loop.LoopGuard(threshold=2)
        evidence = self.evidence()
        guard.observe(self.gate(), evidence, evidence)
        guard.observe(self.gate(), evidence, evidence)
        with mock.patch.object(loop, "durable_evidence", return_value=evidence), mock.patch.object(loop, "gate_descriptor", return_value=loop.gate_descriptor(self.gate())):
            self.assertFalse(guard.condition_changed(self.gate()))
        changed = self.evidence(head="new")
        with mock.patch.object(loop, "durable_evidence", return_value=changed), mock.patch.object(loop, "gate_descriptor", return_value=loop.gate_descriptor(self.gate())):
            self.assertTrue(guard.condition_changed(self.gate()))

    def test_task101_server_engine_gate_is_hard_prerequisite(self):
        decision = {
            "blocked_kind": "repeated_gate",
            "gate": {
                "category": "RECOVERABLE_UNREAL_LIFECYCLE",
                "reason": "UE all-platform SDK validation fails before worker discovery, and the same engine distribution does not support Server targets.",
                "task": "TASK-101",
                "phase": "networked-automation-engine-gate",
            },
        }
        self.assertTrue(final_watchdog.hard_prerequisite_gate(decision))

    def test_run_resume_cannot_force_hard_prerequisite_but_restart_can(self):
        decision = {
            "blocked_kind": "repeated_gate",
            "gate": {
                "category": "RECOVERABLE_UNREAL_LIFECYCLE",
                "reason": "No server-capable UE installation or SDK metadata repair has been exposed.",
                "task": "TASK-101",
            },
        }
        self.assertFalse(final_watchdog.operator_override_allowed(decision, "resume"))
        self.assertTrue(final_watchdog.operator_override_allowed(decision, "restart"))


if __name__ == "__main__":
    unittest.main()
