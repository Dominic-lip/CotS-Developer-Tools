#!/usr/bin/env python3
"""V4 compatibility layer over the proven CotS supervisor.

Keeps its battle-tested orchestration while fixing the remote-main protocol
regression, selecting the correct task workspace, and rotating Codex threads at
turn boundaries so provider conversation state cannot grow without bound.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import CotSAgentSupervisor as legacy
from CotSProtocolAdapterV4 import activity_count, completed_item_from_notification, extract_text, normalize_items
from CotSWorkspaceProfiles import profile_for_task

TOOLS_REPO = SCRIPT_DIR.parent
ACTIVE_TASK = legacy.next_required_task()
PROFILE = profile_for_task(ACTIVE_TASK)


def _profile_instructions(provider: str) -> str:
    git_script = TOOLS_REPO / "Scripts" / "CotS-GitCompletion.py"
    build_script = PROFILE.build_script
    task = ACTIVE_TASK or "ROADMAP_COMPLETE"
    return f"""CotS Factory V4 workspace contract.
Control plane: {TOOLS_REPO}
Active task: {task}
Active profile: {PROFILE.name}
Writable workspace: {PROFILE.workspace_root}
Expected repository: {PROFILE.repository}
Unreal project: {PROFILE.project_path}
Shardlands donor: C:\\Dev\\Shardlands (READ ONLY; never mutate it).

Read {TOOLS_REPO / 'AGENTS.md'} and the task specification under
{TOOLS_REPO / 'Tasks'} before work. The process working directory is the active
workspace above. Do not treat CotSDeveloperTools as production output when the
profile is production. Do not treat Shardlands as an output workspace.

For Git status/diff/completion use only:
python "{git_script}" --profile {PROFILE.name} ...
For the canonical build use only:
"{build_script}"
Production autonomous commits must be on autonomous/task-* branches; direct
production commits to main are refused by the Git helper.

Host MCP is profile-bound. Before any mutation verify GetWorkspaceStatus says
profile={PROFILE.name}, repository={PROFILE.repository}, and the Unreal identity
matches {PROFILE.project_path}. Acquire the mutation lock using this supervisor
process PID and generation when those fields are requested.

