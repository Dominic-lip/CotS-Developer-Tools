#!/usr/bin/env python3
"""Persistent, agent-neutral CotS supervisor with a live status dashboard.

Owns exactly one mutating agent at a time: a Codex ``app-server --stdio``
process, or a single ``claude -p`` invocation per turn. It never starts an
interactive ``codex`` or ``claude`` session. See
``Tasks/008B_PERSISTENT_AGENT_SUPERVISOR.md`` and
``Tasks/008C_SUPERVISOR_DASHBOARD.md``.

The console shows only a redrawn-in-place summary (see ``render_frame``).
Raw protocol traffic goes to ``.cots/codex-protocol.log`` and
``.cots/claude-protocol.log``; summarized human-facing events go to
``.cots/supervisor-events.log``. Neither is printed to the console.
"""
from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import msvcrt
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
COTS_DIR = REPO / ".cots"
STATE = COTS_DIR / "agent-supervisor.local.json"
CODEX_PROTOCOL_LOG = COTS_DIR / "codex-protocol.log"
CLAUDE_PROTOCOL_LOG = COTS_DIR / "claude-protocol.log"
EVENTS_LOG = COTS_DIR / "supervisor-events.log"
LEASE = COTS_DIR / "agent-supervisor-lease.local.lock"

TURN_TIMEOUT_SECONDS = 2 * 60 * 60
UPDATE_TIMEOUT_SECONDS = 120
CAPACITY_RECHECK_SECONDS = 300
MAX_RECENT_EVENTS = 10
DASHBOARD_REFRESH_SECONDS = 1.0
EXTERNAL_PROBE_SECONDS = 5.0
HOST_MCP_HOST, HOST_MCP_PORT = "127.0.0.1", 8010

# --- Hot-loop / stall circuit breaker (TASK-008C fix) ---------------------
# A turn is "suspicious" when it finished almost instantly with no assistant
# text and no recorded tool/item activity. Three of those in a row for the
# same provider means it is very likely failing silently (e.g. an
# unclassified provider error) rather than doing real work.
SUSPICIOUS_TURN_MS = 3000
STALL_THRESHOLD = 3
STALL_BACKOFF_SECONDS = 60.0

# --- Bounded retry for transient/transport failures ------------------------
MAX_TRANSIENT_RETRIES = 3
MAX_TRANSPORT_RETRIES = 2
TRANSIENT_BASE_BACKOFF_SECONDS = 5.0
TRANSIENT_MAX_BACKOFF_SECONDS = 60.0

AUTONOMY_POLICY = {"granular": {
    # App Server's auto-reviewer, rather than a human, evaluates the narrow
    # fixed-wrapper sandbox escape and any proposed matching rule.
    "sandbox_approval": True, "rules": True, "skill_approval": False,
    "request_permissions": True, "mcp_elicitations": True,
}}

MARKER_INSTRUCTIONS = """End every completed turn with exactly one outcome marker:
SUPERVISOR_OUTCOME: CONTINUE
HUMAN_GATE: <reason>
SUPERVISOR_OUTCOME: COMPLETE
Also emit, each on its own line whenever known, SUPERVISOR_TASK: <task id>
and SUPERVISOR_PHASE: <short current phase>. Do not stop for routine
reporting."""

CODEX_START = f"""Read and follow AGENTS.md and Docs/AUTONOMOUS_DEVELOPMENT.md.
Work autonomously through the next incomplete task. This App Server thread is
the sole mutating agent and owns the supervisor lease itself; do not mistake
that lease for another agent. Refuse only a separately observed CotS Host lock
or independently running mutating agent. Preserve the CotS/Shardlands
boundaries, Host MCP restrictions, and production bootstrap boundary.

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

{MARKER_INSTRUCTIONS}"""

CODEX_CONTINUE_TEMPLATE = """Continue autonomous CotS development from the current repository
and checkpoint state. Reconcile actual state first.{checkpoint_facts} Continue the
active task or next incomplete task. """ + MARKER_INSTRUCTIONS

CLAUDE_START = f"""Read and follow CLAUDE.md, then AGENTS.md and
Docs/AUTONOMOUS_DEVELOPMENT.md. Work autonomously through the next incomplete
task. You are the sole mutating agent right now; the CotS supervisor holds the
single-mutating-agent lease on your behalf. Refuse only a separately observed
CotS Host lock or independently running mutating agent. Preserve the
CotS/Shardlands boundaries, Host MCP restrictions, and production bootstrap
boundary.

Your tool access is already structurally limited to workspace file edits plus
exactly two fixed shell invocations: `python Scripts/CotS-GitCompletion.py ...`
for status/diff/staged task completion/commit/push, and
`Scripts\\Build-ToolLab.cmd` for the canonical build. You cannot run arbitrary
shell commands; do not ask for one. Never write Shardlands or mutate
production CotS without an explicit task authorization.

{MARKER_INSTRUCTIONS}"""

CLAUDE_CONTINUE_TEMPLATE = """Continue autonomous CotS development from the current
repository and checkpoint state. Reconcile actual state first.{checkpoint_facts} Continue the
active task or next incomplete task. """ + MARKER_INSTRUCTIONS


def build_continue_prompt(name: str, state: dict[str, Any]) -> str:
    """Inject factual repository/checkpoint state into the continuation
    prompt (TASK-008C fix): the handoff between providers must be grounded
    in what the provider-neutral checkpoint and Tasks/*.md actually say, not
    left to the next provider's own conversational guess at what happened."""
    task = state.get("task")
    phase = state.get("phase")
    lease_owner = state.get("mutation_lease_owner")
    facts = []
    if task and task != "RECONCILING":
        facts.append(f"checkpoint task={task}")
    if phase and phase != "RECONCILING":
        facts.append(f"phase={phase}")
    if lease_owner and lease_owner not in ("none", None):
        facts.append(f"Host mutation lease owner={lease_owner}")
    checkpoint_facts = (
        f" The provider-neutral supervisor checkpoint (.cots/agent-supervisor.local.json) "
        f"and active Tasks/*.md report: {', '.join(facts)}; verify this against the actual "
        f"repository state before trusting it."
    ) if facts else ""
    template = CODEX_CONTINUE_TEMPLATE if name == "codex" else CLAUDE_CONTINUE_TEMPLATE
    return template.format(checkpoint_facts=checkpoint_facts)

