#!/usr/bin/env python3
"""Hardened entry point for CotSAgentSupervisor.

This wrapper leaves the reviewed supervisor logic intact but places a strict,
local schema boundary between provider text and the supervisor. Provider output
is untrusted telemetry: malformed shapes are repaired locally and never allowed
to crash the autonomous process.

It also consumes a bounded local routing override produced by the 24x7 legacy-
governor recovery layer, extends the checked-in roadmap scheduler through the
read-only TASK-116 reconciliation gate, and exposes the fixed production
lifecycle bridge only for the explicitly authorized production-mutation tasks.
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from typing import Any

import CotSAgentSupervisor as base
from CotS24x7Common import DailyTelemetry, sanitize_context, safe_nonnegative_int
from CotSLegacyGovernorRecovery import ROUTING_OVERRIDE

telemetry = DailyTelemetry()
_original_load_state = base.load_state
_original_parse = base.parse_compact_context
_original_scheduled_task_instruction = base.scheduled_task_instruction
_original_turn_outcome = base.turn_outcome
ROUTING_OVERRIDE_MAX_AGE_SECONDS = 6 * 60 * 60

# TASK-016 exposed a topology mismatch rather than a missing capability: a
# Codex App Server turn cannot recursively conjure a Claude MCP client, but the
# supervisor already owns a first-class Claude adapter. When Codex reports this
# exact provider-capability boundary, route the next turn through the existing
# structured HANDOFF mechanism instead of restarting the same Codex turn.
CLAUDE_HANDOFF_GATE_PATTERNS = (
    "no claude adapter",
    "no claude mcp client",
    "no claude client capability",
)

PRODUCTION_ADAPTER_INSTRUCTIONS = r"""
For TASK-015 and TASK-100 through TASK-115 only, the scheduled task itself is
explicit authorization to modify C:\Dev\CotS within that task's stated scope.
Host filesystem/lifecycle/build/Git work against production must go through the
fixed audited command `python Scripts/CotSProductionLifecycle.py ...`; never
replace it with arbitrary shell, PowerShell, raw Git mutation, arbitrary Python
filesystem code, or writes elsewhere under C:\Dev. C:\Dev\Shardlands remains
read-only. The fixed production lifecycle command is the one additional command
for which Codex may request sandbox escalation when its workspace sandbox blocks
the external production root; the configured auto-reviewer remains the approval
authority. No other shell/filesystem/process escalation is authorized.

