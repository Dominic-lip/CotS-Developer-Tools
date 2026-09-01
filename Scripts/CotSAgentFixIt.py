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
    return (
        "You are the external CotS AgentFixIt worker. Make one bounded infrastructure repair only. "
        "The only writable workspace is C:\\Dev\\CotSDeveloperTools. Shardlands and C:\\Dev\\CotS are read-only/forbidden for FixIt. "
        "Do not start the normal factory or Unreal unless the incident itself is specifically a lifecycle validation incident. "
        "Inspect only incident-relevant sources/logs/checkpoint. Run the smallest relevant tests first, then py_compile for changed Python "
        "and git diff --check. Commit validated changes only through `python Scripts/CotS-GitCompletion.py --profile tooling complete ...`. "
        "Do not reset, clean, force-push, rewrite history, or include unrelated dirty files. Preserve the original task/checkpoint and "
        "single-mutating-agent lease. End with exactly: FIXIT_RESULT: SUCCESS|RETRYABLE_FAILURE|HUMAN_REQUIRED; on success also "
        "FIXIT_COMMIT: <sha>, FIXIT_RESTART_COMPONENTS: factory,supervisor,host_mcp, and FIXIT_RESUME_TASK: TASK-xxx.\n"
        f"Attempt {attempt}/{MAX_ATTEMPTS}\n" + json.dumps(bounded, indent=2)
    )


def parse_result(output: str, incident: dict[str, Any]) -> dict[str, Any]:
    lines = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip()
             for line in output.splitlines() if line.startswith("FIXIT_") and ":" in line}
    result = lines.get("FIXIT_RESULT", "RETRYABLE_FAILURE")
    if result not in {"SUCCESS", "RETRYABLE_FAILURE", "HUMAN_REQUIRED"}:
        result = "RETRYABLE_FAILURE"
    components = [item.strip() for item in lines.get("FIXIT_RESTART_COMPONENTS", "factory,supervisor,host_mcp").split(",")]
    return {
        "result": result,
        "commit": lines.get("FIXIT_COMMIT", ""),
        "restart_components": [item for item in components if item in ALLOWED_COMPONENTS],
        "resume_task": lines.get("FIXIT_RESUME_TASK") or incident.get("task_id"),
        "output_tail": output[-2400:],
    }


def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO, text=True, capture_output=True, check=False, timeout=60)


def _head() -> str:
    result = _run_git("rev-parse", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else ""


def validate(base_head: str, reported_commit: str) -> tuple[bool, str]:
    """Validate both committed and still-uncommitted repair changes.

    The old implementation validated only `git diff`, which becomes empty
    after a successful repair commit and therefore silently skipped Python
    compilation. V4 validates the base..HEAD commit range plus any residual
    worktree diff, and requires the provider's reported commit to be current.
    """
    head = _head()
    if not base_head or not head or head == base_head:
        return False, "FixIt claimed success but did not create a new commit"
    if not reported_commit:
        return False, "FixIt claimed success without FIXIT_COMMIT"
    resolved = _run_git("rev-parse", reported_commit)
    if resolved.returncode or resolved.stdout.strip() != head:
        return False, f"reported FIXIT_COMMIT does not match current HEAD ({head})"

    changed = _run_git("diff", "--name-only", f"{base_head}..{head}")
    if changed.returncode:
        return False, (changed.stdout + changed.stderr)[-1200:]
    changed_paths = [line.strip() for line in changed.stdout.splitlines() if line.strip()]
    if not changed_paths:
        return False, "repair commit contains no changed files"
    forbidden = [path for path in changed_paths if path.replace("\\", "/").startswith(("ToolLab/Content/",))]
    if forbidden:
        return False, f"FixIt infrastructure repair unexpectedly changed content assets: {forbidden!r}"

    python_files = [path for path in changed_paths if path.endswith(".py") and (REPO / path).is_file()]
    if python_files:
        compiled = subprocess.run(
            [sys.executable, "-m", "py_compile", *python_files],
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
        if compiled.returncode:
            return False, (compiled.stdout + compiled.stderr)[-1200:]

    committed_check = _run_git("diff", "--check", f"{base_head}..{head}")
    if committed_check.returncode:
        return False, (committed_check.stdout + committed_check.stderr)[-1200:]
    worktree_check = _run_git("diff", "--check")
    if worktree_check.returncode:
        return False, (worktree_check.stdout + worktree_check.stderr)[-1200:]

    # A successful bounded repair must not leave additional staged changes.
    staged = _run_git("diff", "--cached", "--name-only")
    if staged.returncode:
        return False, (staged.stdout + staged.stderr)[-1200:]
    if staged.stdout.strip():
        return False, "FixIt left staged changes after its reported repair commit"
    return True, f"validated repair commit {head} ({len(changed_paths)} files)"


def active_mutator(checkpoint: dict[str, Any]) -> bool:
    """Fail closed: FixIt never overlaps an indicated provider writer."""
    return bool(checkpoint.get("active_agent")) and str(checkpoint.get("state", "")).startswith("RUNNING_")


def run_incident(path: Path, attempt: int, *, runner=subprocess.run) -> dict[str, Any]:
    incident = read_json(path)
    checkpoint = read_json(Path(str(incident.get("checkpoint_path") or SUPERVISOR_STATE)))
    provider = select_provider(incident, attempt)
    base_head = _head()
    if not incident:
        result = {"result": "HUMAN_REQUIRED", "reason": "incident unreadable"}
    elif not provider:
        result = {"result": "WAITING_FOR_PROVIDER", "reason": "no repair provider currently available"}
    elif active_mutator(checkpoint):
        result = {"result": "HUMAN_REQUIRED", "reason": "active mutation provider remains live; refusing concurrent repair"}
    elif not base_head:
        result = {"result": "HUMAN_REQUIRED", "reason": "tooling repository HEAD is unavailable"}
    else:
        command = (["codex", "exec", "--full-auto", repair_prompt(incident, attempt)] if provider == "codex"
                   else ["claude", "-p", repair_prompt(incident, attempt)])
        completed = runner(command, cwd=REPO, text=True, capture_output=True, timeout=7200, check=False)
        output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        result = parse_result(output, incident)
        result["provider"] = provider
        result["provider_exit_code"] = completed.returncode
        if completed.returncode != 0 and result["result"] == "SUCCESS":
            result = {"result": "RETRYABLE_FAILURE", "provider": provider, "reason": f"repair provider exited {completed.returncode}"}
        elif result["result"] == "SUCCESS":
            ok, validation = validate(base_head, str(result.get("commit") or ""))
            result["validation"] = validation
            if not ok:
                result = {"result": "RETRYABLE_FAILURE", "provider": provider, "reason": validation}
    result.update({"incident": incident.get("incident_id"), "attempt": attempt, "base_head": base_head})
    atomic_json(RESULT_PATH, result)
    return result


def emit(result: dict[str, Any]) -> None:
    print(f"FIXIT_RESULT: {result['result']}")
    if result.get("commit"):
        print(f"FIXIT_COMMIT: {result['commit']}")
    if result.get("restart_components"):
        print("FIXIT_RESTART_COMPONENTS: " + ",".join(result["restart_components"]))
    if result.get("resume_task"):
        print(f"FIXIT_RESUME_TASK: {result['resume_task']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident", required=True, type=Path)
    parser.add_argument("--attempt", type=int, required=True, choices=range(1, MAX_ATTEMPTS + 1))
    args = parser.parse_args()
    emit(run_incident(args.incident, args.attempt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
