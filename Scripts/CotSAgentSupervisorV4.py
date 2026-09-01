#!/usr/bin/env python3
"""V4 compatibility layer over the proven CotS supervisor.

Keeps its battle-tested orchestration while fixing the remote-main protocol
regression, selecting the correct task workspace, rotating Codex threads at
turn boundaries, reconciling the profile-aware Host MCP, and forcing a clean
supervisor restart before crossing a workspace-profile boundary.
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
from CotSHostClient import call as host_call, status as host_status
from CotSProtocolAdapterV4 import activity_count, completed_item_from_notification, extract_text, normalize_items
from CotSWorkspaceProfiles import profile_for_task

TOOLS_REPO = SCRIPT_DIR.parent
_original_next_required_task = legacy.next_required_task
ACTIVE_TASK = _original_next_required_task()
PROFILE = profile_for_task(ACTIVE_TASK)


def _v4_next_required_task(path: Path = legacy.FOUNDATION_COMPLETION_STATE) -> str | None:
    """Never cross tooling/production roots inside one provider supervisor."""
    actual = _original_next_required_task(path)
    if actual is not None and profile_for_task(actual).name != PROFILE.name:
        return None
    return actual


legacy.next_required_task = _v4_next_required_task


def _profile_instructions() -> str:
    git_script = TOOLS_REPO / "Scripts" / "CotS-GitCompletion.py"
    agents_file = TOOLS_REPO / "AGENTS.md"
    autonomy_file = TOOLS_REPO / "Docs" / "AUTONOMOUS_DEVELOPMENT.md"
    task = ACTIVE_TASK or "ROADMAP_COMPLETE"
    return f"""CotS Factory V4 workspace contract.
Control plane: {TOOLS_REPO}
Active task: {task}
Active profile: {PROFILE.name}
Only writable task workspace: {PROFILE.workspace_root}
Expected repository: {PROFILE.repository}
Unreal project: {PROFILE.project_path}
Shardlands donor: C:\\Dev\\Shardlands — READ ONLY; never mutate, clean, rename, reset, or reorganize it.

Read and obey these absolute control-plane files before work:
- {agents_file}
- {autonomy_file}
- the active task specification under {TOOLS_REPO / 'Tasks'}
The current process working directory is the active workspace, not the control-plane repository.
Do not treat CotSDeveloperTools as production output when the profile is production.

Use only the profile-aware Git helper for Git mutation:
python "{git_script}" --profile {PROFILE.name} ...
Never reset, clean, force-push, rewrite history, or stage unrelated files.
Production autonomous commits must be on autonomous/task-* branches; direct production commits to main are refused.
For the canonical build use only: "{PROFILE.build_script}"
Do not retry raw UBT/dotnet/Build.bat after a sandbox/write failure.

Host MCP is profile-bound. Before mutation verify GetWorkspaceStatus reports
profile={PROFILE.name}, repository={PROFILE.repository}, and the expected Unreal project identity when the editor is running.
Acquire/release the logical mutation lease around mutating lifecycle work. Only one mutating provider may act at a time.
Use Epic native Unreal MCP where sufficient and existing CotS typed tools where they add validated behavior.

Work in coherent bounded turns from the compact checkpoint. Re-read only changed facts. Prefer targeted validation while iterating and full suites only at gates. Never claim a build/test/PIE proof that was not actually run. A provider outcome marker is not roadmap completion; only the checked-in ledger is authoritative.
"""


V4_PREFIX = _profile_instructions()
V4_CONTINUE = """Continue from this structured checkpoint. Inspect source only where needed to verify changed facts; do not reconstruct conversation history by default.{checkpoint_facts}
"""
legacy.CODEX_START = V4_PREFIX + "\n" + legacy.PROVIDER_SELF_VALIDATION_RULE + "\n" + legacy.MARKER_INSTRUCTIONS
legacy.CLAUDE_START = V4_PREFIX + "\n" + legacy.PROVIDER_SELF_VALIDATION_RULE + "\n" + legacy.MARKER_INSTRUCTIONS
legacy.CODEX_CONTINUE_TEMPLATE = V4_PREFIX + "\n" + V4_CONTINUE + legacy.MARKER_INSTRUCTIONS
legacy.CLAUDE_CONTINUE_TEMPLATE = V4_PREFIX + "\n" + V4_CONTINUE + legacy.MARKER_INSTRUCTIONS
legacy.START_PROMPTS = {"codex": legacy.CODEX_START, "claude": legacy.CLAUDE_START}

# Checkpoint/log constants were computed at legacy import time and remain in
# CotSDeveloperTools. REPO below changes only task-facing cwd/path/Git probes.
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

# --- V4 Host MCP reconciliation -------------------------------------------
def _v4_probe_host_mcp(bus: Any) -> None:
    try:
        payload = host_status(timeout=2.0)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if payload.get("success") is not True:
            raise RuntimeError(str(payload.get("error") or "Host status unsuccessful"))
        if data.get("profile") != PROFILE.name or str(data.get("repository") or "").lower() != PROFILE.repository.lower():
            raise RuntimeError(
                f"Host identity mismatch: profile={data.get('profile')!r} repository={data.get('repository')!r}"
            )
        lease = data.get("mutation_lock") if isinstance(data.get("mutation_lock"), dict) else {}
        lease_owner = lease.get("agent_id") or "none"
        bus.update(
            host_mcp_state="READY",
            toollab_state="OPEN" if data.get("editor_running") else "CLOSED",
            unreal_mcp_state="READY" if data.get("unreal_mcp_ready") else "NOT_READY",
            mutation_lease_owner=lease_owner,
            workspace_profile=PROFILE.name,
            target_repository=PROFILE.repository,
        )
        legacy.reconcile_task_phase(bus, lease_owner)
    except Exception as error:
        bus.update(
            host_mcp_state=f"NOT_READY: {error}",
            toollab_state="UNKNOWN",
            unreal_mcp_state="UNKNOWN",
            workspace_profile=PROFILE.name,
            target_repository=PROFILE.repository,
        )
        legacy.reconcile_task_phase(bus, bus.data.get("mutation_lease_owner"))


def _v4_reconcile_host_lock_owner(bus: Any) -> None:
    owner = bus.data.get("mutation_lease_owner")
    target = legacy.supervisor_task_owner(bus.data.get("task"))
    if not owner or owner == "none" or not target or owner == target:
        return
    if not legacy.re.fullmatch(r"(?:codex|claude)-task-[a-z0-9-]+", str(owner), legacy.re.IGNORECASE):
        return
    try:
        transferred = host_call(
            "TransferMutationLock",
            {"agent_id": owner, "target_agent_id": target},
            timeout=5.0,
        )
        if transferred.get("success"):
            bus.update(mutation_lease_owner=target, event=f"Host mutation lease migrated {owner} -> {target}")
        else:
            bus.update(event=f"Host mutation lease migration deferred: {transferred.get('error')}")
    except Exception as error:
        bus.update(event=f"Host mutation lease migration deferred: {error}")


legacy.probe_host_mcp = _v4_probe_host_mcp
legacy.reconcile_host_lock_owner = _v4_reconcile_host_lock_owner

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
    # One engineering turn per provider thread. App Server stays persistent,
    # while provider conversation is rebuilt from the compact checkpoint.
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


def main() -> int:
    os.environ["COTS_WORKSPACE_PROFILE"] = PROFILE.name
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
