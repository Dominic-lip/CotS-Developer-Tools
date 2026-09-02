#!/usr/bin/env python3
"""Bounded local recovery for the pre-24x7 usage governor.

The legacy governor intentionally blocks a work package after repeated
zero/micro-delta provider turns. Older supervisor builds then park forever in
GOVERNOR_PAUSED waiting for human direction. The 24x7 runtime treats those
specific *strategy* blocks as locally recoverable: preserve all historical
metrics, clear only the active retry/blocking streak, then restart the factory
so the provider gets one fresh strategy opportunity.

A second bounded recovery is allowed when a provider has emitted an explicit
structured HANDOFF but the legacy duplicate-provider guard subsequently blocks
the package for observing the same substantive blocker again. In that case the
handoff is already the changed strategy; the outer watchdog may clear only the
active block and reassert the persisted handoff target after shutdown.

Hard package-budget exhaustion and unknown block reasons are never overridden.
No AI provider is contacted by this module.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
COTS = REPO / ".cots"
STATE = COTS / "usage-governor.local.json"
SUPERVISOR_STATE = COTS / "agent-supervisor.local.json"
LOCK = COTS / "usage-governor.local.json.lock"
RECOVERY_STATE = COTS / "legacy-governor-recovery.local.json"

RECOVERABLE_REASON_TOKENS = (
    "zero-delta",
    "micro/low-delta",
    "same next action",
    "unchanged strategy",
    "batch related implementation",
    "changed strategy or human direction required",
)

# These reasons are only recoverable when the supervisor has a concrete,
# structured provider handoff. Without that evidence they remain blocked.
HANDOFF_BLOCK_TOKENS = (
    "same substantive blocker observed twice",
    "same failed provider attempt observed twice",
    "no third blind retry",
)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _active_package(state: dict[str, Any], task_id: str) -> tuple[dict[str, Any] | None, str | None]:
    tasks = state.get("tasks") if isinstance(state.get("tasks"), dict) else {}
    task = tasks.get(task_id) if isinstance(tasks.get(task_id), dict) else None
    if not task:
        return None, None
    package_id = str(task.get("current_package") or "1")
    packages = task.get("packages") if isinstance(task.get("packages"), dict) else {}
    package = packages.get(package_id) if isinstance(packages.get(package_id), dict) else None
    return package, package_id


def structured_handoff_target(supervisor: dict[str, Any] | None) -> str | None:
    """Return an explicitly requested provider handoff, if one is durable.

    Prefer the persisted field. ``last_output`` is a restart-safe fallback for
    older/local supervisor builds that emitted the marker but failed to retain
    ``pending_handoff_target`` through their legacy admission path.
    """
    supervisor = supervisor if isinstance(supervisor, dict) else {}
    target = str(supervisor.get("pending_handoff_target") or "").strip().lower()
    if target in {"codex", "claude"}:
        return target

    output = str(supervisor.get("last_output") or "")
    if "SUPERVISOR_OUTCOME: HANDOFF" not in output:
        return None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("SUPERVISOR_TARGET_AGENT:"):
            continue
        candidate = line.partition(":")[2].strip().lower()
        if candidate in {"codex", "claude"}:
            return candidate
    return None


def recover_state(
    state: dict[str, Any],
    task_id: str,
    *,
    source: str = "24x7-watchdog",
    supervisor: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a recovered copy/result while preserving historical counters.

    Strategy/streak blocks are eligible directly. A repeated-substantive-block
    is eligible only when the supervisor has a structured provider HANDOFF,
    because the handoff itself supplies the required changed strategy. Package
    budgets and unknown reasons remain blocked so quota protection cannot be
    silently bypassed.
    """
    package, package_id = _active_package(state, task_id)
    if package is None:
        return state, {"recovered": False, "reason": "task/package not found", "task": task_id}

    blocked = bool(package.get("blocked"))
    reason = str(package.get("blocked_reason") or "").strip()
    lower = reason.lower()
    handoff_target = structured_handoff_target(supervisor)
    strategy_recoverable = blocked and any(token in lower for token in RECOVERABLE_REASON_TOKENS)
    handoff_recoverable = (
        blocked
        and handoff_target is not None
        and any(token in lower for token in HANDOFF_BLOCK_TOKENS)
    )
    recoverable = strategy_recoverable or handoff_recoverable
    if not recoverable:
        return state, {
            "recovered": False,
            "reason": reason or ("package not blocked" if not blocked else "non-recoverable legacy governor block"),
            "task": task_id,
            "package": package_id,
            "handoff_target": handoff_target,
        }

    now = time.time()
    mode = "structured_handoff" if handoff_recoverable and not strategy_recoverable else "strategy_streak"
    before = {
        "blocked_reason": reason,
        "zero_delta_streak": int(package.get("zero_delta_streak") or 0),
        "low_delta_streak": int(package.get("low_delta_streak") or 0),
        "turns": int(package.get("turns") or 0),
    }

    package["blocked"] = False
    package["blocked_reason"] = None
    package["zero_delta_streak"] = 0
    package["low_delta_streak"] = 0
    package["last_zero_delta_next_action_digest"] = None
    package["last_low_delta_next_action_digest"] = None
    package["autonomous_recovery"] = {
        "at": now,
        "source": source,
        "mode": mode,
        "handoff_target": handoff_target,
        "reason": "cleared only active legacy block; historical productivity totals preserved",
        "previous": before,
    }

    history = state.setdefault("autonomous_recovery_history", [])
    if not isinstance(history, list):
        history = []
        state["autonomous_recovery_history"] = history
    history.append({
        "at": now,
        "task": task_id,
        "package": package_id,
        "source": source,
        "mode": mode,
        "handoff_target": handoff_target,
        "previous": before,
    })
    state["autonomous_recovery_history"] = history[-50:]
    state["updated_at"] = now

    return state, {
        "recovered": True,
        "task": task_id,
        "package": package_id,
        "mode": mode,
        "handoff_target": handoff_target,
        "previous_reason": reason,
        "previous_zero_delta_streak": before["zero_delta_streak"],
        "previous_low_delta_streak": before["low_delta_streak"],
    }


def recover_persisted(task_id: str, *, source: str = "24x7-watchdog") -> dict[str, Any]:
    """Recover the persisted active package using a short inter-process lock."""
    COTS.mkdir(parents=True, exist_ok=True)
    LOCK.touch(exist_ok=True)
    if LOCK.stat().st_size == 0:
        LOCK.write_bytes(b" ")
    with LOCK.open("r+b") as lock_handle:
        locked = False
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock_handle.seek(0)
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError:
                time.sleep(0.05)
        if not locked:
            return {"recovered": False, "reason": "legacy governor state lock busy", "task": task_id}
        try:
            state = _read_json(STATE)
            if not state:
                return {"recovered": False, "reason": "legacy governor state unavailable", "task": task_id}
            supervisor = _read_json(SUPERVISOR_STATE)
            state, result = recover_state(state, task_id, source=source, supervisor=supervisor)
            if result.get("recovered"):
                _atomic_json(STATE, state)
                _atomic_json(RECOVERY_STATE, {**result, "at": time.time()})
            return result
        finally:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock_handle.seek(0)
                    msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Recover one locally blocked legacy usage-governor package")
    parser.add_argument("task")
    args = parser.parse_args()
    print(json.dumps(recover_persisted(args.task, source="manual-local-recovery"), indent=2, default=str))