CLAUDE_ALLOWED_TOOLS = (
    "Read Edit Write Grep Glob "
    "Bash(python Scripts/CotS-GitCompletion.py *) "
    "Bash(Scripts\\Build-ToolLab.cmd *)"
)

TASK_PATTERN = re.compile(r"^SUPERVISOR_TASK:\s*(.+)$", re.MULTILINE)
PHASE_PATTERN = re.compile(r"^SUPERVISOR_PHASE:\s*(.+)$", re.MULTILINE)

USAGE_LIMIT_PATTERNS = [
    re.compile(r"usage limit", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"quota exceeded", re.IGNORECASE),
    re.compile(r"usageLimitExceeded"),
    re.compile(r"\b429\b"),
    re.compile(r"\b529\b"),
]
RESET_EPOCH_PATTERN = re.compile(r"usage limit reached\|(\d+)", re.IGNORECASE)
# Real Codex 0.151.0 App Server usage-limit errors do not carry a machine
# reset timestamp; they embed a human-readable clock time in the message,
# e.g. "...or try again at 4:22 AM." captured verbatim in
# .cots/codex-protocol.log. Best-effort-parse it as a fallback.
TRY_AGAIN_AT_PATTERN = re.compile(r"try again at (\d{1,2}):(\d{2})\s*([AaPp][Mm])")

# Host MCP mutation-lease owners are named "<agent>-task-<number>"
# (observed live: "codex-task-012"). Used only as a reconciliation fallback
# when no SUPERVISOR_TASK marker has been parsed from an agent turn yet.
LEASE_TASK_PATTERN = re.compile(r"-task-(\d+)$", re.IGNORECASE)

ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_PATTERN.sub("", text)


def summarize_event(text: str, limit: int = 300) -> str:
    """Collapse a possibly multi-line/ANSI-laden event into one safe console line.

    The full, untruncated text still goes to ``.cots/supervisor-events.log``
    via ``log_event``; only the in-memory/on-screen copy is sanitized so a
    verbose subprocess-stderr dump (e.g. an App Server crash trace) can never
    corrupt the redrawn-in-place dashboard frame.
    """
    collapsed = " ".join(strip_ansi(text).split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return collapsed


def extract_reset_from_message(message: str) -> float | None:
    epoch_match = RESET_EPOCH_PATTERN.search(message)
    if epoch_match:
        return float(epoch_match.group(1))
    clock_match = TRY_AGAIN_AT_PATTERN.search(message)
    if not clock_match:
        return None
    hour, minute, meridiem = int(clock_match.group(1)), int(clock_match.group(2)), clock_match.group(3).upper()
    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0
    now = time.localtime()
    candidate = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, 0, 0, -1))
    if candidate <= time.time():
        candidate += 24 * 60 * 60  # the reset clock time has already passed today
    return candidate


def is_codex_usage_limit_error(error: dict[str, Any] | None) -> bool:
    """Match every real usage-exhaustion shape seen in the installed Codex
    0.151.0 App Server protocol (.cots/codex-protocol.log): a standalone
    ``error`` notification or a ``turn/completed`` with ``status: "failed"``,
    both carrying ``codexErrorInfo: "usageLimitExceeded"``."""
    if not error:
        return False
    if error.get("codexErrorInfo") == "usageLimitExceeded":
        return True
    message = str(error.get("message", ""))
    return any(pattern.search(message) for pattern in USAGE_LIMIT_PATTERNS)


def is_capacity_exhausted_rate_limits(rate_limits: dict[str, Any]) -> bool:
    """``account/rateLimits/updated`` capacity signal.

    In the captured protocol ``rateLimitReachedType`` was always ``null``
    even while every turn was failing on usage; the only rate-limit-side
    corroborating signal present was ``credits: {hasCredits: false,
    unlimited: false}``. This is intentionally used only to annotate the
    dashboard/checkpoint (see ``last_known_rate_limits``), never as the sole
    trigger to abort a turn -- an account without a purchased credit balance
    is not necessarily mid-turn-exhausted, so the authoritative signal stays
    the explicit turn/error failure above.
    """
    if rate_limits.get("rateLimitReachedType"):
        return True
    credits = rate_limits.get("credits") or {}
    return credits.get("hasCredits") is False and credits.get("unlimited") is False


class TurnFailed(RuntimeError):
    """A turn completed with a provider-reported failure that is not a usage
    limit. ``transient`` distinguishes a known-recoverable transport/provider
    hiccup (bounded retry) from an unknown/system failure (terminal FAILED)."""

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient




class TurnResult:
    """Provider-neutral outcome of one completed turn."""

    __slots__ = ("text", "duration_ms", "activity_count")

    def __init__(self, text: str, duration_ms: float | None, activity_count: int) -> None:
        self.text = text
        self.duration_ms = duration_ms
        self.activity_count = activity_count

    def is_suspicious(self) -> bool:
        """No meaningful assistant text, no recorded tool/item activity, and
        it finished almost instantly -- the shape of a silent failed-fast
        turn rather than real work."""
        return (
            not self.text.strip()
            and self.activity_count == 0
            and self.duration_ms is not None
            and self.duration_ms < SUSPICIOUS_TURN_MS
        )


# --------------------------------------------------------------------------
# Persistence and logging
# --------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"state": "STARTING", "turn_count": 0}


def save_state(value: dict[str, Any]) -> None:
    STATE.parent.mkdir(exist_ok=True)
    temporary = STATE.with_suffix(STATE.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE)


def log_event(text: str) -> None:
    EVENTS_LOG.parent.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with EVENTS_LOG.open("a", encoding="utf-8") as log:
        log.write(f"[{stamp}] {text}\n")


