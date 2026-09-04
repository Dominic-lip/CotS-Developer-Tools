#!/usr/bin/env python3
"""Continuous campaign wrapper for the hardened CotS 24x7 Factory Controller.

Extends the reviewed scheduler through TASK-121, routes provider work through
the campaign supervisor, and preserves a genuine COMPLETE checkpoint so roadmap
completion exits cleanly instead of being reclassified as a recoverable crash.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import CotSFactoryController24x7 as h

SCRIPTS = Path(__file__).resolve().parent
CAMPAIGN_LAST_TASK = 121
_original_install = h.install_hardening
_original_mark_stopped = h.base.FactoryController.mark_supervisor_stopped


def load_campaign_completion_state(path: Path = h.base.COMPLETION_STATE) -> dict[str, Any]:
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
        | {f"TASK-{number}" for number in range(100, CAMPAIGN_LAST_TASK + 1)}
    )
    allowed = {
        "COMPLETE_VERIFIED", "COMPLETE_BUT_EVIDENCE_MISSING", "PARTIAL",
        "NOT_STARTED", "SUPERSEDED", "DEFERRED_PROVIDER_VERIFICATION",
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
        raise ValueError("completion state is missing reviewed campaign tasks")
    return document


def campaign_next_required_task(path: Path = h.base.COMPLETION_STATE) -> str | None:
    document = load_campaign_completion_state(path)
    return next((entry["id"] for entry in document["tasks"] if entry["status"] != "COMPLETE_VERIFIED"), None)


def campaign_reconcile_checkpoint(checkpoint: dict[str, Any], path: Path = h.base.COMPLETION_STATE) -> tuple[dict[str, Any], bool]:
    """Same stale-checkpoint policy as 24x7 wrapper, against campaign universe."""
    if not isinstance(checkpoint, dict):
        return {}, False
    document = load_campaign_completion_state(path)
    statuses = {entry["id"]: entry["status"] for entry in document["tasks"]}
    scheduled = next((entry["id"] for entry in document["tasks"] if entry["status"] != "COMPLETE_VERIFIED"), None)
    compact = checkpoint.get("compact_task_context") if isinstance(checkpoint.get("compact_task_context"), dict) else {}
    current = str(checkpoint.get("task") or checkpoint.get("active_task_override") or compact.get("task_id") or "")
    if not scheduled or not current or current == scheduled:
        return dict(checkpoint), False
    if statuses.get(current) not in {None, "COMPLETE_VERIFIED"}:
        return dict(checkpoint), False

    result = dict(checkpoint)
    result.update({
        "state": "STARTING", "task": scheduled, "phase": "RECONCILING",
        "scheduled_task": scheduled, "active_task_override": None,
        "active_task_before_deferred": None, "active_agent": None,
        "pending_handoff_target": None, "resuming_deferred_verification": None,
        "provider_turn": None, "provider_turn_started_at": None,
        "provider_turn_heartbeat_at": None,
        "compact_task_context": {"task_id": scheduled, "phase": "RECONCILING", "acceptance_remaining": []},
        "efficiency": {}, "current_action": f"Reconciling checked-in roadmap task {scheduled}",
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
            if isinstance(entry, dict) and statuses.get(str(entry.get("task_id") or "")) not in {None, "COMPLETE_VERIFIED"}
        ]
    return result, True


def preserve_complete_checkpoint(self: Any, checkpoint: dict[str, Any]) -> None:
    """Do not erase COMPLETE before handle_gate can verify roadmap completion."""
    if isinstance(checkpoint, dict) and checkpoint.get("state") == "COMPLETE":
        cleaned = h.base.clear_provider_activity(checkpoint, state="COMPLETE")
        cleaned["updated_at"] = time.time()
        h.base.atomic_json(h.base.SUPERVISOR_STATE, cleaned)
        return
    _original_mark_stopped(self, checkpoint)


def install_campaign() -> None:
    _original_install()
    h._load_reviewed_completion_state = load_campaign_completion_state
    h.hardened_authoritative_next_required_task = campaign_next_required_task
    h.reconcile_completed_checkpoint = campaign_reconcile_checkpoint
    h.base.authoritative_next_required_task = campaign_next_required_task
    h.base.SUPERVISOR_SCRIPT = SCRIPTS / "CotSAgentSupervisorCampaign.py"
    h.base.FactoryController.mark_supervisor_stopped = preserve_complete_checkpoint


def main() -> int:
    install_campaign()
    # h.main() would reinstall its defaults; call the already-hardened base main.
    h.telemetry.emit("FACTORY_START", "Campaign Factory Controller starting")
    try:
        code = int(h.base.main())
        h.telemetry.emit("FACTORY_EXIT", f"Campaign Factory Controller exited with code {code}", exit_code=code)
        return code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
