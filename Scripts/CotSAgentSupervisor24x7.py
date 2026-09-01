#!/usr/bin/env python3
"""Hardened entry point for CotSAgentSupervisor.

This wrapper leaves the reviewed supervisor logic intact but places a strict,
local schema boundary between provider text and the supervisor. Provider output
is untrusted telemetry: malformed shapes are repaired locally and never allowed
to crash the autonomous process.
"""
from __future__ import annotations

import sys
import traceback
from typing import Any

import CotSAgentSupervisor as base
from CotS24x7Common import DailyTelemetry, sanitize_context, safe_nonnegative_int

telemetry = DailyTelemetry()
_original_load_state = base.load_state
_original_parse = base.parse_compact_context


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


def install_hardening() -> None:
    base.load_state = hardened_load_state
    base.parse_compact_context = hardened_parse_compact_context
    base.compact_context = hardened_compact_context
    base.merge_compact_context = hardened_merge_compact_context
    base._bounded = hardened_bounded


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