class StatusBus:
    """Thread-safe dashboard state: one writer set, one renderer reader."""

    def __init__(self, initial: dict[str, Any]) -> None:
        self.lock = threading.RLock()
        self.data = initial
        self.recent_events: list[str] = list(initial.get("recent_events", []))[-MAX_RECENT_EVENTS:]

    # Fields that are only meaningful while the checkpoint is in a specific
    # state; leaving that state clears them so a stale value (e.g. an old
    # human_gate reason surviving into a later CONTINUING/RUNNING state)
    # never misleads a later reader of the checkpoint or dashboard.
    STATE_SCOPED_FIELDS = {"HUMAN_GATE": ("human_gate",), "FAILED": ("failure",)}

    def update(self, event: str | None = None, **fields: Any) -> None:
        with self.lock:
            self.data.update(fields)
            self.data["updated_at"] = time.time()
            new_state = fields.get("state")
            if new_state:
                for owning_state, scoped_fields in self.STATE_SCOPED_FIELDS.items():
                    if new_state == owning_state:
                        continue
                    for field in scoped_fields:
                        if field not in fields and self.data.get(field) is not None:
                            self.data[field] = None
            if event:
                stamp = time.strftime("%H:%M:%S")
                self.recent_events.append(f"[{stamp}] {summarize_event(event)}")
                self.recent_events = self.recent_events[-MAX_RECENT_EVENTS:]
                log_event(event)
            self.data["recent_events"] = list(self.recent_events)
            save_state(self.data)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.data)


# --------------------------------------------------------------------------
# Supervisor instance lease (unchanged from TASK-008B)
# --------------------------------------------------------------------------

class AppServerError(RuntimeError):
    pass


class UsageResetRequired(AppServerError):
    """The provider reported a usage/rate limit that requires a later resume."""

    status_label = "USAGE_EXHAUSTED"

    def __init__(self, reason: str, reset_at: float | None = None) -> None:
        super().__init__(reason)
        self.reset_at = reset_at


class ProviderStalled(UsageResetRequired):
    """Circuit breaker trip: several consecutive no-op/suspicious turns from
    the same provider (TASK-008C hot-loop protection). Handled exactly like a
    usage exhaustion for rotation purposes, but with a short fixed backoff
    instead of a provider-reported reset time, and a distinct dashboard
    status so it is never confused with real provider exhaustion.
    """

    status_label = "STALLED_PROVIDER"

    def __init__(self, reason: str) -> None:
        super().__init__(reason, time.time() + STALL_BACKOFF_SECONDS)


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


# --------------------------------------------------------------------------
# Codex adapter (Codex App Server, unchanged protocol handling from 008B)
# --------------------------------------------------------------------------

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
        self.usage_reset_at: float | None = None
        self.last_error: dict[str, Any] | None = None
        self.last_rate_limits: dict[str, Any] | None = None
        self.capacity_exhausted_hint = False
        self.lock = threading.Condition()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    @staticmethod
    def _trace(prefix: str, value: Any) -> None:
        CODEX_PROTOCOL_LOG.parent.mkdir(exist_ok=True)
        with CODEX_PROTOCOL_LOG.open("a", encoding="utf-8") as log:
            log.write(prefix + json.dumps(value, separators=(",", ":")) + "\n")

    def _mark_usage_exhausted(self, error: dict[str, Any]) -> None:
        if not self.usage_reset_reason:
            self.usage_reset_reason = str(error.get("codexErrorInfo") or error.get("message") or "usage_limit")
        reset_at = extract_reset_from_message(str(error.get("message", "")))
        if reset_at is not None:
            self.usage_reset_at = reset_at

    # Notifications with no request id: nothing in this supervisor correlates
    # them, so they are handled for side effects only and never queued --
    # hundreds of turns previously left thousands of unmatched notifications
    # sitting in ``messages`` for the lifetime of the App Server process.
    _DISCARDED_NOTIFICATION_METHODS = frozenset({
        "thread/status/changed", "thread/started", "item/started", "item/completed",
        "mcpServer/startupStatus/updated", "remoteControl/status/changed",
    })

    def _handle_message(self, message: dict[str, Any]) -> None:
        """Apply one decoded App Server message's side effects and decide
        whether it should be queued for ``request``/``wait_turn`` to consume.
        Split out from ``_read_stdout`` so the real protocol classification
        logic can be unit-tested directly against captured JSONL fixtures
        without spawning a real ``codex app-server`` subprocess."""
        method = message.get("method")
        with self.lock:
            if method == "account/rateLimits/updated":
                # Kept for forward compatibility (a real, structured
                # exhaustion signal on some accounts/plans) and for
                # dashboard/checkpoint annotation, but never the sole
                # trigger -- see is_capacity_exhausted_rate_limits().
                limits = message.get("params", {}).get("rateLimits", {})
                self.last_rate_limits = limits
                self.capacity_exhausted_hint = is_capacity_exhausted_rate_limits(limits)
                reached = limits.get("rateLimitReachedType")
                if reached:
                    self.usage_reset_reason = str(reached)
                    epoch = extract_reset_epoch(limits)
                    if epoch is not None:
                        self.usage_reset_at = epoch
                self.lock.notify_all()
                return
            if method == "error":
                # The real, authoritative usage-exhaustion signal in the
                # installed Codex 0.151.0 App Server protocol: a standalone
                # notification with codexErrorInfo == "usageLimitExceeded"
                # and willRetry: false, emitted just before the matching
                # turn/completed (see .cots/codex-protocol.log). It carries
                # no request id, so it is processed here and discarded.
                error = message.get("params", {}).get("error") or {}
                self.last_error = error
                if is_codex_usage_limit_error(error):
                    self._mark_usage_exhausted(error)
                self.lock.notify_all()
                return
            if method in self._DISCARDED_NOTIFICATION_METHODS:
                self.lock.notify_all()
                return
            if method == "turn/completed":
                # Defense in depth: classify directly from the turn's own
                # ``error`` field too, in case a future/older App Server
                # build omits the separate ``error`` notification.
                turn = message.get("params", {}).get("turn", {})
                if turn.get("status") == "failed":
                    error = turn.get("error") or self.last_error or {}
                    if is_codex_usage_limit_error(error):
                        self._mark_usage_exhausted(error)
            self.messages.append(message)
            self.lock.notify_all()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._trace("< ", message)
            self._handle_message(message)

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
                    raise UsageResetRequired(self.usage_reset_reason, self.usage_reset_at)
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
                if self.usage_reset_reason:
                    raise UsageResetRequired(self.usage_reset_reason, self.usage_reset_at)
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


def extract_reset_epoch(limits: dict[str, Any]) -> float | None:
    for key in ("resetsAtEpochSeconds", "resetAtEpochSeconds", "resetsAt", "resetAt"):
        value = limits.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("resetsInSeconds", "secondsUntilReset"):
        value = limits.get(key)
        if isinstance(value, (int, float)):
            return time.time() + float(value)
    return None


