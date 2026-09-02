from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from CotSAgentSupervisor24x7 import apply_routing_override
from CotSLegacyGovernorRecovery import recover_state, structured_handoff_target


def _state(reason: str, *, blocked: bool = True) -> dict:
    return {
        "schema_version": 3,
        "totals": {"provider_turns": 99, "zero_delta_turns": 7},
        "tasks": {
            "TASK-013": {
                "current_package": 1,
                "total_turns": 4,
                "zero_delta_turns": 4,
                "packages": {
                    "1": {
                        "id": "P001",
                        "turns": 4,
                        "blocked": blocked,
                        "blocked_reason": reason,
                        "zero_delta_streak": 2,
                        "zero_delta_turns": 4,
                        "low_delta_streak": 0,
                        "last_zero_delta_next_action_digest": "same",
                        "failure_counts": {"abc": 2},
                    }
                },
            }
        },
    }


def _supervisor(*, claude_status: str = "IDLE", explicit_target: str | None = None) -> dict:
    value = {
        "task": "TASK-013",
        "preferred_agent": "codex",
        "active_agent": None,
        "turn_count": 7,
        "codex": {"status": "IDLE", "version": "test"},
        "claude": {"status": claude_status, "version": "test"},
    }
    if explicit_target:
        value["pending_handoff_target"] = explicit_target
    return value


class LegacyGovernorRecoveryTests(unittest.TestCase):
    def test_strategy_block_is_rebaselined_without_erasing_history(self) -> None:
        original = _state("two consecutive zero-delta turns; changed strategy or human direction required")
        state, result = recover_state(copy.deepcopy(original), "TASK-013")
        self.assertTrue(result["recovered"])
        package = state["tasks"]["TASK-013"]["packages"]["1"]
        self.assertFalse(package["blocked"])
        self.assertIsNone(package["blocked_reason"])
        self.assertEqual(package["zero_delta_streak"], 0)
        self.assertIsNone(package["last_zero_delta_next_action_digest"])
        self.assertEqual(package["zero_delta_turns"], 4)
        self.assertEqual(state["tasks"]["TASK-013"]["total_turns"], 4)
        self.assertEqual(state["totals"], original["totals"])
        self.assertEqual(package["failure_counts"], {"abc": 2})
        self.assertEqual(state["autonomous_recovery_history"][-1]["task"], "TASK-013")

    def test_repeated_substantive_block_recovers_with_structured_handoff(self) -> None:
        original = _state("same substantive blocker observed twice; no third blind retry")
        state, result = recover_state(copy.deepcopy(original), "TASK-013", supervisor=_supervisor(explicit_target="claude"))
        self.assertTrue(result["recovered"])
        self.assertEqual(result["mode"], "structured_handoff")
        self.assertEqual(result["handoff_target"], "claude")
        self.assertFalse(state["tasks"]["TASK-013"]["packages"]["1"]["blocked"])

    def test_repeated_substantive_block_routes_to_usable_alternate(self) -> None:
        original = _state("same substantive blocker observed twice; no third blind retry")
        state, result = recover_state(copy.deepcopy(original), "TASK-013", supervisor=_supervisor())
        self.assertTrue(result["recovered"])
        self.assertEqual(result["mode"], "alternate_provider")
        self.assertEqual(result["handoff_target"], "claude")
        self.assertFalse(state["tasks"]["TASK-013"]["packages"]["1"]["blocked"])

    def test_repeated_substantive_block_without_usable_alternate_stays_blocked(self) -> None:
        original = _state("same substantive blocker observed twice; no third blind retry")
        state, result = recover_state(
            copy.deepcopy(original), "TASK-013", supervisor=_supervisor(claude_status="USAGE_EXHAUSTED")
        )
        self.assertFalse(result["recovered"])
        self.assertTrue(state["tasks"]["TASK-013"]["packages"]["1"]["blocked"])

    def test_legacy_last_output_handoff_is_recognized(self) -> None:
        supervisor = {
            "last_output": "SUPERVISOR_OUTCOME: HANDOFF\nSUPERVISOR_TARGET_AGENT: claude\nSUPERVISOR_HANDOFF_REASON: provider-specific proof"
        }
        self.assertEqual(structured_handoff_target(supervisor), "claude")

    def test_hard_budget_block_is_not_overridden(self) -> None:
        original = _state("package budget reached (8/8) with high-value ratio 0%")
        state, result = recover_state(copy.deepcopy(original), "TASK-013", supervisor=_supervisor(explicit_target="claude"))
        self.assertFalse(result["recovered"])
        self.assertTrue(state["tasks"]["TASK-013"]["packages"]["1"]["blocked"])

    def test_unblocked_package_is_noop(self) -> None:
        original = _state("", blocked=False)
        state, result = recover_state(copy.deepcopy(original), "TASK-013")
        self.assertFalse(result["recovered"])
        self.assertEqual(state["tasks"]["TASK-013"]["packages"]["1"]["zero_delta_streak"], 2)

    def test_routing_override_applies_only_until_a_provider_turn_advances(self) -> None:
        state = {
            "task": "TASK-013",
            "turn_count": 7,
            "compact_task_context": {"task_id": "TASK-013"},
            "preferred_agent": "codex",
        }
        override = {
            "task": "TASK-013",
            "target": "claude",
            "at": 1000.0,
            "baseline_turn_count": 7,
        }
        routed, applied = apply_routing_override(state, override, now=1001.0)
        self.assertTrue(applied)
        self.assertEqual(routed["pending_handoff_target"], "claude")
        advanced = dict(state)
        advanced["turn_count"] = 8
        routed2, applied2 = apply_routing_override(advanced, override, now=1001.0)
        self.assertFalse(applied2)
        self.assertNotIn("pending_handoff_target", routed2)


if __name__ == "__main__":
    unittest.main()
