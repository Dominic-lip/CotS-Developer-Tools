#!/usr/bin/env python3
"""Persistent, single-agent CotS supervisor using Codex App Server.

This intentionally owns ``codex app-server --stdio``. It never invokes the
interactive ``codex`` CLI. The checkpoint is local-only so a supervisor can
resume the durable App Server thread after a terminal, host, or agent restart.
"""
from __future__ import annotations

import argparse
import json
import msvcrt
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
STATE = REPO / ".cots" / "agent-supervisor.local.json"
PROTOCOL_LOG = REPO / ".cots" / "agent-supervisor.protocol.log"
LEASE = REPO / ".cots" / "agent-supervisor-lease.local.lock"
TURN_TIMEOUT_SECONDS = 2 * 60 * 60
UPDATE_TIMEOUT_SECONDS = 120

AUTONOMY_POLICY = {"granular": {
    # App Server's auto-reviewer, rather than a human, evaluates the narrow
    # fixed-wrapper sandbox escape and any proposed matching rule.
    "sandbox_approval": True, "rules": True, "skill_approval": False,
    "request_permissions": True, "mcp_elicitations": True,
}}

START = """Read and follow AGENTS.md and Docs/AUTONOMOUS_DEVELOPMENT.md.
Work autonomously through the next incomplete task. This App Server thread is
the sole mutating agent and owns the supervisor lease itself; do not mistake
that lease for another agent. Refuse only a separately observed CotS Host lock
or independently running mutating agent. Preserve the CotS/Shardlands
boundaries, Host MCP restrictions, and production bootstrap boundary. Do not
stop for routine reporting.

Routine approved work is limited to workspace edits and the fixed CotS
operations described in Docs/AUTONOMOUS_DEVELOPMENT.md. Use
Scripts/CotS-GitCompletion.py for status, diff, staged task completion, commit,
and push; do not invoke arbitrary git mutation commands. Never reset, clean,
force-push, rewrite history, run arbitrary process control, write Shardlands,
or mutate production CotS without an explicit task authorization.

If the App Server workspace sandbox denies Git metadata writes, request the
supported escalation only for the exact `Scripts/CotS-GitCompletion.py complete`
command with the task's explicit repository-relative files. The configured
auto-reviewer, not a human and not this supervisor, decides that fixed request.
Never request escalation for any other shell, Git, process, filesystem, or
network operation.

End every completed turn with exactly one marker:
SUPERVISOR_OUTCOME: CONTINUE
HUMAN_GATE: <reason>
SUPERVISOR_OUTCOME: COMPLETE"""

CONTINUE = """Continue autonomous CotS development from the current repository
and checkpoint state. Reconcile actual state first. Continue the active task or
next incomplete task. Do not stop for routine reporting. End with exactly
SUPERVISOR_OUTCOME: CONTINUE, HUMAN_GATE: <reason>, or COMPLETE."""


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"state": "STARTING", "turn_count": 0}


def save_state(value: dict[str, Any]) -> None:
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class AppServerError(RuntimeError):
    pass


class UsageResetRequired(AppServerError):
    """The service reported a rate/usage limit that requires a later resume."""


class SupervisorLease:
    """OS-held lease that refuses a second live supervisor instance."""

    def __init__(self) -> None:
        LEASE.parent.mkdir(exist_ok=True)
        LEASE.touch(exist_ok=True)
        if LEASE.stat().st_size == 0:
            LEASE.write_text(" ", encoding="utf-8")
        self.file = LEASE.open("r+", encoding="utf-8")
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            self.file.close()
            raise AppServerError("supervisor_lease_held") from error
        self.owner_id = str(uuid.uuid4())
        self.file.seek(0)
        self.file.truncate()
        self.file.write(json.dumps({"owner_id": self.owner_id, "acquired_at": time.time()}) + "\n")
        self.file.flush()

    def close(self) -> None:
        if self.file.closed:
            return
        try:
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.file.close()


class AppServer:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["codex", "app-server", "--stdio"], cwd=REPO,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.next_id = 1
        self.messages: list[dict[str, Any]] = []
        self.stderr: list[str] = []
        self.usage_reset_reason: str | None = None
        self.lock = threading.Condition()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    @staticmethod
    def _trace(prefix: str, value: Any) -> None:
        PROTOCOL_LOG.parent.mkdir(exist_ok=True)
        with PROTOCOL_LOG.open("a", encoding="utf-8") as log:
            log.write(prefix + json.dumps(value, separators=(",", ":")) + "\n")

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._trace("< ", message)
            with self.lock:
                if message.get("method") == "account/rateLimits/updated":
                    limits = message.get("params", {}).get("rateLimits", {})
                    reached = limits.get("rateLimitReachedType")
                    if reached:
                        self.usage_reset_reason = str(reached)
                self.messages.append(message)
                self.lock.notify_all()

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            with self.lock:
                self.stderr.append(line.rstrip())
                self.stderr = self.stderr[-200:]
                self.lock.notify_all()

    def _send(self, message: dict[str, Any]) -> None:
        if self.process.poll() is not None:
            raise AppServerError("app_server_exited: " + "\n".join(self.stderr[-20:]))
        assert self.process.stdin is not None
        self._trace("> ", message)
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def close(self) -> None:
        """Close only the App Server process this supervisor launched."""
        if self.process.poll() is not None:
            return
        assert self.process.stdin is not None
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._trace("! ", {"warning": "app_server_did_not_exit_after_stdin_close"})

    def request(self, method: str, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        with self.lock:
            while True:
                if self.usage_reset_reason:
                    raise UsageResetRequired(self.usage_reset_reason)
                for index, message in enumerate(self.messages):
                    if message.get("id") != request_id:
                        continue
                    self.messages.pop(index)
                    if "error" in message:
                        raise AppServerError(f"{method}: {message['error']}")
                    return message.get("result", {})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{method}: " + "\n".join(self.stderr[-20:]))
                self.lock.wait(min(remaining, 0.5))

    def _reply_to_server_request(self, message: dict[str, Any]) -> None:
        # Auto-review owns the actual risk decision. Never silently grant a
        # direct user approval if the server falls back to this client.
        method = message.get("method", "")
        if method.endswith("/requestApproval") or "Approval" in method:
            self._send({"id": message["id"], "error": {
                "code": -32001,
                "message": "Supervisor delegates approval to auto_review; direct approval denied.",
            }})

    def wait_turn(self, thread_id: str, timeout: float = TURN_TIMEOUT_SECONDS) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self.lock:
            while True:
                for index, message in enumerate(self.messages):
                    if message.get("method") == "turn/completed" and message.get("params", {}).get("threadId") == thread_id:
                        return self.messages.pop(index)["params"]["turn"]
                    if "id" in message and "method" in message:
                        request = self.messages.pop(index)
                        self._reply_to_server_request(request)
                        break
                else:
                    if self.process.poll() is not None:
                        raise AppServerError("app_server_exited: " + "\n".join(self.stderr[-20:]))
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("turn/completed: " + "\n".join(self.stderr[-20:]))
                    self.lock.wait(min(remaining, 0.5))
                    continue


def text_from(turn: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get("text", item.get("content", "")))
        for item in turn.get("items", [])
        if isinstance(item, dict) and item.get("type") in {"agentMessage", "message"}
    )