def text_from(turn: dict[str, Any]) -> str:
    return "\n".join(
        str(item.get("text", item.get("content", "")))
        for item in turn.get("items", [])
        if isinstance(item, dict) and item.get("type") in {"agentMessage", "message"}
    )


def turn_outcome(text: str) -> tuple[str, str]:
    if "HUMAN_GATE:" in text:
        return "HUMAN_GATE", text.split("HUMAN_GATE:", 1)[1].strip().splitlines()[0]
    if "SUPERVISOR_OUTCOME: COMPLETE" in text:
        return "COMPLETE", ""
    return "CONTINUING", ""


def parse_task_phase(text: str) -> tuple[str | None, str | None]:
    task_match = TASK_PATTERN.search(text)
    phase_match = PHASE_PATTERN.search(text)
    return (
        task_match.group(1).strip() if task_match else None,
        phase_match.group(1).strip() if phase_match else None,
    )


def codex_app_settings(developer_instructions: str) -> dict[str, Any]:
    return {
        "cwd": str(REPO), "developerInstructions": developer_instructions,
        "approvalPolicy": AUTONOMY_POLICY, "approvalsReviewer": "auto_review",
        "sandbox": "workspace-write",
    }


def user_text(text: str) -> list[dict[str, Any]]:
    # Codex App Server v2 requires text_elements, even when it is empty.
    return [{"type": "text", "text": text, "text_elements": []}]


class CodexAgent:
    """Owns at most one live Codex App Server process at a time."""

    name = "codex"

    def __init__(self) -> None:
        self.app: AppServer | None = None
        self.thread_id: str | None = None

    @staticmethod
    def available() -> bool:
        return shutil.which("codex") is not None

    @staticmethod
    def version() -> str | None:
        try:
            return subprocess.check_output(["codex", "--version"], text=True, timeout=15).strip()
        except Exception:
            return None

    def activate(self, thread_id: str | None) -> bool:
        """Start the App Server and resume/start its thread. Returns resumed."""
        self.app = AppServer()
        self.app.request("initialize", {
            "clientInfo": {"name": "CotS Persistent Supervisor", "version": "1.2"},
            "capabilities": {"experimentalApi": True},
        })
        resumed = False
        if thread_id:
            try:
                self.app.request("thread/resume", {"threadId": thread_id, **codex_app_settings(CODEX_START)})
                resumed = True
            except (AppServerError, TimeoutError):
                thread_id = None
        if not thread_id:
            started = self.app.request("thread/start", codex_app_settings(CODEX_START))
            thread_id = started["thread"]["id"]
        self.thread_id = thread_id
        return resumed

    def run_turn(self, prompt: str) -> TurnResult:
        assert self.app is not None and self.thread_id is not None
        self.app.request("turn/start", {"threadId": self.thread_id, "input": user_text(prompt)}, timeout=60)
        turn = self.app.wait_turn(self.thread_id)
        if turn.get("status") == "failed":
            error = turn.get("error") or self.app.last_error or {}
            if is_codex_usage_limit_error(error):
                raise UsageResetRequired(
                    str(error.get("codexErrorInfo") or "usageLimitExceeded"),
                    extract_reset_from_message(str(error.get("message", ""))),
                )
            # No other failed-turn shape has been observed in the captured
            # protocol; treat an unrecognized failure as unknown/system
            # rather than silently continuing (the TASK-008C hot-loop bug).
            raise TurnFailed(str(error.get("message") or "codex turn failed"), transient=False)
        return TurnResult(text_from(turn), turn.get("durationMs"), len(turn.get("items") or []))

    def deactivate(self) -> None:
        if self.app is not None:
            self.app.close()
            self.app = None


# --------------------------------------------------------------------------
# Claude adapter: one ``claude -p`` invocation per turn, resumed by session id
# --------------------------------------------------------------------------

def log_claude_protocol(args: list[str], completed: subprocess.CompletedProcess[str]) -> None:
    CLAUDE_PROTOCOL_LOG.parent.mkdir(exist_ok=True)
    with CLAUDE_PROTOCOL_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps({
            "ts": time.time(), "args": args, "returncode": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr,
        }, separators=(",", ":")) + "\n")


def try_parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # ``-p`` normally prints exactly one JSON object; fall back to the last
    # line in case anything else leaked onto stdout.
    for line in reversed(text.splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def detect_usage_limit(combined_text: str, payload: dict[str, Any] | None) -> tuple[bool, float | None]:
    """Claude Code ``-p --output-format json`` usage-limit classification.

    ``api_error_status`` and ``is_error``/``subtype`` are real fields
    confirmed live against the installed Claude Code 2.1.251 CLI (see
    .cots/claude-protocol.log and Scripts/tests/fixtures/claude_success.json
    for the captured shape: {"is_error": false, "api_error_status": null,
    "subtype": "success", "result": "...", ...}). A 429/529
    ``api_error_status`` is the authoritative machine-readable usage-limit
    signal; the text patterns are a fallback for a limit message that only
    reaches stdout/stderr as prose.
    """
    api_status = payload.get("api_error_status") if isinstance(payload, dict) else None
    matched = api_status in (429, 529) or any(pattern.search(combined_text) for pattern in USAGE_LIMIT_PATTERNS)
    if not matched:
        return False, None
    return True, extract_reset_from_message(combined_text)


class ClaudeAgent:
    """Runs Claude Code non-interactively, one process per turn."""

    name = "claude"

    def __init__(self) -> None:
        self.session_id: str | None = None

    @staticmethod
    def available() -> bool:
        return shutil.which("claude") is not None

    @staticmethod
    def version() -> str | None:
        try:
            return subprocess.check_output(["claude", "--version"], text=True, timeout=15).strip()
        except Exception:
            return None

    def activate(self, session_id: str | None) -> bool:
        self.session_id = session_id
        return session_id is not None

    # subtypes confirmed by Anthropic's Claude Code CLI docs/-p output shape
    # that indicate a recoverable transport/provider hiccup rather than an
    # unknown application failure worth a terminal FAILED state.
    TRANSIENT_SUBTYPES = {"error_during_execution", "error_network", "error_timeout"}

    def run_turn(self, prompt: str) -> TurnResult:
        args = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
            "--allowedTools", CLAUDE_ALLOWED_TOOLS,
        ]
        if self.session_id:
            args += ["--resume", self.session_id]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args, cwd=REPO, capture_output=True, text=True,
                timeout=TURN_TIMEOUT_SECONDS, encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired as error:
            raise AppServerError(f"claude_turn_timeout: {error}") from error
        duration_ms = (time.monotonic() - started) * 1000
        log_claude_protocol(args, completed)
        payload = try_parse_json(completed.stdout)
        combined = f"{completed.stdout}\n{completed.stderr}"
        is_limited, reset_at = detect_usage_limit(combined, payload)
        if is_limited:
            raise UsageResetRequired("claude_usage_limit", reset_at)
        if payload is None:
            raise AppServerError(f"claude_no_json_result exit={completed.returncode}: {combined[-2000:]}")
        self.session_id = payload.get("session_id") or self.session_id
        if payload.get("is_error"):
            subtype = payload.get("subtype")
            transient = subtype in self.TRANSIENT_SUBTYPES
            raise TurnFailed(f"claude_error subtype={subtype}: {str(payload.get('result', ''))[:2000]}", transient=transient)
        activity_count = int(payload.get("num_turns") or 0)
        return TurnResult(str(payload.get("result", "")), duration_ms, activity_count)

    def deactivate(self) -> None:
        pass  # nothing to close: each turn is already a completed subprocess


