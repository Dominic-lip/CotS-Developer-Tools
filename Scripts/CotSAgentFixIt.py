#!/usr/bin/env python3
"""External, bounded repair worker for CotS factory infrastructure incidents."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from CotSRecovery import REPO, SUPERVISOR_STATE, atomic_json, fixed_git, read_json
except ModuleNotFoundError:
    from Scripts.CotSRecovery import REPO, SUPERVISOR_STATE, atomic_json, fixed_git, read_json

MAX_ATTEMPTS = 3
RESULT_PATH = REPO / ".cots" / "fixit-result.local.json"
ALLOWED_COMPONENTS = {"factory", "supervisor", "host_mcp"}


def select_provider(incident: dict[str, Any], attempt: int, available: set[str] | None = None) -> str | None:
    available = available if available is not None else {name for name in ("codex", "claude") if shutil.which(name)}
    implicated = str(incident.get("provider_state") or "")
    active = (read_json(SUPERVISOR_STATE).get("active_agent") or "").lower()
    order = ["claude", "codex"] if active == "codex" else ["codex", "claude"]
    if attempt >= 3:
        order.reverse()
    for name in order:
        if name in available and name not in implicated:
            return name
    return next((name for name in order if name in available), None)


def repair_prompt(incident: dict[str, Any], attempt: int) -> str:
    bounded = {key: incident.get(key) for key in (
        "incident_id", "fingerprint", "category", "task_id", "task_phase", "affected_component",
        "error_code", "error_message", "recommended_scope", "previous_repair_attempts")}
    bounded["relevant_recent_events"] = list(incident.get("relevant_recent_events") or [])[-12:]
    bounded["bounded_relevant_log_excerpt"] = str(incident.get("bounded_relevant_log_excerpt") or "")[-2400:]
    bounded["checkpoint"] = read_json(Path(str(incident.get("checkpoint_path") or SUPERVISOR_STATE)))
    return ("You are the external CotS AgentFixIt worker. Make one bounded repair only. "
            "Scope is C:\\Dev\\CotSDeveloperTools; Shardlands is read-only and C:\\Dev\\CotS is forbidden "
            "unless this incident explicitly authorizes production code. Do not start the normal factory. "
            "Inspect only the incident-relevant sources/logs/checkpoint below. Run targeted tests first, then "
            "py_compile for changed Python and git diff --check. Commit validated changes only through "
            "Scripts/CotS-GitCompletion.py. Preserve the original checkpoint/task and one-mutating-agent lease. "
            "End with exactly: FIXIT_RESULT: SUCCESS|RETRYABLE_FAILURE|HUMAN_REQUIRED; on success also "
            "FIXIT_COMMIT: <sha>, FIXIT_RESTART_COMPONENTS: factory,supervisor,host_mcp, and FIXIT_RESUME_TASK: TASK-xxx.\n"
            f"Attempt {attempt}/{MAX_ATTEMPTS}\n" + json.dumps(bounded, indent=2))


def parse_result(output: str, incident: dict[str, Any]) -> dict[str, Any]:
    lines = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
             for line in output.splitlines() if line.startswith("FIXIT_") and ":" in line}
    result = lines.get("FIXIT_RESULT", "RETRYABLE_FAILURE")
    if result not in {"SUCCESS", "RETRYABLE_FAILURE", "HUMAN_REQUIRED"}:
        result = "RETRYABLE_FAILURE"
    components = [item.strip() for item in lines.get("FIXIT_RESTART_COMPONENTS", "factory,supervisor,host_mcp").split(",")]
    return {"result": result, "commit": lines.get("FIXIT_COMMIT", ""),
            "restart_components": [item for item in components if item in ALLOWED_COMPONENTS],
            "resume_task": lines.get("FIXIT_RESUME_TASK") or incident.get("task_id"), "output_tail": output[-2400:]}


def validate() -> tuple[bool, str]:
    changed = [line.strip() for line in fixed_git("diff", "--name-only").splitlines() if line.strip().endswith(".py")]
    if changed:
        compiled = subprocess.run([sys.executable, "-m", "py_compile", *changed], cwd=REPO, text=True, capture_output=True, check=False)
        if compiled.returncode:
            return False, (compiled.stdout + compiled.stderr)[-1200:]
    check = subprocess.run(["git", "diff", "--check"], cwd=REPO, text=True, capture_output=True, check=False)
    return check.returncode == 0, (check.stdout + check.stderr)[-1200:]


def active_mutator(checkpoint: dict[str, Any]) -> bool:
    """Fail closed: FixIt never overlaps an indicated provider writer."""
    return bool(checkpoint.get("active_agent")) and str(checkpoint.get("state", "")).startswith("RUNNING_")


def run_incident(path: Path, attempt: int, *, runner=subprocess.run) -> dict[str, Any]:
    incident = read_json(path)
    checkpoint = read_json(Path(str(incident.get("checkpoint_path") or SUPERVISOR_STATE)))
    provider = select_provider(incident, attempt)
    if not incident or not provider:
        result = {"result": "HUMAN_REQUIRED", "reason": "incident unreadable or no trusted repair provider"}
    elif active_mutator(checkpoint):
        result = {"result": "HUMAN_REQUIRED", "reason": "active mutation provider remains live; refusing concurrent repair"}
    else:
        command = (["codex", "exec", "--full-auto", repair_prompt(incident, attempt)] if provider == "codex"
                   else ["claude", "-p", repair_prompt(incident, attempt)])
        completed = runner(command, cwd=REPO, text=True, capture_output=True, timeout=7200, check=False)
        result = parse_result((completed.stdout or "") + "\n" + (completed.stderr or ""), incident)
        result["provider"] = provider
        if result["result"] == "SUCCESS":
            ok, validation = validate()
            if not ok:
                result = {"result": "RETRYABLE_FAILURE", "provider": provider, "reason": validation}
    result.update({"incident": incident.get("incident_id"), "attempt": attempt})
    atomic_json(RESULT_PATH, result)
    return result


def emit(result: dict[str, Any]) -> None:
    print(f"FIXIT_RESULT: {result['result']}")
    if result.get("commit"): print(f"FIXIT_COMMIT: {result['commit']}")
    if result.get("restart_components"): print("FIXIT_RESTART_COMPONENTS: " + ",".join(result["restart_components"]))
    if result.get("resume_task"): print(f"FIXIT_RESUME_TASK: {result['resume_task']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", required=True, type=Path)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    emit(run_incident(args.incident, args.attempt))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
