from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from CotSProcess import pid_running
from CotSProtocolAdapterV4 import activity_count, extract_text, normalize_items
from CotSUsageGovernor import UsageSample, evidence_count, strict_bool
from CotSWorkspaceProfiles import WorkspaceBoundaryError, assert_write_allowed, load_profile, normalized_github_repo, profile_for_task


def load_hyphen_module(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkspaceProfileTests(unittest.TestCase):
    def test_task_015_and_100_are_production(self) -> None:
        self.assertEqual(profile_for_task("TASK-014").name, "tooling")
        self.assertEqual(profile_for_task("TASK-015").name, "production")
        self.assertEqual(profile_for_task("TASK-100").name, "production")

    def test_shardlands_is_never_writable(self) -> None:
        for name in ("tooling", "production"):
            with self.assertRaises(WorkspaceBoundaryError):
                assert_write_allowed(Path(r"C:\Dev\Shardlands\Source\Bad.cpp"), load_profile(name))

    def test_remote_normalization(self) -> None:
        self.assertEqual(normalized_github_repo("https://github.com/Dominic-lip/CotS-Game.git"), "Dominic-lip/CotS-Game")
        self.assertEqual(normalized_github_repo("git@github.com:Dominic-lip/CotS-Game.git"), "Dominic-lip/CotS-Game")
        self.assertIsNone(normalized_github_repo("https://example.com/not-github/repo.git"))


class ProcessTests(unittest.TestCase):
    def test_invalid_pid_is_false_not_exception(self) -> None:
        for value in (None, 0, -1, True, "123"):
            self.assertFalse(pid_running(value))


class ProtocolTests(unittest.TestCase):
    def test_integer_items_are_never_iterated(self) -> None:
        self.assertEqual(normalize_items(7), [])
        self.assertEqual(activity_count(7), 7)
        self.assertEqual(extract_text({"items": 7}), "")

    def test_completed_item_text_fallback(self) -> None:
        completed = [{"type": "agentMessage", "text": "done"}]
        self.assertEqual(extract_text({"items": 1}, completed), "done")
        self.assertEqual(activity_count(1, completed), 1)

    def test_future_wrapped_items_shape(self) -> None:
        wrapped = {"items": [{"type": "message", "content": "ok"}]}
        self.assertEqual(extract_text({"items": wrapped}), "ok")


class GovernorTests(unittest.TestCase):
    def test_exact_incident_list_is_counted(self) -> None:
        self.assertEqual(evidence_count(["a", "b", "c"]), 3)
        self.assertEqual(evidence_count({"items": [1, 2]}), 2)
        self.assertEqual(evidence_count({"count": 4}), 4)

    def test_ambiguous_text_is_not_manufactured_evidence(self) -> None:
        self.assertEqual(evidence_count("three"), 0)
        self.assertEqual(evidence_count({"note": "many"}), 0)

    def test_boolean_strings_are_strict(self) -> None:
        self.assertFalse(strict_bool("false"))
        self.assertFalse(strict_bool("0"))
        self.assertTrue(strict_bool("true"))
        self.assertTrue(strict_bool("1"))
        self.assertFalse(strict_bool("anything else"))

    def test_context_health_thresholds(self) -> None:
        self.assertEqual(UsageSample(input_tokens=43_000, context_window=258_400).context_health, "HEALTHY")
        self.assertTrue(UsageSample(input_tokens=213_347, context_window=258_400).rotation_required)
        self.assertEqual(UsageSample(input_tokens=213_347, context_window=258_400).context_health, "CRITICAL")


class GitCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_hyphen_module("CotS-GitCompletionV4.py", "cots_git_completion_v4")

    def test_production_main_is_refused(self) -> None:
        with self.assertRaises(WorkspaceBoundaryError):
            self.module.require_safe_branch("production", "main", "autonomous/", "main")

    def test_production_task_branch_is_allowed(self) -> None:
        self.module.require_safe_branch("production", "autonomous/task-015", "autonomous/", "main")


if __name__ == "__main__":
    unittest.main()
