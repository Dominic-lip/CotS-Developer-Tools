#!/usr/bin/env python3
"""Small, dependency-free contract shared by Factory, Bootstrap and FixIt."""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from enum import Enum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
COTS = REPO / ".cots"
INCIDENTS = COTS / "incidents"
SUPERVISOR_STATE = COTS / "agent-supervisor.local.json"
FACTORY_STATE = COTS / "factory-controller.local.json"
MAX_INCIDENT_LOG = 2400
MAX_EVENTS = 12
RECOVERABLE_EXIT = 75
HUMAN_REQUIRED_EXIT = 76


class IncidentCategory(str, Enum):
    FACTORY_CONTROLLER = "FACTORY_CONTROLLER"
    SUPERVISOR = "SUPERVISOR"
    HOST_MCP = "HOST_MCP"
    UNREAL_MCP = "UNREAL_MCP"
    PROVIDER_HANDOFF = "PROVIDER_HANDOFF"
    CHECKPOINT_STATE = "CHECKPOINT_STATE"
    PROCESS_LIFECYCLE = "PROCESS_LIFECYCLE"
    VALIDATION_TOPOLOGY = "VALIDATION_TOPOLOGY"
    BUILD_TEST = "BUILD_TEST"
    DASHBOARD_STATE = "DASHBOARD_STATE"
    CAPACITY_WAIT = "CAPACITY_WAIT"
    OTHER_RECOVERABLE_INFRASTRUCTURE = "OTHER_RECOVERABLE_INFRASTRUCTURE"


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default or {})
    except (OSError, json.JSONDecodeError):
        return dict(default or {})


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Windows readers can transiently hold the destination open.
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def fixed_git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO, text=True, capture_output=True,
                            timeout=20, check=False)
    return (result.stdout + result.stderr)[-6000:]


def tail(path: Path, limit: int = MAX_INCIDENT_LOG) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def fingerprint(category: str, message: str, checkpoint: dict[str, Any]) -> str:
    material = "|".join((category, message[:500], str(checkpoint.get("task")), str(checkpoint.get("phase"))))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def write_incident(category: IncidentCategory | str, message: str, *, affected_component: str,
                   error_code: str = "RECOVERABLE", recommended_scope: str = "factory_infrastructure",
                   checkpoint: dict[str, Any] | None = None, factory_state: dict[str, Any] | None = None,
                   previous_repair_attempts: int = 0) -> Path:
    """Persist only bounded control evidence.  This file is FixIt's whole input."""
    checkpoint = checkpoint if checkpoint is not None else read_json(SUPERVISOR_STATE)
    factory_state = factory_state if factory_state is not None else read_json(FACTORY_STATE)
    category_value = category.value if isinstance(category, IncidentCategory) else str(category)
    ident = fingerprint(category_value, message, checkpoint)
    events = list(checkpoint.get("recent_events") or factory_state.get("recent_events") or [])[-MAX_EVENTS:]
    logs = "\n".join(filter(None, [
        tail(COTS / "supervisor-events.log", 1200),
        tail(COTS / "host-mcp.log", 600),
        tail(COTS / "factory.log", 600),
    ]))[-MAX_INCIDENT_LOG:]
    incident = {
        "incident_id": ident, "fingerprint": ident, "category": category_value,
        "timestamp": time.time(), "task_id": checkpoint.get("task"), "task_phase": checkpoint.get("phase"),
        "factory_state": factory_state.get("factory") or factory_state.get("state"),
        "supervisor_state": checkpoint.get("state"), "provider_state": {
            name: (checkpoint.get(name) or {}).get("status") for name in ("codex", "claude")},
        "checkpoint_path": str(SUPERVISOR_STATE), "git_head": fixed_git("rev-parse", "HEAD").strip(),
        "git_status": fixed_git("status", "--porcelain=v1")[-2000:], "affected_component": affected_component,
        "error_code": error_code, "error_message": str(message)[:1200],
        "relevant_recent_events": [str(item)[:400] for item in events],
        "bounded_relevant_log_excerpt": logs, "previous_repair_attempts": previous_repair_attempts,
        "recommended_scope": recommended_scope,
    }
    path = INCIDENTS / f"{ident}.json"
    atomic_json(path, incident)
    return path
