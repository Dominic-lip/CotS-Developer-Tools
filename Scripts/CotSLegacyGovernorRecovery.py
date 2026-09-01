#!/usr/bin/env python3
"""Bounded local recovery for the pre-24x7 usage governor.

The legacy governor intentionally blocks a work package after repeated
zero/micro-delta provider turns.  Older supervisor builds then park forever in
GOVERNOR_PAUSED waiting for human direction.  The 24x7 runtime treats those
specific *strategy* blocks as locally recoverable: preserve all historical
metrics, clear only the active retry/blocking streak, then restart the factory
so the provider gets one fresh strategy opportunity.

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


def recover_state(state: dict[str, Any], task_id: str, *, source: str = "24x7-watchdog") -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a recovered copy/result while preserving all historical counters.

    Only strategy/streak blocks are eligible.  Package budgets and unknown
    reasons remain blocked so quota protection cannot be silently bypassed.
    """
    package, package_id = _active_package(state, task_id)
    if package is None:
        return state, {"recovered": False, "reason": "task/package not found", "task": task_id}

    blocked = bool(package.get("blocked"))
    reason = str(package.get("blocked_reason") or "").strip()
    lower = reason.lower()
    recoverable = blocked and any(token in lower for token in RECOVERABLE_REASON_TOKENS)
    if not recoverable:
        return state, {
            "recovered": False,
            "reason": reason or ("package not blocked" if not blocked else "non-recoverable legacy governor block"),
            "task": task_id,
            "package": package_id,
        }

    now = time.time()
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
        "reason": "cleared only active legacy strategy-block streak; historical productivity totals preserved",
        "previous": before,
    }

    history = state.setdefault("autonomous_recovery_history", [])
    if not isinstance(history, list):
        history = []
        state["autonomous_recovery_history"] = history
    history.append({"at": now, "task": task_id, "package": package_id, "source": source, "previous": before})
    state["autonomous_recovery_history"] = history[-50:]
    state["updated_at"] = now

    return state, {
        "recovered": True,
        "task": task_id,
        "package": package_id,
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
            state, result = recover_state(state, task_id, source=source)
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
