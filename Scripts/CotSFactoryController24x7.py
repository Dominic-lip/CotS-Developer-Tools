#!/usr/bin/env python3
"""24x7 containment wrapper for the reviewed CotS Factory Controller."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

import CotSFactoryController as base
from CotS24x7Common import DailyTelemetry, safe_nonnegative_int
from CotSRecovery import RECOVERABLE_EXIT, IncidentCategory, write_incident

SCRIPTS = Path(__file__).resolve().parent
telemetry = DailyTelemetry()
_original_read_json = base.read_json
_original_start_supervisor = base.FactoryController.start_supervisor


def hardened_read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    value = _original_read_json(path, default)
    if path == base.STATE_PATH:
        attempts = value.get("repair_attempts")
        if not isinstance(attempts, dict):
            attempts = {}
        value["repair_attempts"] = {str(k): safe_nonnegative_int(v, 0) for k, v in attempts.items()}
        events = value.get("recent_events")
        value["recent_events"] = list(events)[-10:] if isinstance(events, list) else []
        for field in ("started_at", "updated_at", "supervisor_started_at"):
            if value.get(field) is not None and not isinstance(value[field], (int, float)):
                value.pop(field, None)
    return value


def _load_reviewed_completion_state(path: Path = base.COMPLETION_STATE) -> dict[str, Any]:
    """Load and fail-closed validate the reviewed roadmap through TASK-116."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"completion state unreadable: {error}") from error
    tasks = document.get("tasks")
    if document.get("schema_version") != 1:
        raise ValueError("completion state has unsupported schema version")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("completion state has no task list")
    expected = (
        {f"TASK-{number:03d}" for number in range(9)}
        | {"TASK-008A", "TASK-008B", "TASK-008C"}
        | {f"TASK-{number:03d}" for number in range(9, 17)}
        | {f"TASK-{number}" for number in range(100, 117)}
    )
    allowed = {
        "COMPLETE_VERIFIED",
        "COMPLETE_BUT_EVIDENCE_MISSING",
        "PARTIAL",
        "NOT_STARTED",
        "SUPERSEDED",
        "DEFERRED_PROVIDER_VERIFICATION",
    }
    seen: set[str] = set()
    for entry in tasks:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry["id"] in seen:
            raise ValueError("completion state has invalid or duplicate task records")
        if entry["id"] not in expected or entry.get("status") not in allowed:
            raise ValueError("completion state has invalid task records")
        if entry["status"] == "COMPLETE_VERIFIED" and not entry.get("evidence"):
            raise ValueError(f"completion state lacks evidence for {entry['id']}")
        seen.add(entry["id"])
    if seen != expected:
        raise ValueError("completion state is missing required roadmap tasks")
    return document


def hardened_authoritative_next_required_task(path: Path = base.COMPLETION_STATE) -> str | None:
    """Validate the reviewed roadmap universe through the read-only TASK-116 gate."""
    document = _load_reviewed_completion_state(path)
    return next((entry["id"] for entry in document["tasks"] if entry["status"] != "COMPLETE_VERIFIED"), None)


