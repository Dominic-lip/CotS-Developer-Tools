#!/usr/bin/env python3
"""Outer, fixed-scope recovery controller for autonomous CotS development.

This controller owns only the Host MCP and supervisor processes it starts.  It
does not expose a shell, accept executable paths, or kill arbitrary PIDs.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import subprocess
import sys
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

try:  # Supports both ``python Scripts/...`` and importlib-loaded unit tests.
    from CotSFactoryDashboard import TerminalDashboard, strip_terminal_controls
except ModuleNotFoundError:
    from Scripts.CotSFactoryDashboard import TerminalDashboard, strip_terminal_controls

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
COTS = REPO / ".cots"
STATE_PATH = COTS / "factory-controller.local.json"
SUPERVISOR_STATE = COTS / "agent-supervisor.local.json"
HOST_SCRIPT = SCRIPTS / "CotSHostMcp.py"
SUPERVISOR_SCRIPT = SCRIPTS / "CotSAgentSupervisor.py"
MAX_REPAIR_ATTEMPTS = 3
POLL_SECONDS = 1.0
DASHBOARD_REFRESH_SECONDS = 0.75
CHECKPOINT_STALE_SECONDS = 90.0
SUPERVISOR_STARTUP_GRACE_SECONDS = 30.0
TERMINAL_BOUNDARY_WAIT_SECONDS = 15.0

# This is the factory's authoritative interpretation of supervisor states.
# Keep names emitted by CotSAgentSupervisor plus the transitional provider
# lifecycle names retained by older checkpoints/dashboard clients.  A state
# outside this set is *not* a failure while the owned child and its heartbeat
# are healthy; it follows the UNKNOWN_LIVE_STATE watchdog path below.
NONTERMINAL_SUPERVISOR_STATES = frozenset({
    "STARTING", "PREFLIGHT", "RECONCILING", "RUNNING_CODEX", "RUNNING_CLAUDE",
    "CLAUDE_STARTING", "CLAUDE_READY", "CLAUDE_TURN_STARTING", "ROTATING_AGENT",
    "WAITING_FOR_AGENT_CAPACITY", "WAITING_FOR_USAGE_RESET", "PROBING_AVAILABILITY",
    "STALLED_PROVIDER", "CHECKPOINTING", "CONTINUING", "STOPPING",
})
TERMINAL_SUPERVISOR_STATES = frozenset({"COMPLETE", "FAILED", "TERMINAL_FAILURE", "RECOVERABLE_GATE", "HUMAN_REQUIRED", "HUMAN_GATE"})


class GateCategory(str, Enum):
    RECOVERABLE_PROVIDER = "RECOVERABLE_PROVIDER"
    RECOVERABLE_HOST_MCP = "RECOVERABLE_HOST_MCP"
    RECOVERABLE_SUPERVISOR = "RECOVERABLE_SUPERVISOR"
    RECOVERABLE_UNREAL_LIFECYCLE = "RECOVERABLE_UNREAL_LIFECYCLE"
    RECOVERABLE_BUILD_TEST = "RECOVERABLE_BUILD_TEST"
    RECOVERABLE_VALIDATION_TOPOLOGY = "RECOVERABLE_VALIDATION_TOPOLOGY"
    RECOVERABLE_STALE_STATE = "RECOVERABLE_STALE_STATE"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


RECOVERABLE = frozenset(category for category in GateCategory if category.name.startswith("RECOVERABLE_"))


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default.copy()
    except (FileNotFoundError, json.JSONDecodeError):
        return default.copy()


def read_checkpoint() -> tuple[dict[str, Any], bool]:
    """Return the raw checkpoint and whether its minimum control shape is valid."""
    try:
        value = json.loads(SUPERVISOR_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}, False
    return value, isinstance(value, dict) and isinstance(value.get("state"), str) and bool(value["state"])


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def tail(path: Path, limit: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def host_ready() -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", 8010, timeout=1)
    try:
        connection.request("POST", "/mcp", body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}), headers={"Content-Type": "application/json"})
        return connection.getresponse().status == 200
    except OSError:
        return False
    finally:
        connection.close()


def fixed_git(*args: str) -> str:
    """Read-only, fixed Git inspection. No user-controlled command is accepted."""
    completed = subprocess.run(["git", *args], cwd=REPO, text=True, capture_output=True, timeout=20, check=False)
    return (completed.stdout + completed.stderr)[-12000:]


def classify_gate(checkpoint: dict[str, Any], supervisor_exit: int | None = None) -> tuple[GateCategory, str, str]:
    """Classify structured state first; compatibility fallbacks are narrow."""
    structured = checkpoint.get("recoverable_gate")
    if isinstance(structured, dict):
        try:
            category = GateCategory(str(structured.get("category")))
        except ValueError:
            category = GateCategory.TERMINAL_FAILURE
        return category, str(structured.get("reason") or "unspecified"), str(structured.get("recommended_action") or "repair")
    state = checkpoint.get("state")
    reason = str(checkpoint.get("human_gate") or checkpoint.get("failure") or "")
    # Compatibility for pre-structured incidents. These exact terms are legacy
    # contract values, not a broad natural-language classifier.
    if state == "HUMAN_GATE" and "nested `codex exec`" in reason:
        return GateCategory.RECOVERABLE_VALIDATION_TOPOLOGY, reason, "use_active_adapter"
    if state == "HUMAN_GATE" and any(token in reason.lower() for token in ("login", "mfa", "credential", "secret", "subscription", "payment")):
        return GateCategory.HUMAN_REQUIRED, reason, "human_authentication_or_decision"
    if state in {"HUMAN_GATE", "HUMAN_REQUIRED"}:
        return GateCategory.TERMINAL_FAILURE, reason or "human decision required", "inspect"
    if state == "RECOVERABLE_GATE":
        return GateCategory.RECOVERABLE_SUPERVISOR, reason or "unstructured recoverable gate", "restart_supervisor"
    if state in {"FAILED", "TERMINAL_FAILURE"}:
        return GateCategory.RECOVERABLE_SUPERVISOR, reason or "supervisor failed", "restart_supervisor"
    if supervisor_exit is not None:
        return GateCategory.RECOVERABLE_SUPERVISOR, reason or "supervisor exited", "restart_supervisor"
    return GateCategory.RECOVERABLE_SUPERVISOR, reason or f"supervisor reached unexpected boundary {state!r}", "restart_supervisor"


def incident_fingerprint(category: GateCategory, reason: str, checkpoint: dict[str, Any]) -> str:
    material = "|".join((category.value, reason, str(checkpoint.get("task")), str(checkpoint.get("phase"))))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def choose_repair_agents(checkpoint: dict[str, Any]) -> str:
    active = checkpoint.get("active_agent")
    candidates = [name for name in ("codex", "claude") if checkpoint.get(name, {}).get("status") not in {"NOT_INSTALLED", "USAGE_EXHAUSTED"}]
    if active in candidates and len(candidates) > 1:
        candidates.remove(active); candidates.append(active)
    return ",".join(candidates or ["codex", "claude"])


def repair_prompt(evidence: dict[str, Any], attempt: int) -> str:
    return """You are executing one bounded CotS infrastructure repair turn. Diagnose only the captured evidence below. Repair scope is C:\\Dev\\CotSDeveloperTools infrastructure only unless the original task explicitly permits more. Do not write Shardlands or CotS. Make the smallest coherent fix, run relevant tests, run py_compile for changed Python, run git diff --check, and commit only through Scripts/CotS-GitCompletion.py if validation passes. Do not claim success if validation fails. Preserve the original task/checkpoint and do not begin TASK-100. Return exactly these machine-readable lines at the end:\nSUPERVISOR_TASK: {task}\nSUPERVISOR_PHASE: factory-repair\nSUPERVISOR_OUTCOME: CONTINUE\n\nCAPTURED FACTORY EVIDENCE (attempt {attempt}/{maximum}):\n{payload}""".format(task=evidence.get("task") or "RECONCILING", attempt=attempt, maximum=MAX_REPAIR_ATTEMPTS, payload=json.dumps(evidence, indent=2)[-14000:])


class FactoryController:
    """Owns only exact Popen children created by this instance."""
    def __init__(self) -> None:
        self.host: subprocess.Popen[str] | None = None
        self.supervisor: subprocess.Popen[str] | None = None
        self.state = read_json(STATE_PATH, {"repair_attempts": {}, "recent_events": []})
        self.state.setdefault("repair_attempts", {})
        self.state.setdefault("recent_events", [])
        self.state.setdefault("started_at", time.time())
        self.dashboard_stop = threading.Event()
        self.dashboard_thread: threading.Thread | None = None
        self._git_snapshot: dict[str, Any] = {}
        self._git_snapshot_at = 0.0

    def save(self, event: str | None = None, **fields: Any) -> None:
        self.state.update(fields)
        self.state["updated_at"] = time.time()
        if event:
            stamp = time.strftime("%H:%M:%S")
            self.state["recent_events"] = (self.state["recent_events"] + [f"{stamp}  {strip_terminal_controls(event)}"])[-10:]
        atomic_json(STATE_PATH, self.state)

    @staticmethod
    def task_title(task: object) -> str:
        """Read a task heading for display only; task selection remains supervisor-owned."""
        task_id = str(task or "")
        if not task_id.startswith("TASK-"):
            return ""
        number = task_id.removeprefix("TASK-").split("-", 1)[0]
        for path in sorted((REPO / "Tasks").glob(f"{number}*")):
            try:
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("#"):
                        return line.lstrip("# ").strip()
            except OSError:
                continue
        return ""

    def dashboard_snapshot(self) -> dict[str, Any]:
        """Assemble telemetry for presentation without feeding it into control flow."""
        checkpoint = read_json(SUPERVISOR_STATE, {})
        snapshot = dict(self.state)
        snapshot["supervisor"] = checkpoint
        snapshot["task_title"] = self.task_title(checkpoint.get("task"))
        snapshot["next_expected_action"] = (
            snapshot.get("recovery", {}).get("current_action")
            or checkpoint.get("scheduled_task")
            or ("Monitor active agent turn" if str(checkpoint.get("state", "")).startswith("RUNNING_") else None)
        )
        if time.monotonic() - self._git_snapshot_at >= 5.0:
            try:
                self._git_snapshot = {"git_branch": fixed_git("rev-parse", "--abbrev-ref", "HEAD").strip() or "?"}
                status_lines = [line for line in fixed_git("status", "--porcelain=v1").splitlines() if line.strip()]
                self._git_snapshot["git_status"] = "clean" if not status_lines else f"dirty ({len(status_lines)} paths)"
                self._git_snapshot["git_status_counts"] = {
                    "protected": sum(1 for line in status_lines if not line[3:].replace("\\", "/").startswith("Scripts/")),
                    "untracked_other": sum(1 for line in status_lines if line.startswith("??") and not line[3:].replace("\\", "/").startswith("Scripts/")),
                    "supervisor": sum(1 for line in status_lines if line[3:].replace("\\", "/").startswith("Scripts/")),
                }
                self._git_snapshot["last_commit"] = fixed_git("log", "-1", "--format=%h %s").strip() or "(no commits)"
                self._git_snapshot_at = time.monotonic()
            except Exception:
                self._git_snapshot = {"git_branch": "?", "git_status": "unavailable", "last_commit": "?"}
                self._git_snapshot_at = time.monotonic()
        snapshot.update(self._git_snapshot)
        return snapshot

    def start_dashboard(self) -> None:
        if self.dashboard_thread is not None:
            return
        dashboard = TerminalDashboard()
        def refresh() -> None:
            while not self.dashboard_stop.is_set():
                dashboard.draw(self.dashboard_snapshot())
                self.dashboard_stop.wait(DASHBOARD_REFRESH_SECONDS)
            dashboard.draw(self.dashboard_snapshot())
        self.dashboard_thread = threading.Thread(target=refresh, name="cots-factory-dashboard", daemon=True)
        self.dashboard_thread.start()

    def stop_dashboard(self) -> None:
        self.dashboard_stop.set()
        if self.dashboard_thread is not None:
            self.dashboard_thread.join(timeout=3)
            self.dashboard_thread = None

    def start_host(self) -> None:
        if host_ready():
            self.save("Host MCP already ready; attached without ownership", host_state="READY", host_pid=None)
            return
        self.host = subprocess.Popen([sys.executable, str(HOST_SCRIPT)], cwd=REPO, text=True)
        self.save("Owned Host MCP started", host_state="STARTING", host_pid=self.host.pid)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if host_ready():
                self.save("Owned Host MCP ready", host_state="READY")
                return
            if self.host.poll() is not None:
                break
            time.sleep(0.2)
        self.save("Owned Host MCP unavailable", host_state="FAILED")

    def stop_owned(self, process: subprocess.Popen[str] | None, label: str) -> None:
        if process is None or process.poll() is not None:
            return
        pid = process.pid
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=10)
        # terminate()/kill() only end this one process. The supervisor spawns
        # its own `claude -p`/`codex` child as a separate OS process, which
        # Windows does not tie to its parent's lifetime, so it survives as an
        # orphan that keeps mutating the working tree as an undetected second
        # agent. Sweep the whole tree rooted at the owned PID to close that.
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False)
        self.save(f"Owned {label} stopped")

    def start_supervisor(self, prompt: str | None = None, agents: str = "codex,claude") -> None:
        args = [sys.executable, str(SUPERVISOR_SCRIPT), "--no-dashboard", "--agents", agents]
        if prompt:
            args += ["--prompt", prompt, "--max-turns", "1"]
        self.supervisor = subprocess.Popen(args, cwd=REPO, text=True)
        self.save("Supervisor started", factory="RUNNING", supervisor_state="REPAIRING" if prompt else "RUNNING", supervisor_pid=self.supervisor.pid, supervisor_started_at=time.time())

    @staticmethod
    def checkpoint_age(checkpoint: dict[str, Any], now: float | None = None) -> float:
        """Use the durable heartbeat; mtime is a compatibility fallback."""
        now = time.time() if now is None else now
        updated_at = checkpoint.get("updated_at")
        if isinstance(updated_at, (int, float)):
            return max(0.0, now - updated_at)
        try:
            return max(0.0, now - SUPERVISOR_STATE.stat().st_mtime)
        except OSError:
            return float("inf")

    @staticmethod
    def checkpoint_heartbeat_at(checkpoint: dict[str, Any]) -> float:
        updated_at = checkpoint.get("updated_at")
        if isinstance(updated_at, (int, float)):
            return float(updated_at)
        try:
            return SUPERVISOR_STATE.stat().st_mtime
        except OSError:
            return 0.0

    def live_supervisor_boundary(self, now: float | None = None) -> tuple[GateCategory | None, str | None]:
        """Assess a still-running child without inferring death from its text."""
        assert self.supervisor is not None
        if self.supervisor.poll() is not None:
            return GateCategory.RECOVERABLE_SUPERVISOR, "owned supervisor process exited"
        checkpoint, valid = read_checkpoint()
        started_at = float(self.state.get("supervisor_started_at", now or time.time()))
        current = time.time() if now is None else now
        if not valid:
            if current - started_at <= SUPERVISOR_STARTUP_GRACE_SECONDS:
                return None, None
            return GateCategory.RECOVERABLE_STALE_STATE, "supervisor checkpoint is structurally invalid"
        state = checkpoint["state"]
        age = self.checkpoint_age(checkpoint, current)
        if age > CHECKPOINT_STALE_SECONDS:
            return GateCategory.RECOVERABLE_STALE_STATE, f"supervisor heartbeat stale for {age:.0f}s (state {state!r})"
        if self.checkpoint_heartbeat_at(checkpoint) < started_at:
            if current - started_at <= SUPERVISOR_STARTUP_GRACE_SECONDS:
                return None, None
            return GateCategory.RECOVERABLE_STALE_STATE, "supervisor has not emitted a post-launch checkpoint heartbeat"
        if state in {"RECOVERABLE_GATE", "FAILED", "TERMINAL_FAILURE"}:
            category, reason, _ = classify_gate(checkpoint)
            return category, reason
        if state in {"HUMAN_GATE", "HUMAN_REQUIRED"}:
            category, reason, _ = classify_gate(checkpoint)
            return category, reason
        if state == "COMPLETE":
            return GateCategory.TERMINAL_FAILURE, "roadmap completion verified"
        if state not in NONTERMINAL_SUPERVISOR_STATES:
            # Fresh unknown states are deliberately nonterminal.  The heartbeat
            # watchdog remains the bounded recovery mechanism.
            if self.state.get("unknown_live_state") != state:
                self.save(f"UNKNOWN_LIVE_STATE: {state}; monitoring fresh owned supervisor", supervisor_state="UNKNOWN_LIVE_STATE", unknown_live_state=state)
            return None, None
        if self.state.get("unknown_live_state"):
            self.save("Recognized supervisor lifecycle state resumed", unknown_live_state=None)
        return None, None

    def await_terminal_boundary(self, reason: str) -> int | None:
        """Let a real gate finish its checkpoint/turn boundary before a kill."""
        assert self.supervisor is not None
        deadline = time.monotonic() + TERMINAL_BOUNDARY_WAIT_SECONDS
        while self.supervisor.poll() is None and time.monotonic() < deadline:
            time.sleep(POLL_SECONDS)
        if self.supervisor.poll() is None:
            self.save(f"Supervisor boundary timeout: {reason}; stopping owned child")
            self.stop_owned(self.supervisor, "supervisor")
        return self.supervisor.poll()

    def capture(self, category: GateCategory, reason: str) -> dict[str, Any]:
        checkpoint = read_json(SUPERVISOR_STATE, {})
        return {
            "category": category.value, "reason": reason, "task": checkpoint.get("task"), "phase": checkpoint.get("phase"),
            "checkpoint": checkpoint, "git_status": fixed_git("status", "--porcelain=v1"),
            "git_head": fixed_git("rev-parse", "HEAD").strip(), "host_ready": host_ready(),
            "supervisor_events": tail(COTS / "supervisor-events.log"), "codex_protocol": tail(COTS / "codex-protocol.log"),
            "claude_protocol": tail(COTS / "claude-protocol.log"),
        }

    def handle_gate(self, exit_code: int | None, forced: tuple[GateCategory, str] | None = None) -> bool:
        checkpoint = read_json(SUPERVISOR_STATE, {})
        if checkpoint.get("state") == "COMPLETE":
            self.save("Roadmap completion verified", factory="COMPLETE", supervisor_state="STOPPED")
            return False
        category, reason = forced if forced else classify_gate(checkpoint, exit_code)[:2]
        fingerprint = incident_fingerprint(category, reason, checkpoint)
        attempts = int(self.state["repair_attempts"].get(fingerprint, 0))
        self.save(f"Supervisor gate {category.value}: {reason}", recovery={"state": "GATED", "category": category.value, "incident": fingerprint, "attempt": attempts})
        if category in {GateCategory.HUMAN_REQUIRED, GateCategory.TERMINAL_FAILURE} or attempts >= MAX_REPAIR_ATTEMPTS:
            self.save("Human-required unresolved incident", factory="HUMAN_REQUIRED", supervisor_state="STOPPED", recovery={"state": "HUMAN_REQUIRED", "category": category.value, "incident": fingerprint, "attempt": attempts, "reason": reason})
            return False
        attempts += 1
        self.state["repair_attempts"][fingerprint] = attempts
        evidence = self.capture(category, reason)
        self.save("Repair turn scheduled", factory="RUNNING", supervisor_state="REPAIRING", recovery={"state": "REPAIRING", "category": category.value, "incident": fingerprint, "attempt": attempts})
        self.start_supervisor(repair_prompt(evidence, attempts), choose_repair_agents(checkpoint))
        return True

    def run(self) -> int:
        self.start_dashboard()
        try:
            self.start_host()
            self.start_supervisor()
            repair_mode = False
            while True:
                assert self.supervisor is not None
                exit_code = self.supervisor.poll()
                if exit_code is None:
                    boundary = self.live_supervisor_boundary()
                    if boundary[0] is None:
                        time.sleep(POLL_SECONDS); continue
                    category, reason = boundary
                    exit_code = self.await_terminal_boundary(reason or "supervisor boundary")
                    if not self.handle_gate(exit_code, (category, reason or "supervisor boundary")):
                        return 0
                    repair_mode = True
                    continue
                if repair_mode:
                # A repair turn is bounded to one completed supervisor turn.
                # Its own validation/commit result is in the checkpoint and
                # protocol log; only then is the normal task supervisor relaunched.
                    self.save("Repair turn ended; applying controlled restarts", supervisor_state="RESTARTING")
                    changed = fixed_git("show", "--format=", "--name-only", "HEAD").replace("\\", "/").splitlines()
                    if "Scripts/CotSHostMcp.py" in changed and self.host is not None:
                        self.stop_owned(self.host, "Host MCP"); self.host = None; self.start_host()
                    repair_mode = False
                    self.start_supervisor()
                    continue
                if not self.handle_gate(exit_code):
                    return 0
                repair_mode = True
        finally:
            self.stop_dashboard()


def main() -> int:
    parser = argparse.ArgumentParser(description="CotS fixed-scope autonomous factory controller")
    parser.add_argument("--once", action="store_true", help="Start fixed children then perform one monitor pass (test only).")
    args = parser.parse_args()
    controller = FactoryController()
    if args.once:
        controller.start_host(); controller.start_supervisor(); return 0
    try:
        return controller.run()
    except KeyboardInterrupt:
        controller.stop_owned(controller.supervisor, "supervisor")
        controller.stop_owned(controller.host, "Host MCP")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