def turn_outcome(text: str) -> tuple[str, str]:
    if "HUMAN_GATE:" in text:
        return "HUMAN_GATE", text.split("HUMAN_GATE:", 1)[1].strip()
    if "SUPERVISOR_OUTCOME: COMPLETE" in text:
        return "COMPLETE", ""
    return "CONTINUING", ""


def app_settings() -> dict[str, Any]:
    return {
        "cwd": str(REPO), "developerInstructions": START,
        "approvalPolicy": AUTONOMY_POLICY, "approvalsReviewer": "auto_review",
        "sandbox": "workspace-write",
    }


def user_text(text: str) -> list[dict[str, Any]]:
    # Codex App Server v2 requires text_elements, even when it is empty.
    return [{"type": "text", "text": text, "text_elements": []}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="Update Codex before starting a session.")
    parser.add_argument("--prompt", help="Initial bounded test prompt.")
    parser.add_argument("--max-turns", type=int, help="Stop after this many completed turns (test only).")
    parser.add_argument("--fresh", action="store_true", help="Discard only the local supervisor checkpoint before a disposable proof.")
    args = parser.parse_args()
    try:
        lease = SupervisorLease()
    except AppServerError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        if args.fresh and STATE.exists():
            STATE.unlink()
        state = load_state()
        state.update({"state": "PREFLIGHT", "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip()})
        save_state(state)
        if args.update:
            try:
                subprocess.run(["codex", "update"], cwd=REPO, timeout=UPDATE_TIMEOUT_SECONDS, check=False)
            except subprocess.TimeoutExpired:
                state.update({"state": "FAILED", "failure": "codex_update_timeout", "updated_at": time.time()})
                save_state(state)
                return 2
            state["codex_version_after_update"] = subprocess.check_output(["codex", "--version"], text=True).strip()
            save_state(state)
        app = AppServer()
        try:
            app.request("initialize", {
                "clientInfo": {"name": "CotS Persistent Supervisor", "version": "1.1"},
                "capabilities": {"experimentalApi": True},
            })
            thread_id = state.get("thread_id")
            resumed = False
            if thread_id:
                try:
                    app.request("thread/resume", {"threadId": thread_id, **app_settings()})
                    resumed = True
                except (AppServerError, TimeoutError):
                    thread_id = None
            if not thread_id:
                started = app.request("thread/start", app_settings())
                thread_id = started["thread"]["id"]
                state.pop("human_gate", None)
                state.pop("failure", None)
            state.update({"state": "RUNNING_TURN", "thread_id": thread_id, "started_at": time.time()})
            save_state(state)
            prompt = args.prompt or (CONTINUE if resumed and state.get("turn_count") else START)
            while True:
                app.request("turn/start", {"threadId": thread_id, "input": user_text(prompt)}, timeout=60)
                turn = app.wait_turn(thread_id)
                text = text_from(turn)
                kind, detail = turn_outcome(text)
                state.update({"state": kind, "turn_count": state.get("turn_count", 0) + 1,
                              "last_turn": turn.get("id"), "last_output": text[-8000:], "updated_at": time.time()})
                if detail:
                    state["human_gate"] = detail
                save_state(state)
                if kind != "CONTINUING" or (args.max_turns and state["turn_count"] >= args.max_turns):
                    if args.max_turns and kind == "CONTINUING":
                        state["state"] = "COMPLETE"
                        save_state(state)
                    return 0
                state["state"] = "CONTINUING"
                save_state(state)
                prompt = CONTINUE
        except UsageResetRequired as error:
            state.update({"state": "WAITING_FOR_USAGE_RESET", "usage_reset": str(error),
                          "updated_at": time.time()})
            save_state(state)
            return 0
        except (AppServerError, TimeoutError, KeyError) as error:
            state.update({"state": "FAILED", "failure": str(error), "updated_at": time.time()})
            save_state(state)
            return 1
        finally:
            app.close()
    finally:
        lease.close()


if __name__ == "__main__":
    sys.exit(main())
