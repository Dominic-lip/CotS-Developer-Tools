#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import CotSHardwareTelemetry as hardware
import CotSLocalAI as local_ai
import CotSOperationalMetrics as metrics
import CotSProductivityGovernor as governor
import CotSRollbackGuard as rollback
import CotSUsageLedger as usage


class TestQuotaParsing(unittest.TestCase):
    def test_clock_reset_message_is_parsed_locally(self):
        # 2026-09-01 01:00 local -> same-day 04:22 is in the future.
        now = time.mktime((2026, 9, 1, 1, 0, 0, 0, 0, -1))
        reset = usage.parse_reset_from_message("You've hit your usage limit; try again at 4:22 AM.", now)
        self.assertIsNotNone(reset)
        local = time.localtime(reset)
        self.assertEqual((local.tm_hour, local.tm_min), (4, 22))

    def test_rate_window_remaining_is_derived_without_invention(self):
        value = usage._normalize_window("Primary", {"usedPercent": 63.5, "resetAt": 1900000000})
        self.assertAlmostEqual(value["remaining_percent"], 36.5)
        self.assertEqual(value["reset_at"], 1900000000)

    def test_missing_window_percentage_stays_unknown(self):
        value = usage._normalize_window("Primary", {"resetAt": 1900000000})
        self.assertIsNone(value["used_percent"])
        self.assertIsNone(value["remaining_percent"])


class TestProductivityGovernor(unittest.TestCase):
    def test_four_no_evidence_turns_trip_governor(self):
        with tempfile.TemporaryDirectory() as directory:
            old_state = governor.STATE
            governor.STATE = Path(directory) / "governor.json"
            evidence = {"head":"a","working_tree":"x","targeted_tests":0,"full_suites":0,"validation_count":0,"acceptance_remaining":1,"last_successful_gate":None,"task":"TASK-013","phase":"x"}
            try:
                with mock.patch.object(governor, "read_json", return_value={"turn_count":0}), mock.patch.object(governor, "evidence_signature", return_value=dict(evidence)):
                    g = governor.ProductivityGovernor(threshold=4, cooldown_seconds=120)
                for turn in range(1, 5):
                    with mock.patch.object(governor, "evidence_signature", return_value=dict(evidence)):
                        g.observe({"turn_count":turn,"task":"TASK-013","phase":"x"})
                self.assertTrue(g.tripped())
                self.assertEqual(g.snapshot()["unproductive_turns"], 4)
            finally:
                governor.STATE = old_state

    def test_commit_counts_as_productive_evidence(self):
        progressed, reasons = governor.evidence_progressed({"head":"a","working_tree":"x"},{"head":"b","working_tree":"x"})
        self.assertTrue(progressed); self.assertIn("commit", reasons)


class TestHardwareSafety(unittest.TestCase):
    def test_low_disk_pauses_factory(self):
        reason = hardware.safety_reason({"disk":{"free_gb":1.8},"memory":{},"gpu":{},"unreal":{}})
        self.assertIn("Disk free space", reason)

    def test_hot_gpu_pauses_factory(self):
        reason = hardware.safety_reason({"disk":{"free_gb":100},"memory":{"free_bytes":8*1024**3},"gpu":{"temperature_c":95},"unreal":{}})
        self.assertIn("GPU temperature", reason)


class TestLocalAI(unittest.TestCase):
    def test_deterministic_quota_classification_does_not_wake_cloud(self):
        value = local_ai.deterministic_classify("You've hit your usage limit; try again later")
        self.assertIn("provider_quota", value["categories"])
        self.assertFalse(value["cloud_wake_recommended"])

    def test_process_lifecycle_is_local_recovery(self):
        value = local_ai.deterministic_classify("invalid_pid open_process_failed")
        self.assertIn("process_lifecycle", value["categories"])
        self.assertFalse(value["cloud_wake_recommended"])


class TestOperationalMetrics(unittest.TestCase):
    def test_24h_report_separates_alive_and_productive(self):
        with tempfile.TemporaryDirectory() as directory:
            old_samples = metrics.SAMPLES; metrics.SAMPLES = Path(directory) / "samples.jsonl"
            now=time.time(); rows=[
                {"ts":now-90,"alive":True,"productive":True,"useful_turns":1,"commits":0,"tests":0,"recoveries":0,"human_required":0},
                {"ts":now-60,"alive":True,"productive":False,"useful_turns":2,"commits":1,"tests":2,"recoveries":1,"human_required":0},
                {"ts":now-30,"alive":True,"productive":False,"useful_turns":2,"commits":1,"tests":2,"recoveries":1,"human_required":1},
            ]
            metrics.SAMPLES.write_text("\n".join(json.dumps(row) for row in rows)+"\n",encoding="utf-8")
            try:
                report=metrics.OperationalMetrics().report(24)
                self.assertEqual(report["uptime_percent"],100.0)
                self.assertLess(report["productive_percent"],100.0)
                self.assertEqual(report["commits"],1)
                self.assertEqual(report["tests"],2)
                self.assertEqual(report["human_interventions"],1)
            finally: metrics.SAMPLES=old_samples


class TestRollbackPrimitives(unittest.TestCase):
    def test_changed_runtime_can_be_restored_without_git_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); scripts=root/"Scripts"; scripts.mkdir(); target=scripts/"A.py"; target.write_text("good\n",encoding="utf-8")
            old_repo, old_root, old_state, old_files = rollback.REPO, rollback.SNAPSHOT_ROOT, rollback.STATE, rollback.MANAGED_FILES
            rollback.REPO=root; rollback.SNAPSHOT_ROOT=root/"snapshots"; rollback.STATE=root/"state.json"; rollback.MANAGED_FILES=("Scripts/A.py",)
            try:
                guard=rollback.RollbackGuard(); guard.prepare_generation(1); target.write_text("bad\n",encoding="utf-8")
                self.assertEqual(guard.changed_files(),["Scripts/A.py"])
                restored=guard.restore("test"); self.assertEqual(restored,["Scripts/A.py"]); self.assertEqual(target.read_text(encoding="utf-8"),"good\n")
            finally:
                rollback.REPO, rollback.SNAPSHOT_ROOT, rollback.STATE, rollback.MANAGED_FILES = old_repo, old_root, old_state, old_files


class TestSafeProcessChaos(unittest.TestCase):
    def test_owned_child_death_is_observable(self):
        process=subprocess.Popen([sys.executable,"-c","import time; time.sleep(0.05)"])
        process.wait(timeout=5)
        self.assertIsNotNone(process.poll())


if __name__ == "__main__": unittest.main()