AGENT_CLASSES = {"codex": CodexAgent, "claude": ClaudeAgent}
START_PROMPTS = {"codex": CODEX_START, "claude": CLAUDE_START}


# --------------------------------------------------------------------------
# Best-effort external probes (Git, ToolLab / Host MCP) for the dashboard
# --------------------------------------------------------------------------

# Repository-relative paths TASK-008C/the supervisor itself owns. Everything
# else that shows up dirty is pre-existing work (UnrealPlugin/ToolLab/Content
# in-progress changes) that must never be staged, reverted, or committed by
# this task -- see AGENTS.md's one-mutating-agent/no-destructive-git rules.
SUPERVISOR_OWNED_PREFIXES = (
    "Scripts/CotSAgentSupervisor.py",
    "Scripts/Launch-CotS-Agents.bat",
    "Scripts/tests/",
    "Docs/AUTONOMOUS_DEVELOPMENT.md",
    "Docs/AGENT_COMPATIBILITY.md",
    "Tasks/008B_PERSISTENT_AGENT_SUPERVISOR.md",
    "Tasks/008C_SUPERVISOR_DASHBOARD.md",
)


def classify_git_status(status_lines: list[str]) -> dict[str, int]:
    supervisor = protected = untracked_other = 0
    for line in status_lines:
        code, path = line[:2], line[3:].strip()
        if code == "??":
            if path.startswith(SUPERVISOR_OWNED_PREFIXES):
                supervisor += 1
            else:
                untracked_other += 1
        elif path.startswith(SUPERVISOR_OWNED_PREFIXES):
            supervisor += 1
        else:
            protected += 1
    return {"supervisor": supervisor, "protected": protected, "untracked_other": untracked_other}


def probe_git(bus: StatusBus) -> None:
    try:
        def run(*args: str) -> str:
            completed = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=5)
            return completed.stdout.strip()

        branch = run("rev-parse", "--abbrev-ref", "HEAD") or "?"
        status_lines = [line for line in run("status", "--porcelain").splitlines() if line.strip()]
        last_commit = run("log", "-1", "--format=%h %s") or "(no commits)"
        counts = classify_git_status(status_lines)
        if not status_lines:
            summary = "clean"
        else:
            summary = (
                f"{len(status_lines)} changed (task008c={counts['supervisor']} "
                f"pre-existing-protected={counts['protected']} "
                f"untracked-other={counts['untracked_other']})"
            )
        bus.update(
            git_branch=branch,
            git_status=summary,
            git_status_counts=counts,
            last_commit=last_commit,
        )
    except Exception as error:
        bus.update(git_branch="?", git_status=f"probe_error: {error}", last_commit="?")


