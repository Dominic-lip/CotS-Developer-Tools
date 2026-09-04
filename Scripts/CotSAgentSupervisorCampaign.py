#!/usr/bin/env python3
"""Continuous campaign wrapper for the reviewed CotS 24x7 supervisor.

This layer authorizes the reviewed post-TASK-116 production campaign through
TASK-121 without weakening the existing Shardlands read-only boundary or fixed
production lifecycle bridge.
"""
from __future__ import annotations

import json
import re
from typing import Any

import CotSAgentSupervisor24x7 as h

CAMPAIGN_FIRST_TASK = 117
CAMPAIGN_LAST_TASK = 121

PRODUCTION_ADAPTER_INSTRUCTIONS = rf"""
For TASK-015, TASK-100 through TASK-115, and TASK-{CAMPAIGN_FIRST_TASK} through
TASK-{CAMPAIGN_LAST_TASK} only, the scheduled task itself is explicit
authorization to modify C:\Dev\CotS within that task's stated scope. TASK-116
remains a completed read-only reconciliation gate. C:\Dev\Shardlands remains
strictly read-only. Website, Platform API and other peer repositories remain
read-only unless a later task explicitly names and authorizes a peer mutation.

All production host/filesystem/build/Git work must use the fixed audited command
`python Scripts/CotSProductionLifecycleCampaign.py ...`; do not substitute
arbitrary shell, PowerShell, raw Git mutation, arbitrary Python filesystem code,
or writes elsewhere under C:\Dev. The campaign adapter proxies those exact
fixed operations to a loopback host bridge owned by the persistent watchdog, so
provider sandbox ACLs are not a reason to attempt direct writes, global Git
configuration changes, ACL changes, or alternate host commands. If the bridge
is unavailable, report that exact lifecycle gate so the local watchdog can
restart its fixed host service; do not retry an unchanged direct-access strategy.
""".strip()


def campaign_production_task(task: object) -> bool:
    value = str(task or "")
    if value == "TASK-015":
        return True
    match = re.fullmatch(r"TASK-(\d{3})", value)
    if not match:
        return False
    number = int(match.group(1))
    return 100 <= number <= 115 or CAMPAIGN_FIRST_TASK <= number <= CAMPAIGN_LAST_TASK


def campaign_load_completion_state(path=None) -> dict[str, Any]:
    path = h.base.FOUNDATION_COMPLETION_STATE if path is None else path
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise h.base.AppServerError(f"foundation_completion_state_invalid: {error}") from error
    if document.get("schema_version") != 1:
        raise h.base.AppServerError("foundation_completion_state_invalid: unsupported schema version")
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise h.base.AppServerError("foundation_completion_state_invalid: tasks must be a non-empty list")
    expected = (
        {f"TASK-{number:03d}" for number in range(9)}
        | {"TASK-008A", "TASK-008B", "TASK-008C"}
        | {f"TASK-{number:03d}" for number in range(9, 17)}
        | {f"TASK-{number}" for number in range(100, CAMPAIGN_LAST_TASK + 1)}
    )
    seen: set[str] = set()
    allowed = {
        "COMPLETE_VERIFIED", "COMPLETE_BUT_EVIDENCE_MISSING", "PARTIAL",
        "NOT_STARTED", "SUPERSEDED", h.base.DEFERRED_PROVIDER_VERIFICATION,
    }
    for entry in tasks:
        task_id = entry.get("id") if isinstance(entry, dict) else None
        status = entry.get("status") if isinstance(entry, dict) else None
        if not isinstance(task_id, str) or task_id not in expected:
            raise h.base.AppServerError(f"foundation_completion_state_invalid: invalid task id {task_id!r}")
        if task_id in seen:
            raise h.base.AppServerError(f"foundation_completion_state_invalid: duplicate task {task_id}")
        if status not in allowed:
            raise h.base.AppServerError(f"foundation_completion_state_invalid: invalid status for {task_id}")
        if status == h.base.VERIFIED_COMPLETION_STATUS and not entry.get("evidence"):
            raise h.base.AppServerError(f"foundation_completion_state_invalid: {task_id} lacks durable evidence references")
        seen.add(task_id)
    if seen != expected:
        raise h.base.AppServerError("foundation_completion_state_invalid: reviewed campaign task records are required")
    return document


def install_campaign() -> None:
    h.hardened_load_foundation_completion_state = campaign_load_completion_state
    h._production_task = campaign_production_task
    h.PRODUCTION_ADAPTER_INSTRUCTIONS = PRODUCTION_ADAPTER_INSTRUCTIONS


def main() -> int:
    install_campaign()
    return int(h.main())


if __name__ == "__main__":
    raise SystemExit(main())
