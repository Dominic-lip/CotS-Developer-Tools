#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import CotS24x7Common as common
import CotSAgentSupervisor24x7 as hardened
import CotSWatchdog24x7 as watchdog


class TestProviderContextHardening(unittest.TestCase):
    def test_exact_list_in_int_field_crash_shape_is_neutralized(self):
        value = common.sanitize_context({"targeted_tests_run": [], "full_suites_run": 2, "read_fingerprints": []})
        self.assertEqual(value["targeted_tests_run"], 0)
        self.assertEqual(value["full_suites_run"], 2)

    def test_exact_int_in_list_field_crash_shape_is_neutralized(self):
        value = common.sanitize_context({"targeted_tests_run": 1, "read_fingerprints": 0})
        self.assertEqual(value["read_fingerprints"], [])

    def test_numeric_strings_are_accepted_but_arbitrary_shapes_are_not(self):
        value = common.sanitize_context({"targeted_tests_run": "4", "full_suites_run": {"wrong": "shape"}})
        self.assertEqual(value["targeted_tests_run"], 4)
        self.assertEqual(value["full_suites_run"], 0)

    def test_previous_good_value_survives_malformed_new_value(self):
        previous = {"targeted_tests_run": 7, "read_fingerprints": [{"path": "A"}]}
        value = common.sanitize_context({"targeted_tests_run": [], "read_fingerprints": 12}, previous=previous)
        self.assertEqual(value["targeted_tests_run"], 7)
        self.assertEqual(value["read_fingerprints"], [{"path": "A"}])

    def test_hardened_merge_always_returns_safe_shapes(self):
        value = hardened.hardened_merge_compact_context(
            {"targeted_tests_run": 3, "read_fingerprints": [{"path": "A"}]},
            {"targeted_tests_run": [], "read_fingerprints": 99}, "TASK-013", "provider-proof")
        self.assertIsInstance(value["targeted_tests_run"], int)
        self.assertIsInstance(value["read_fingerprints"], list)
        self.assertEqual(value["task_id"], "TASK-013")

    def test_task016_missing_claude_client_gate_becomes_handoff(self):
        text = """SUPERVISOR_OUTCOME: RECOVERABLE_GATE
SUPERVISOR_GATE_CATEGORY: RECOVERABLE_PROVIDER
SUPERVISOR_GATE_REASON: The active App Server capability set contains no Claude adapter or Claude MCP client.
SUPERVISOR_RECOMMENDED_ACTION: Rotate to or expose the Claude adapter.
"""
        kind, detail = hardened.hardened_turn_outcome(text)
        self.assertEqual(kind, "HANDOFF")
        self.assertTrue(detail.startswith("claude:"))

    def test_unrelated_recoverable_gate_is_not_rewritten(self):
        text = """SUPERVISOR_OUTCOME: RECOVERABLE_GATE
SUPERVISOR_GATE_CATEGORY: RECOVERABLE_BUILD_TEST
SUPERVISOR_GATE_REASON: Canonical build failed.
SUPERVISOR_RECOMMENDED_ACTION: Inspect the bounded build failure.
"""
        kind, detail = hardened.hardened_turn_outcome(text)
        self.assertEqual(kind, "RECOVERABLE_GATE")
        self.assertIn("RECOVERABLE_BUILD_TEST", detail)


class TestProgressAndQuotaGuard(unittest.TestCase):
    def test_commit_or_turn_is_meaningful_progress(self):
        self.assertTrue(common.meaningful_progress({"head":"a","turn_count":1},{"head":"b","turn_count":1}))
        self.assertTrue(common.meaningful_progress({"head":"a","turn_count":1},{"head":"a","turn_count":2}))

    def test_no_change_is_not_progress(self):
        value={"head":"a","turn_count":1,"task":"TASK-013","phase":"x"}
        self.assertFalse(common.meaningful_progress(value,dict(value)))

    def test_false_human_gate_is_recoverable(self):
        self.assertFalse(watchdog.Watchdog._is_true_human_gate("TypeError: int() argument must not be a list"))
        self.assertTrue(watchdog.Watchdog._is_true_human_gate("Authentication required: complete MFA login"))


class TestLocalTelemetry(unittest.TestCase):
    def test_daily_log_is_local_file_io_only(self):
        with tempfile.TemporaryDirectory() as directory:
            old=common.TELEMETRY_DIR; common.TELEMETRY_DIR=Path(directory)
            try:
                telemetry=common.DailyTelemetry(); telemetry.emit("TEST","hello"); days=telemetry.list_days()
                self.assertEqual(len(days),1); self.assertIn("TEST: hello",telemetry.read_day(days[0]))
            finally: common.TELEMETRY_DIR=old


if __name__ == "__main__": unittest.main()
