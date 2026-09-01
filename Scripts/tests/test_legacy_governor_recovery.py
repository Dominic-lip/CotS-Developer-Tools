from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from CotSLegacyGovernorRecovery import recover_state


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


def test_strategy_block_is_rebaselined_without_erasing_history() -> None:
    original = _state("two consecutive zero-delta turns; changed strategy or human direction required")
    state, result = recover_state(copy.deepcopy(original), "TASK-013")
    assert result["recovered"] is True
    package = state["tasks"]["TASK-013"]["packages"]["1"]
    assert package["blocked"] is False
    assert package["blocked_reason"] is None
    assert package["zero_delta_streak"] == 0
    assert package["last_zero_delta_next_action_digest"] is None
    assert package["zero_delta_turns"] == 4
    assert state["tasks"]["TASK-013"]["total_turns"] == 4
    assert state["totals"] == original["totals"]
    assert package["failure_counts"] == {"abc": 2}
    assert state["autonomous_recovery_history"][-1]["task"] == "TASK-013"


def test_hard_budget_block_is_not_overridden() -> None:
    original = _state("package budget reached (8/8) with high-value ratio 0%")
    state, result = recover_state(copy.deepcopy(original), "TASK-013")
    assert result["recovered"] is False
    assert state["tasks"]["TASK-013"]["packages"]["1"]["blocked"] is True


def test_unblocked_package_is_noop() -> None:
    original = _state("", blocked=False)
    state, result = recover_state(copy.deepcopy(original), "TASK-013")
    assert result["recovered"] is False
    assert state["tasks"]["TASK-013"]["packages"]["1"]["zero_delta_streak"] == 2