def mcp_call(connection: Any, request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    connection.request("POST", "/mcp", body=body, headers={"Content-Type": "application/json"})
    response = connection.getresponse()
    payload = json.loads(response.read().decode("utf-8"))
    return payload


def task_from_lease_owner(owner: str | None) -> str | None:
    """Best-effort TASK-<N> reconciliation from a Host mutation-lease owner
    name (observed live: "codex-task-012" -> "TASK-012"). Used only when no
    SUPERVISOR_TASK marker has been parsed directly from an agent turn yet --
    that marker is stronger evidence than this naming-convention fallback."""
    if not owner:
        return None
    match = LEASE_TASK_PATTERN.search(owner)
    return f"TASK-{match.group(1)}" if match else None


def reconcile_task_phase(bus: StatusBus, mutation_lease_owner: str | None) -> None:
    """Fill in task/phase from the strongest available evidence rather than
    ever leaving the dashboard's "(unknown)" default indefinitely (TASK-008C
    fix): a SUPERVISOR_TASK/SUPERVISOR_PHASE marker already parsed from a
    turn is strongest and is left untouched; otherwise fall back to the Host
    mutation-lease owner's naming convention; otherwise mark explicitly
    RECONCILING rather than inventing a value."""
    updates: dict[str, Any] = {}
    if not bus.data.get("task"):
        from_lease = task_from_lease_owner(mutation_lease_owner)
        updates["task"] = from_lease or "RECONCILING"
    if not bus.data.get("phase"):
        updates["phase"] = "RECONCILING"
    if updates:
        bus.update(**updates)


def probe_host_mcp(bus: StatusBus) -> None:
    try:
        connection = http.client.HTTPConnection(HOST_MCP_HOST, HOST_MCP_PORT, timeout=1.5)
        try:
            mcp_call(connection, 1, "initialize", {
                "protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "CotS Supervisor Dashboard", "version": "1.0"},
            })
            status_payload = mcp_call(connection, 2, "tools/call", {"name": "GetToolLabStatus", "arguments": {}})
            data = json.loads(status_payload["result"]["content"][0]["text"])
        finally:
            connection.close()
        lease_owner = data.get("mutation_lock_owner") or "none"
        bus.update(
            host_mcp_state="READY",
            toollab_state="OPEN" if data.get("editor_running") else "CLOSED",
            unreal_mcp_state="READY" if data.get("mcp_ready") else "NOT_READY",
            mutation_lease_owner=lease_owner,
        )
        reconcile_task_phase(bus, lease_owner)
    except OSError:
        bus.update(host_mcp_state="NOT_RUNNING", toollab_state="UNKNOWN", unreal_mcp_state="UNKNOWN")
        reconcile_task_phase(bus, bus.data.get("mutation_lease_owner"))
    except Exception as error:
        bus.update(host_mcp_state=f"error: {error}", toollab_state="UNKNOWN", unreal_mcp_state="UNKNOWN")
        reconcile_task_phase(bus, bus.data.get("mutation_lease_owner"))


# --------------------------------------------------------------------------
# Dashboard rendering
# --------------------------------------------------------------------------

def enable_windows_ansi() -> None:
    if sys.platform != "win32":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def format_reset(reset_at: float | None) -> str:
    if not reset_at:
        return "unknown"
    remaining = reset_at - time.time()
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reset_at))
    if remaining <= 0:
        return f"{when} (due now)"
    hours, minutes = divmod(int(remaining // 60), 60)
    return f"{when} (in {hours}h{minutes:02d}m)"


DEFAULT_FRAME_WIDTH = 78
MAX_LINE_LENGTH = 240  # generous hard cap so one runaway field cannot desync line count


def render_frame_lines(snapshot: dict[str, Any]) -> list[str]:
    """Build every dashboard line as a plain, single-line string. Returning a
    flat list (never an embedded "\\n") keeps the per-frame line count
    predictable so the renderer can erase each row exactly."""
    width = DEFAULT_FRAME_WIDTH
    rule = "=" * width
    thin = "-" * width

    def agent_lines(key: str) -> list[str]:
        info = snapshot.get(key, {})
        status = info.get("status", "UNKNOWN")
        version = info.get("version") or "?"
        result = [f" {key.upper():<7} status={status:<18} version={version}"]
        reset_at = info.get("reset_at")
        if status in ("USAGE_EXHAUSTED", "STALLED_PROVIDER") or reset_at:
            result.append(f"         reset={format_reset(reset_at)}")
        return result

    state = snapshot.get("state", "STARTING")
    active_agent = snapshot.get("active_agent")
    if active_agent:
        active_label = str(active_agent).upper()
    elif state == "ROTATING_AGENT":
        active_label = "(transitioning)"
    else:
        active_label = "(none)"

    lines = [
        rule,
        f" COTS AUTONOMOUS SUPERVISOR{'':>10}state={state:<24}turn={snapshot.get('turn_count', 0)}",
        rule,
        f" Active Agent:  {active_label:<15} Preferred: {str(snapshot.get('preferred_agent', 'codex')).upper()}",
        f" Task:          {snapshot.get('task') or 'RECONCILING':<30} Phase: {snapshot.get('phase') or 'RECONCILING'}",
        f" Current Action: {snapshot.get('current_action') or ''}",
        f" Rotations:     {snapshot.get('rotation_count', 0)}",
        thin,
        *agent_lines("codex"),
        *agent_lines("claude"),
        thin,
        f" ToolLab: {snapshot.get('toollab_state', 'UNKNOWN'):<10} Unreal MCP: {snapshot.get('unreal_mcp_state', 'UNKNOWN'):<10} Host MCP: {snapshot.get('host_mcp_state', 'UNKNOWN')}",
        f" Mutation Lease Owner: {snapshot.get('mutation_lease_owner', 'unknown')}",
        thin,
        f" Git Branch: {snapshot.get('git_branch', '?'):<12} Status: {snapshot.get('git_status', '?')}",
        f" Last Commit: {snapshot.get('last_commit', '?')}",
        f" Last Successful Gate: {snapshot.get('last_successful_gate', '(none yet)')}",
        thin,
        " Recent Events:",
    ]
    events = snapshot.get("recent_events", []) or ["(none yet)"]
    lines.extend(f"   {event}" for event in events[-MAX_RECENT_EVENTS:])
    lines.append(rule)
    lines.append(" You may minimize this window. Closing it stops autonomous development.")
    lines.append(" Ctrl+C = safe shutdown (finishes current turn, saves checkpoint, exits).")
    lines.append(rule)
    # Belt-and-suspenders: strip any stray ANSI/control characters and hard-cap
    # length so a value the supervisor did not fully control (an agent-emitted
    # SUPERVISOR_TASK/PHASE marker, a raw subprocess error string) can never
    # move the cursor itself or blow out a row's rendered width.
    return [strip_ansi(line).replace("\r", "")[:MAX_LINE_LENGTH] for line in lines]


def render_frame(snapshot: dict[str, Any]) -> str:
    return "\n".join(render_frame_lines(snapshot))


# One synchronized render operation, one writer thread: build the full frame
# in memory first (render_frame_lines), then emit it in a single write.
# Every line is followed by "erase to end of line" (\x1b[K) before its
# newline, so a row that is shorter than what a previous, longer-content
# frame left behind is fully overwritten rather than showing trailing
# fragments -- this, not the previous single trailing \x1b[0J alone, was the
# actual cause of the observed overlapping/mixed frames, since \x1b[0J only
# clears from the final cursor position onward, never mid-line remnants on
# earlier rows. \x1b[0J is kept at the end to drop any extra trailing lines
# left over from a previous, taller frame (e.g. one more agent reset line).
def _frame_payload(lines: list[str]) -> str:
    return "\x1b[H" + "\x1b[K\n".join(lines) + "\x1b[K\x1b[0J\n"


def dashboard_loop(bus: StatusBus, stop_event: threading.Event) -> None:
    enable_windows_ansi()
    sys.stdout.write("\x1b[2J\x1b[H")
    sys.stdout.flush()
    last_probe = 0.0
    while True:
        now = time.monotonic()
        if now - last_probe >= EXTERNAL_PROBE_SECONDS:
            probe_git(bus)
            probe_host_mcp(bus)
            last_probe = now
        sys.stdout.write(_frame_payload(render_frame_lines(bus.snapshot())))
        sys.stdout.flush()
        if stop_event.wait(DASHBOARD_REFRESH_SECONDS):
            break
    # Final frame so the last state remains visible after the loop exits.
    sys.stdout.write(_frame_payload(render_frame_lines(bus.snapshot())))
    sys.stdout.flush()


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def is_agent_usable(info: dict[str, Any], configured: bool) -> bool:
    """A provider is usable if it is configured/installed and either not in a
    reset-gated status, or its recorded reset time has passed."""
    if not configured:
        return False
    if info.get("status") not in ("USAGE_EXHAUSTED", "STALLED_PROVIDER"):
        return True
    reset_at = info.get("reset_at")
    return reset_at is not None and time.time() >= reset_at


def pick_ready_agent(checkpoint: dict[str, Any], configured: set[str], agent_order: list[str], current: str) -> str | None:
    """Best usable agent: prefer rotating to another configured provider over
    resuming ``current``, so Codex exhaustion always hands off to Claude (or
    vice versa) rather than idling on the same provider when a second one is
    configured and ready."""
    other = next(
        (name for name in agent_order if name != current and is_agent_usable(checkpoint.get(name, {}), name in configured)),
        None,
    )
    if other is not None:
        return other
    return current if is_agent_usable(checkpoint.get(current, {}), current in configured) else None


def record_turn_and_check_stall(stall_streak: dict[str, int], name: str, result: TurnResult) -> bool:
    """Hot-loop circuit breaker bookkeeping. Returns True once ``name`` has
    produced ``STALL_THRESHOLD`` consecutive suspicious (no text, no
    activity, near-instant) turns in a row; any real turn resets the count."""
    if result.is_suspicious():
        stall_streak[name] = stall_streak.get(name, 0) + 1
    else:
        stall_streak[name] = 0
    return stall_streak[name] >= STALL_THRESHOLD


class Shutdown(Exception):
    pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="Update Codex before starting a session.")
    parser.add_argument("--prompt", help="Initial bounded test prompt.")
    parser.add_argument("--max-turns", type=int, help="Stop after this many completed turns (test only).")
    parser.add_argument("--fresh", action="store_true", help="Discard only the local supervisor checkpoint before a disposable proof.")
    parser.add_argument("--agents", default="codex,claude", help="Comma-separated agent pool, in preference order.")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip the console dashboard thread (for headless/test runs).")
    parser.add_argument("--simulate-codex-usage-limit-after", type=int, help="Test hook: force a Codex usage-limit after N of its turns.")
    parser.add_argument("--simulate-claude-usage-limit-after", type=int, help="Test hook: force a Claude usage-limit after N of its turns.")
    args = parser.parse_args()

    agent_order = [name.strip() for name in args.agents.split(",") if name.strip()]
    agent_order = [name for name in agent_order if name in AGENT_CLASSES] or ["codex"]

    try:
        lease = SupervisorLease()
    except AppServerError as error:
        print(str(error), file=sys.stderr)
        return 2

    shutdown_event = threading.Event()

    def handle_sigint(_signum: int, _frame: Any) -> None:
        if shutdown_event.is_set():
            print("\nForced exit.", file=sys.stderr)
            os._exit(130)
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        if args.fresh and STATE.exists():
            STATE.unlink()
        state = load_state()
        state.setdefault("preferred_agent", agent_order[0])
        state.setdefault("turn_count", 0)
        state.setdefault("rotation_count", 0)
        state.setdefault("codex", {"status": "UNKNOWN"})
        state.setdefault("claude", {"status": "UNKNOWN"})
        bus = StatusBus(state)
        bus.update(state="PREFLIGHT", current_action="Checking installed agent versions", event="Supervisor startup")

        if args.update and "codex" in agent_order:
            bus.update(current_action="Updating Codex", event="Running codex update")
            try:
                subprocess.run(["codex", "update"], cwd=REPO, timeout=UPDATE_TIMEOUT_SECONDS, check=False)
            except subprocess.TimeoutExpired:
                bus.update(state="FAILED", event="codex update timed out")
                return 2

        instances: dict[str, Any] = {}
        for name in agent_order:
            cls = AGENT_CLASSES[name]
            if not cls.available():
                bus.update(**{name: {**bus.data.get(name, {}), "status": "NOT_INSTALLED"}})
                continue
            version = cls.version()
            instances[name] = cls()
            bus.update(**{name: {**bus.data.get(name, {}), "status": "IDLE", "version": version}})
        if not instances:
            bus.update(state="FAILED", event="No configured agent CLI is installed")
            return 2

        dashboard_thread = None
        if not args.no_dashboard:
            dashboard_thread = threading.Thread(target=dashboard_loop, args=(bus, shutdown_event), daemon=True)
            dashboard_thread.start()

        preferred = state["preferred_agent"] if state["preferred_agent"] in instances else next(iter(instances))
        active_name = state.get("active_agent") if state.get("active_agent") in instances else preferred
        simulate_after = {
            "codex": args.simulate_codex_usage_limit_after,
            "claude": args.simulate_claude_usage_limit_after,
        }
        turns_run = {"codex": 0, "claude": 0}
        stall_streak = {"codex": 0, "claude": 0}

        try:
            while True:
                if shutdown_event.is_set():
                    raise Shutdown()

                agent = instances[active_name]
                session_ref_key = "thread_id" if active_name == "codex" else "session_id"
                session_ref = state.get(active_name, {}).get(session_ref_key)
                bus.update(
                    state=f"RUNNING_{active_name.upper()}",
                    active_agent=active_name,
                    preferred_agent=preferred,
                    current_action=f"Starting/resuming {active_name}",
                    **{active_name: {**bus.data.get(active_name, {}), "status": "ACTIVE", "reset_at": None, "last_error": None}},
                )
                resumed = agent.activate(session_ref)
                bus.update(event=f"{active_name.capitalize()} ready")

                prompt = args.prompt or (
                    build_continue_prompt(active_name, bus.data) if resumed and state.get("turn_count") else START_PROMPTS[active_name]
                )
                resume_retry_available = resumed and active_name == "claude"
                transient_retries = 0
                transport_retries = 0
                stall_streak[active_name] = 0

                try:
                    while True:
                        if shutdown_event.is_set():
                            raise Shutdown()
                        bus.update(current_action=f"Waiting for {active_name} turn to complete")
                        turns_run[active_name] += 1
                        if simulate_after.get(active_name) and turns_run[active_name] == simulate_after[active_name] + 1:
                            raise UsageResetRequired(f"simulated_{active_name}_usage_limit", time.time() + 60)
                        try:
                            result = agent.run_turn(prompt)
                        except UsageResetRequired:
                            raise
                        except (TurnFailed, AppServerError) as failure:
                            if resume_retry_available:
                                # Claude has no separate resume-validation step; a stale
                                # session id only surfaces as a failed turn. Retry once
                                # as a fresh session before treating it as a real failure.
                                resume_retry_available = False
                                bus.update(event="Claude resume failed, starting a fresh session")
                                agent.session_id = None
                                prompt = START_PROMPTS[active_name]
                                continue
                            transient = isinstance(failure, TurnFailed) and failure.transient
                            if isinstance(failure, TurnFailed) and not transient:
                                # Unknown/system failure: never silently CONTINUING.
                                bus.update(state="FAILED", event=f"{active_name.capitalize()} turn failed: {failure}")
                                return 1
                            retries = transient_retries if isinstance(failure, TurnFailed) else transport_retries
                            limit = MAX_TRANSIENT_RETRIES if isinstance(failure, TurnFailed) else MAX_TRANSPORT_RETRIES
                            if retries >= limit:
                                bus.update(state="FAILED", event=f"{active_name.capitalize()} exhausted retries after: {failure}")
                                return 1
                            retries += 1
                            if isinstance(failure, TurnFailed):
                                transient_retries = retries
                            else:
                                transport_retries = retries
                                # A transport-level failure (e.g. the App Server
                                # process itself exited) needs the process
                                # restarted, not just a retried request.
                                agent.deactivate()
                            backoff = min(TRANSIENT_BASE_BACKOFF_SECONDS * (2 ** (retries - 1)), TRANSIENT_MAX_BACKOFF_SECONDS)
                            bus.update(event=f"{active_name.capitalize()} transient failure ({failure}); retry {retries}/{limit} in {backoff:.0f}s")
                            if shutdown_event.wait(backoff):
                                raise Shutdown()
                            if not isinstance(failure, TurnFailed):
                                agent.activate(session_ref)
                            continue
                        resume_retry_available = False
                        transient_retries = 0
                        transport_retries = 0
                        kind, detail = turn_outcome(result.text)
                        task, phase = parse_task_phase(result.text)
                        new_ref = getattr(agent, session_ref_key, None)
                        state["turn_count"] = state.get("turn_count", 0) + 1
                        state[active_name] = {**state.get(active_name, {}), session_ref_key: new_ref}
                        bus.update(
                            turn_count=state["turn_count"],
                            task=task or bus.data.get("task"),
                            phase=phase or bus.data.get("phase"),
                            last_output=result.text[-8000:],
                            last_successful_gate=f"{time.strftime('%Y-%m-%d %H:%M:%S')} {active_name} turn completed ({kind})",
                            event=f"{active_name.capitalize()} turn completed ({kind})",
                        )
                        if kind == "HUMAN_GATE":
                            bus.update(state="HUMAN_GATE", human_gate=detail, current_action="Waiting for human", event=f"HUMAN_GATE: {detail}")
                            return 0
                        if kind == "COMPLETE" or (args.max_turns and state["turn_count"] >= args.max_turns):
                            bus.update(state="COMPLETE", current_action="Roadmap complete", event="Roadmap complete")
                            return 0
                        # Hot-loop circuit breaker: a real turn that did meaningful
                        # work (assistant text and/or recorded tool/item activity)
                        # resets the streak; several consecutive no-op turns in a
                        # row trips it rather than burning turns/quota forever.
                        if record_turn_and_check_stall(stall_streak, active_name, result):
                            raise ProviderStalled(
                                f"{active_name} produced {STALL_THRESHOLD} consecutive no-op turns "
                                f"with no assistant text and no recorded tool activity"
                            )
                        prompt = build_continue_prompt(active_name, bus.data)
                except UsageResetRequired as error:
                    status_label = getattr(error, "status_label", "USAGE_EXHAUSTED")
                    verb = "hot-loop detected" if status_label == "STALLED_PROVIDER" else "usage limit reached"
                    bus.update(
                        event=f"{active_name.capitalize()} {verb}: {error}",
                        **{active_name: {**bus.data.get(active_name, {}), "status": status_label, "reset_at": error.reset_at, "last_error": str(error)}},
                    )
                finally:
                    agent.deactivate()

                bus.update(event="Checkpoint saved")

                def usable(name: str) -> bool:
                    return is_agent_usable(bus.data.get(name, {}), name in instances)

                def pick_ready(current: str) -> str | None:
                    return pick_ready_agent(bus.data, set(instances), agent_order, current)

                next_name = pick_ready(active_name)
                if next_name is None:
                    # Neither provider usable: wait and retry instead of exiting.
                    waiting_state = "WAITING_FOR_AGENT_CAPACITY" if len(instances) > 1 else "WAITING_FOR_USAGE_RESET"
                    bus.update(state=waiting_state, active_agent=None, current_action="Waiting for agent capacity", event=f"Entering {waiting_state}")
                    while True:
                        if shutdown_event.is_set():
                            raise Shutdown()
                        next_name = pick_ready(active_name)
                        if next_name is not None:
                            break
                        # Conservative bounded poll: previously min(...,30) made this
                        # effectively ignore CAPACITY_RECHECK_SECONDS and always
                        # busy-poll every 30s regardless of the configured interval.
                        shutdown_event.wait(CAPACITY_RECHECK_SECONDS)
                    bus.update(event="Agent capacity recheck: resuming")

                bus.update(state="ROTATING_AGENT", active_agent=None)
                if next_name != active_name:
                    bus.update(event=f"Rotating {active_name.capitalize()} -> {next_name.capitalize()}")
                    state["rotation_count"] = state.get("rotation_count", 0) + 1
                    bus.update(rotation_count=state["rotation_count"])
                else:
                    bus.update(event=f"Resuming {active_name.capitalize()} after usage reset")
                active_name = next_name
                continue
        except Shutdown:
            bus.update(state="STOPPING", current_action="Finishing shutdown", event="Ctrl+C received, shutting down")
            owner = bus.data.get("mutation_lease_owner")
            if owner and owner != "none":
                bus.update(event=f"Mutation lease still held by {owner}; left for next turn to reconcile")
            try:
                instances[active_name].deactivate()
            except Exception:
                pass
            return 0
        finally:
            shutdown_event.set()
            if dashboard_thread is not None:
                dashboard_thread.join(timeout=3)
    except Exception as error:
        try:
            bus.update(state="FAILED", event=f"Unrecoverable failure: {error}")
        except Exception:
            pass
        return 1
    finally:
        lease.close()


if __name__ == "__main__":
    sys.exit(main())