For bounded production text changes, write a JSON manifest only under
`.cots/production-manifests/` in this DeveloperTools workspace and apply it with
`python Scripts/CotSProductionLifecycle.py apply-manifest <name.json>`. Use the
adapter's fixed bootstrap/build/smoke/open/close/wait-mcp/git-complete operations
rather than inventing host commands. Native Unreal MCP may be used after the
fixed production editor is open and ready. If an adapter operation reports a
real prerequisite/configuration problem, report that exact structured gate; do
not retry the unchanged command blindly.
""".strip()


def _production_task(task: object) -> bool:
    value = str(task or "")
    if value == "TASK-015":
        return True
    match = re.fullmatch(r"TASK-(\d{3})", value)
    return bool(match and 100 <= int(match.group(1)) <= 115)


def hardened_load_foundation_completion_state(path=None) -> dict[str, Any]:
    """Fail-closed roadmap loader extended through the read-only TASK-116 gate.

    The base supervisor intentionally recognizes a fixed reviewed task set.  The
    24x7 wrapper owns the post-115 extension so the large reviewed base module
    does not need an unrelated rewrite.  TASK-116 is scheduling authority only;
    `_production_task()` deliberately remains capped at TASK-115, therefore the
    fixed production mutation bridge is not exposed for this reconciliation.
    """
    path = base.FOUNDATION_COMPLETION_STATE if path is None else path
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise base.AppServerError(f"foundation_completion_state_invalid: {error}") from error
    if document.get("schema_version") != 1:
        raise base.AppServerError("foundation_completion_state_invalid: unsupported schema version")
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise base.AppServerError("foundation_completion_state_invalid: tasks must be a non-empty list")
    seen: set[str] = set()
    for entry in tasks:
        task_id = entry.get("id") if isinstance(entry, dict) else None
        status = entry.get("status") if isinstance(entry, dict) else None
        if not isinstance(task_id, str) or not re.fullmatch(
            r"TASK-(?:0(?:0[0-9]|1[0-6]|08[A-C])|1(?:0[0-9]|1[0-6]))", task_id
        ):
            raise base.AppServerError(f"foundation_completion_state_invalid: invalid task id {task_id!r}")
        if task_id in seen:
            raise base.AppServerError(f"foundation_completion_state_invalid: duplicate task {task_id}")
        if status not in {
            "COMPLETE_VERIFIED", "COMPLETE_BUT_EVIDENCE_MISSING", "PARTIAL",
            "NOT_STARTED", "SUPERSEDED", base.DEFERRED_PROVIDER_VERIFICATION,
        }:
            raise base.AppServerError(f"foundation_completion_state_invalid: invalid status for {task_id}")
        if status == base.VERIFIED_COMPLETION_STATUS and not entry.get("evidence"):
            raise base.AppServerError(f"foundation_completion_state_invalid: {task_id} lacks durable evidence references")
        seen.add(task_id)
    expected = (
        {f"TASK-{number:03d}" for number in range(9)}
        | {"TASK-008A", "TASK-008B", "TASK-008C"}
        | {f"TASK-{number:03d}" for number in range(9, 17)}
        | {f"TASK-{number}" for number in range(100, 117)}
    )
    if seen != expected:
        raise base.AppServerError(
            "foundation_completion_state_invalid: foundation and production roadmap task records are required"
        )
    return document


def _repair_efficiency(value: object) -> dict[str, Any]:
    info = dict(value) if isinstance(value, dict) else {}
    for field in (
        "task_turns", "targeted_test_runs", "full_suite_runs", "repeated_failure_count",
        "files_newly_read_this_turn", "files_reread_unchanged", "checkpoint_context_size",
    ):
        info[field] = safe_nonnegative_int(info.get(field), 0)
    providers = info.get("provider_turns")
    info["provider_turns"] = {
        str(k): safe_nonnegative_int(v, 0)
        for k, v in providers.items()
    } if isinstance(providers, dict) else {}
    elapsed = info.get("current_turn_elapsed_ms")
    if not isinstance(elapsed, (int, float)):
        info["current_turn_elapsed_ms"] = 0
    return info


def _repair_provider(value: object) -> dict[str, Any]:
    info = dict(value) if isinstance(value, dict) else {}
    for field in ("reset_at", "next_availability_probe_at", "last_availability_probe_at"):
        if info.get(field) is not None and not isinstance(info[field], (int, float)):
            info[field] = None
    info["availability_probe_attempts"] = safe_nonnegative_int(info.get("availability_probe_attempts"), 0)
    return info


def _read_routing_override() -> dict[str, Any]:
    try:
        value = json.loads(ROUTING_OVERRIDE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def apply_routing_override(state: dict[str, Any], override: dict[str, Any], *, now: float | None = None) -> tuple[dict[str, Any], bool]:
    """Apply one still-relevant provider route without inventing provider work."""
    if not isinstance(state, dict) or not isinstance(override, dict):
        return state, False
    now = time.time() if now is None else float(now)
    target = str(override.get("target") or "").strip().lower()
    task = str(override.get("task") or "").strip()
    at = override.get("at")
    baseline = safe_nonnegative_int(override.get("baseline_turn_count"), 0)
    current_turn = safe_nonnegative_int(state.get("turn_count"), 0)
    if target not in {"codex", "claude"} or not task:
        return state, False
    if not isinstance(at, (int, float)) or now - float(at) > ROUTING_OVERRIDE_MAX_AGE_SECONDS:
        return state, False
    if current_turn > baseline:
        return state, False

    compact = state.get("compact_task_context") if isinstance(state.get("compact_task_context"), dict) else {}
    candidates = {
        str(state.get("task") or ""),
        str(state.get("scheduled_task") or ""),
        str(state.get("active_task_override") or ""),
        str(compact.get("task_id") or ""),
    }
    candidates.discard("")
    if candidates and task not in candidates:
        return state, False

    result = dict(state)
    result["pending_handoff_target"] = target
    result["active_task_override"] = task
    return result, True


def hardened_load_state() -> dict[str, Any]:
    state = _original_load_state()
    if not isinstance(state, dict):
        state = {}
    state["turn_count"] = safe_nonnegative_int(state.get("turn_count"), 0)
    state["rotation_count"] = safe_nonnegative_int(state.get("rotation_count"), 0)
    state["compact_task_context"] = sanitize_context(state.get("compact_task_context"))
    state["efficiency"] = _repair_efficiency(state.get("efficiency"))
    for name in ("codex", "claude"):
        state[name] = _repair_provider(state.get(name))
    failures = state.get("failure_fingerprints")
    if not isinstance(failures, dict):
        state["failure_fingerprints"] = {}

    override = _read_routing_override()
    state, applied = apply_routing_override(state, override)
    if applied:
        telemetry.emit(
            "LEGACY_ROUTE_RESTORED",
            f"Restored bounded provider route to {state.get('pending_handoff_target')} for {override.get('task')}",
            target=state.get("pending_handoff_target"),
            task=override.get("task"),
            mode=override.get("mode"),
        )
    return state


def hardened_parse_compact_context(text: str) -> dict[str, Any]:
    try:
        raw = _original_parse(text)
    except Exception as error:
        telemetry.emit("TELEMETRY_SANITIZED", f"SUPERVISOR_CONTEXT parse failed locally: {error}")
        return {}
    sanitized = sanitize_context(raw)
    if raw != sanitized:
        telemetry.emit(
            "TELEMETRY_SANITIZED",
            "Malformed provider context was normalized locally; no provider retry required",
            raw_types={k: type(v).__name__ for k, v in raw.items()} if isinstance(raw, dict) else {},
        )
    return sanitized


def hardened_turn_outcome(text: str) -> tuple[str, str]:
    """Translate the observed TASK-016 missing-Claude-client gate to HANDOFF.

    The provider is describing its own App Server client surface, not the
    supervisor's capabilities. The supervisor already has ClaudeAgent and is
    the component responsible for provider rotation, so another Codex retry can
    never satisfy this gate. Only the narrow RECOVERABLE_PROVIDER + explicit
    missing-Claude-client wording is rewritten; all other gates are preserved.
    """
    kind, detail = _original_turn_outcome(text)
    if kind != "RECOVERABLE_GATE":
        return kind, detail
    category, separator, remainder = detail.partition("|")
    reason, separator2, _action = remainder.partition("|") if separator else ("", "", "")
    normalized = " ".join(reason.lower().split())
    if (
        category == "RECOVERABLE_PROVIDER"
        and separator2
        and any(pattern in normalized for pattern in CLAUDE_HANDOFF_GATE_PATTERNS)
    ):
        telemetry.emit(
            "PROVIDER_HANDOFF_REPAIR",
            "Converted missing Claude client capability gate into supervisor handoff",
            target="claude",
            reason=reason,
        )
        return "HANDOFF", f"claude:{reason}"
    return kind, detail


def hardened_compact_context(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("compact_task_context") if isinstance(state, dict) else {}
    return sanitize_context(raw)


def hardened_merge_compact_context(
    previous: dict[str, Any], incoming: dict[str, Any], task: str | None, phase: str | None,
) -> dict[str, Any]:
    prior = sanitize_context(previous)
    candidate = dict(prior)
    if isinstance(incoming, dict):
        candidate.update(incoming)
    if task:
        candidate["task_id"] = task
    if phase:
        candidate["phase"] = phase
    return sanitize_context(candidate, previous=prior)


def hardened_bounded(value: Any, limit: int = 12) -> Any:
    if isinstance(value, str):
        return value[:600]
    if isinstance(value, list):
        return [hardened_bounded(item, limit) for item in value[:limit]]
    if isinstance(value, dict):
        return {str(key)[:80]: hardened_bounded(item, limit) for key, item in list(value.items())[:limit]}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:600]


def hardened_scheduled_task_instruction(task_override: str | None = None) -> str:
    instruction = _original_scheduled_task_instruction(task_override)
    task = task_override or base.next_required_task()
    if _production_task(task):
        instruction += "\n\n" + PRODUCTION_ADAPTER_INSTRUCTIONS
    return instruction


def install_hardening() -> None:
    base.load_foundation_completion_state = hardened_load_foundation_completion_state
    base.load_state = hardened_load_state
    base.parse_compact_context = hardened_parse_compact_context
    base.turn_outcome = hardened_turn_outcome
    base.compact_context = hardened_compact_context
    base.merge_compact_context = hardened_merge_compact_context
    base._bounded = hardened_bounded
    base.scheduled_task_instruction = hardened_scheduled_task_instruction

    if PRODUCTION_ADAPTER_INSTRUCTIONS not in base.CODEX_START:
        base.CODEX_START = base.CODEX_START + "\n\n" + PRODUCTION_ADAPTER_INSTRUCTIONS
    if PRODUCTION_ADAPTER_INSTRUCTIONS not in base.CLAUDE_START:
        base.CLAUDE_START = base.CLAUDE_START + "\n\n" + PRODUCTION_ADAPTER_INSTRUCTIONS
    base.START_PROMPTS["codex"] = base.CODEX_START
    base.START_PROMPTS["claude"] = base.CLAUDE_START

    production_tool = " Bash(python Scripts/CotSProductionLifecycle.py *)"
    if "CotSProductionLifecycle.py" not in base.CLAUDE_ALLOWED_TOOLS:
        base.CLAUDE_ALLOWED_TOOLS += production_tool


def main() -> int:
    install_hardening()
    telemetry.emit("SUPERVISOR_START", "Hardened supervisor starting", wrapper="CotSAgentSupervisor24x7")
    try:
        code = int(base.main())
        telemetry.emit("SUPERVISOR_EXIT", f"Supervisor exited normally with code {code}", exit_code=code)
        return code
    except KeyboardInterrupt:
        telemetry.emit("SUPERVISOR_STOP", "Supervisor received keyboard interrupt")
        return 130
    except BaseException as error:
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-12000:]
        telemetry.emit("SUPERVISOR_CRASH", f"{type(error).__name__}: {error}", traceback=trace)
        print(trace, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
