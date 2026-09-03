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


def hardened_authoritative_next_required_task(path: Path = base.COMPLETION_STATE) -> str | None:
    """Validate the reviewed roadmap universe through the read-only TASK-116 gate."""
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
    return next((entry["id"] for entry in tasks if entry["status"] != "COMPLETE_VERIFIED"), None)


def install_hardening() -> None:
    base.SUPERVISOR_SCRIPT = SCRIPTS / "CotSAgentSupervisor24x7.py"
    base.read_json = hardened_read_json
    base.authoritative_next_required_task = hardened_authoritative_next_required_task


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
