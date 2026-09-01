#!/usr/bin/env python3
"""Profile-aware V4 wrapper around the proven CotS Factory controller."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import CotSFactoryController as legacy
from CotSWorkspaceProfiles import profile_for_task

TOOLS_REPO = SCRIPT_DIR.parent
HOST_V4 = SCRIPT_DIR / "CotSHostMcpV4Runner.py"
SUPERVISOR_V4 = SCRIPT_DIR / "CotSAgentSupervisorV4.py"
BOOTSTRAP_PRODUCTION = SCRIPT_DIR / "Bootstrap-CotS-Production.py"
STOP_REQUEST = TOOLS_REPO / ".cots" / "factory-stop-request.local.json"


class FactoryControllerV4(legacy.FactoryController):
    def __init__(self) -> None:
        super().__init__()
        self.v4_generation = f"factory-{os.getpid()}-{uuid.uuid4().hex[:10]}"
        self.v4_host_profile: str | None = None
        # A stop request applies to one live generation only; never let a stale
        # request from a previous stopped run poison a new launch.
        try:
            STOP_REQUEST.unlink()
        except FileNotFoundError:
            pass

    def selected_profile(self):
        task = legacy.authoritative_next_required_task()
        return task, profile_for_task(task)

    def child_env(self, profile_name: str) -> dict[str, str]:
        env = os.environ.copy()
        env["COTS_WORKSPACE_PROFILE"] = profile_name
        env["COTS_FACTORY_PID"] = str(os.getpid())
        env["COTS_FACTORY_GENERATION"] = self.v4_generation
        return env

    def ensure_task_workspace(self, task: str | None) -> None:
        if task != "TASK-015":
            return
        completed = subprocess.run(
            [sys.executable, str(BOOTSTRAP_PRODUCTION)],
            cwd=TOOLS_REPO,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(
                "production workspace bootstrap failed: "
                + ((completed.stdout or "") + (completed.stderr or ""))[-1600:]
            )

    def start_host(self) -> None:
        task, profile = self.selected_profile()
        self.ensure_task_workspace(task)
        if self.host is not None and self.host.poll() is None and self.v4_host_profile == profile.name:
            return
        if self.host is not None and self.host.poll() is None:
            self.stop_owned(self.host, "Host MCP")
            self.host = None
        self.host = subprocess.Popen(
            [sys.executable, str(HOST_V4)],
            cwd=TOOLS_REPO,
            env=self.child_env(profile.name),
            text=True,
        )
        self.v4_host_profile = profile.name
        self.save(
            "V4 Host MCP started",
            host_state="STARTING",
            host_pid=self.host.pid,
            workspace_profile=profile.name,
            workspace=str(profile.workspace_root),
            target_repository=profile.repository,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if legacy.host_ready():
                self.save("V4 Host MCP ready", host_state="READY")
                return
            if self.host.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError(f"V4 Host MCP failed to start for profile {profile.name}")

    def start_supervisor(self, prompt: str | None = None, agents: str = "codex,claude") -> None:
        task, profile = self.selected_profile()
        self.ensure_task_workspace(task)
        if self.v4_host_profile != profile.name:
            self.start_host()
        args = [sys.executable, str(SUPERVISOR_V4), "--no-dashboard", "--agents", agents]
        if prompt:
            args += ["--prompt", prompt, "--max-turns", "1"]
        self.supervisor = subprocess.Popen(
            args,
            cwd=TOOLS_REPO,
            env=self.child_env(profile.name),
            text=True,
        )
        self.save(
            "V4 Supervisor started",
            factory="RUNNING",
            supervisor_state="REPAIRING" if prompt else "RUNNING",
            supervisor_pid=self.supervisor.pid,
            supervisor_started_at=time.time(),
            workspace_profile=profile.name,
            workspace=str(profile.workspace_root),
            target_repository=profile.repository,
            scheduled_task=task,
            factory_generation=self.v4_generation,
        )

    def handle_gate(self, exit_code: int | None, forced=None) -> bool:
        if STOP_REQUEST.exists():
            checkpoint = legacy.read_json(legacy.SUPERVISOR_STATE, {})
            self.mark_supervisor_stopped(checkpoint)
            try:
                STOP_REQUEST.unlink()
            except FileNotFoundError:
                pass
            self._exit_code = 0
            self.save(
                "Operator safe stop completed at supervisor boundary",
                factory="STOPPED",
                supervisor_state="STOPPED",
                recovery={"state": "IDLE"},
            )
            return False
        return super().handle_gate(exit_code, forced)


def main() -> int:
    return FactoryControllerV4().run()


if __name__ == "__main__":
    raise SystemExit(main())