def reconcile_completed_checkpoint(
    checkpoint: dict[str, Any], path: Path = base.COMPLETION_STATE,
) -> tuple[dict[str, Any], bool]:
    """Retire stale task-local runtime state when the reviewed scheduler moved on.

    A persisted provider thread, handoff, or compact context from a completed
    task -- or from an unreviewed task that is no longer present in the
    fail-closed completion state -- must never outrank the checked-in scheduler
    after restart. Preserve cumulative counters and provider-capacity metadata,
    but force a fresh provider session for the next reviewed task and discard
    operational debt that belongs to completed or unreviewed tasks.
    """
    if not isinstance(checkpoint, dict):
        return {}, False
    document = _load_reviewed_completion_state(path)
    statuses = {entry["id"]: entry["status"] for entry in document["tasks"]}
    scheduled = next((entry["id"] for entry in document["tasks"] if entry["status"] != "COMPLETE_VERIFIED"), None)
    compact = checkpoint.get("compact_task_context") if isinstance(checkpoint.get("compact_task_context"), dict) else {}
    current = str(
        checkpoint.get("task")
        or checkpoint.get("active_task_override")
        or compact.get("task_id")
        or ""
    )
    if not scheduled or not current or current == scheduled:
        return dict(checkpoint), False
    current_status = statuses.get(current)
    if current_status not in {None, "COMPLETE_VERIFIED"}:
        return dict(checkpoint), False

    result = dict(checkpoint)
    result.update({
        "state": "STARTING",
        "task": scheduled,
        "phase": "RECONCILING",
        "scheduled_task": scheduled,
        "active_task_override": None,
        "active_task_before_deferred": None,
        "active_agent": None,
        "pending_handoff_target": None,
        "resuming_deferred_verification": None,
        "provider_turn": None,
        "provider_turn_started_at": None,
        "provider_turn_heartbeat_at": None,
        "compact_task_context": {
            "task_id": scheduled,
            "phase": "RECONCILING",
            "acceptance_remaining": [],
        },
        "efficiency": {},
        "current_action": f"Reconciling checked-in roadmap task {scheduled}",
    })
    for stale_field in ("human_gate", "failure", "recoverable_gate", "last_outcome"):
        result.pop(stale_field, None)

    for name, session_key in (("codex", "thread_id"), ("claude", "session_id")):
        info = dict(result.get(name)) if isinstance(result.get(name), dict) else {}
        info.pop(session_key, None)
        if info.get("status") == "ACTIVE":
            info["status"] = "IDLE"
        result[name] = info

    queue = result.get("deferred_verifications")
    if isinstance(queue, list):
        result["deferred_verifications"] = [
            entry for entry in queue
            if (
                isinstance(entry, dict)
                and statuses.get(str(entry.get("task_id") or "")) not in {None, "COMPLETE_VERIFIED"}
            )
        ]
    return result, True


def hardened_start_supervisor(self: Any, prompt: str | None = None, agents: str = "codex,claude") -> None:
    """Reconcile a stale or unreviewed checkpoint before a normal scheduler start."""
    if prompt is None:
        checkpoint = base.read_json(base.SUPERVISOR_STATE, {})
        previous_task = str(checkpoint.get("task") or "") if isinstance(checkpoint, dict) else ""
        reconciled, changed = reconcile_completed_checkpoint(checkpoint)
        if changed:
            base.atomic_json(base.SUPERVISOR_STATE, reconciled)
            self.save(
                f"Reconciled stale checkpoint {previous_task or 'unknown'} -> {reconciled.get('task')}",
                supervisor_state="RECONCILING",
            )
            telemetry.emit(
                "STALE_TASK_CHECKPOINT_RECONCILED",
                f"Retired stale checkpoint {previous_task or 'unknown'} before scheduling {reconciled.get('task')}",
                previous_task=previous_task or None,
                scheduled_task=reconciled.get("task"),
            )
    _original_start_supervisor(self, prompt=prompt, agents=agents)


def install_hardening() -> None:
    base.SUPERVISOR_SCRIPT = SCRIPTS / "CotSAgentSupervisor24x7.py"
    base.read_json = hardened_read_json
    base.authoritative_next_required_task = hardened_authoritative_next_required_task
    base.FactoryController.start_supervisor = hardened_start_supervisor


def main() -> int:
    install_hardening()
    telemetry.emit("FACTORY_START", "24x7 Factory Controller starting")
    try:
        code = int(base.main())
        telemetry.emit("FACTORY_EXIT", f"Factory Controller exited with code {code}", exit_code=code)
        return code
    except KeyboardInterrupt:
        telemetry.emit("FACTORY_STOP", "Factory Controller received keyboard interrupt")
        return 130
    except BaseException as error:
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-12000:]
        telemetry.emit("FACTORY_CRASH", f"{type(error).__name__}: {error}", traceback=trace)
        try:
            write_incident(
                IncidentCategory.FACTORY_CONTROLLER,
                f"Unhandled Factory Controller exception: {type(error).__name__}: {error}",
                affected_component="factory",
                error_code="FACTORY_UNHANDLED_EXCEPTION",
            )
        except Exception:
            pass
        print(trace, file=sys.stderr)
        return RECOVERABLE_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