Work in one coherent bounded turn from the compact checkpoint. Prefer targeted
validation. Never claim a build/test/PIE proof that was not actually run.
"""


V4_PREFIX = _profile_instructions("shared")
legacy.CODEX_START = V4_PREFIX + "\n" + legacy.CODEX_START
legacy.CLAUDE_START = V4_PREFIX + "\n" + legacy.CLAUDE_START
legacy.CODEX_CONTINUE_TEMPLATE = V4_PREFIX + "\n" + legacy.CODEX_CONTINUE_TEMPLATE
legacy.CLAUDE_CONTINUE_TEMPLATE = V4_PREFIX + "\n" + legacy.CLAUDE_CONTINUE_TEMPLATE
legacy.START_PROMPTS = {"codex": legacy.CODEX_START, "claude": legacy.CLAUDE_START}

# The legacy supervisor stores its checkpoint/log files in constants computed
# at import time; changing REPO here changes only task-facing cwd/path probes.
legacy.REPO = PROFILE.workspace_root


def v4_codex_app_settings(developer_instructions: str) -> dict[str, Any]:
    return {
        "cwd": str(PROFILE.workspace_root),
        "developerInstructions": developer_instructions,
        "approvalPolicy": legacy.AUTONOMY_POLICY,
        "approvalsReviewer": "auto_review",
        "sandbox": "workspace-write",
    }


legacy.codex_app_settings = v4_codex_app_settings

# Claude's shell allowlist must use absolute tool-control paths because its cwd
# is the target workspace in production mode.
git_command = str(TOOLS_REPO / "Scripts" / "CotS-GitCompletion.py")
legacy.CLAUDE_ALLOWED_TOOLS = (
    "Read Edit Write Grep Glob "
    f'Bash(python "{git_command}" --profile {PROFILE.name} *) '
    f'Bash("{PROFILE.build_script}" *) '
    "mcp__cots-host__GetWorkspaceStatus "
    "mcp__cots-host__AcquireMutationLock "
    "mcp__cots-host__ReleaseMutationLock "
    "mcp__cots-host__TransferMutationLock "
    "mcp__cots-host__OpenProject "
    "mcp__cots-host__CloseProject "
    "mcp__cots-host__WaitForUnrealMcp "
    "mcp__cots-host__BuildProject "
    "mcp__cots-host__RunCotSAutomation "
    "mcp__unreal-mcp__*"
)

# --- Codex protocol normalization -----------------------------------------
_original_handle_message = legacy.AppServer._handle_message
_original_wait_turn = legacy.AppServer.wait_turn


def _v4_handle_message(self: Any, message: dict[str, Any]) -> None:
    thread_id, item = completed_item_from_notification(message)
    if item is not None:
        if not hasattr(self, "_v4_completed_items"):
            self._v4_completed_items = {}
        key = thread_id or "__unknown__"
        self._v4_completed_items.setdefault(key, []).append(item)
        # item/completed has no other legacy side effect; retain the item and
        # notify waiters instead of throwing it away.
        with self.lock:
            self.lock.notify_all()
        return
    _original_handle_message(self, message)


def _v4_wait_turn(self: Any, thread_id: str, timeout: float = legacy.TURN_TIMEOUT_SECONDS) -> dict[str, Any]:
    turn = dict(_original_wait_turn(self, thread_id, timeout))
    completed = list(getattr(self, "_v4_completed_items", {}).pop(thread_id, []))
    if not completed:
        completed = list(getattr(self, "_v4_completed_items", {}).pop("__unknown__", []))
    raw_items = turn.get("items")
    normalized = normalize_items(raw_items)
    if not normalized and completed:
        normalized = completed
    count = activity_count(raw_items, completed)
    if not normalized and count:
        normalized = [{"type": "activity"} for _ in range(count)]
    turn["items"] = normalized
    turn["_v4_activity_count"] = count
    turn["_v4_completed_items"] = completed
    return turn


def _v4_text_from(turn: dict[str, Any]) -> str:
    return extract_text(turn, turn.get("_v4_completed_items") or [])


legacy.AppServer._handle_message = _v4_handle_message
legacy.AppServer.wait_turn = _v4_wait_turn
legacy.text_from = _v4_text_from

# --- Context growth control ------------------------------------------------
_original_codex_run_turn = legacy.CodexAgent.run_turn


def _v4_codex_run_turn(self: Any, prompt: str, bus: Any = None, shutdown_event: Any = None) -> Any:
    # One engineering turn per provider thread. The App Server process remains
    # persistent, but each new turn starts from the compact checkpoint rather
    # than an ever-growing provider conversation. Static instructions/tool
    # schemas remain cacheable by the provider.
    if getattr(self, "_v4_turns_on_thread", 0) >= 1:
        assert self.app is not None
        started = self.app.request("thread/start", legacy.codex_app_settings(legacy.CODEX_START))
        self.thread_id = started["thread"]["id"]
        self._v4_turns_on_thread = 0
        if bus is not None:
            bus.update(event="Codex context boundary reached; started fresh thread from compact checkpoint")
    result = _original_codex_run_turn(self, prompt, bus=bus, shutdown_event=shutdown_event)
    self._v4_turns_on_thread = getattr(self, "_v4_turns_on_thread", 0) + 1
    return result


legacy.CodexAgent.run_turn = _v4_codex_run_turn

# Claude is already one process per turn; keep session resume only within the
# same selected profile. The subprocess cwd comes from legacy.REPO, patched
# above to the active workspace.


def main() -> int:
    os.environ["COTS_WORKSPACE_PROFILE"] = PROFILE.name
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
