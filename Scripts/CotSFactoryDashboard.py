#!/usr/bin/env python3
"""Pure presentation for the CotS Autonomous Factory terminal dashboard.

This module deliberately consumes a plain snapshot.  It owns no processes,
does not write checkpoints, and makes no recovery decisions; that keeps the
controller's safety contract separate from the terminal UI.
"""
from __future__ import annotations

import re
import shutil
import sys
import time
import ctypes
from typing import Any, TextIO

SPINNER = ("|", "/", "-", "\\")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
MAX_EVENTS = 10

COLORS = {
    "green": "\x1b[32m", "cyan": "\x1b[36m", "blue": "\x1b[34m",
    "magenta": "\x1b[35m", "yellow": "\x1b[33m", "red": "\x1b[31m",
    "dim": "\x1b[2m", "reset": "\x1b[0m",
}


def strip_terminal_controls(value: object) -> str:
    """Make externally sourced state safe for one dashboard row."""
    text = " ".join(ANSI_RE.sub("", str(value or "")).replace("\r", " ").replace("\n", " ").split())
    if text.startswith("{") or '"jsonrpc"' in text or '"method"' in text:
        return "Protocol detail withheld (see protocol log)"
    return text


def status_style(state: object) -> tuple[str, str]:
    """Return a human status and its semantic colour, independent of ANSI."""
    value = str(state or "STARTING").upper()
    if value in {"COMPLETE"}:
        return "COMPLETE", "green"
    if value in {"HUMAN_REQUIRED", "HUMAN_GATE", "FAILED", "TERMINAL_FAILURE"}:
        return ("HUMAN_REQUIRED" if "HUMAN" in value else "FAILED"), "red"
    if "REPAIR" in value or "RECOVERABLE" in value:
        return "REPAIRING", "yellow"
    if value.startswith("WAIT") or value in {"ROTATING_AGENT", "STOPPING"}:
        return "WAITING", "yellow"
    if value.startswith("RUNNING_") or value in {"CONTINUING", "PREFLIGHT"}:
        return "WORKING", "cyan"
    if value == "RUNNING":
        return "RUNNING", "green"
    return "RUNNING", "cyan"


def spinner_frame(index: int) -> str:
    return SPINNER[index % len(SPINNER)]


def format_elapsed(seconds: float | int | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _truncate(value: object, width: int) -> str:
    text = strip_terminal_controls(value)
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _agent_line(name: str, info: dict[str, Any], width: int) -> str:
    status = info.get("status", "UNKNOWN")
    version = info.get("version") or "unknown"
    extra = ""
    if info.get("reset_at"):
        extra = " reset " + time.strftime("%H:%M", time.localtime(info["reset_at"]))
    elif info.get("next_availability_probe_at"):
        extra = " probe " + time.strftime("%H:%M:%S", time.localtime(info["next_availability_probe_at"]))
    return _truncate(f"{name:<6} {status:<18} v{version}{extra}", width)


def render_lines(snapshot: dict[str, Any], spinner_index: int = 0, width: int | None = None) -> list[str]:
    """Render a bounded, ANSI-free frame for tests and non-colour terminals."""
    width = max(60, min(width or shutil.get_terminal_size((100, 24)).columns, 120))
    inner = width - 4
    def row(text: object = "") -> str:
        return "│ " + _truncate(text, inner).ljust(inner) + " │"
    def top(title: str) -> str:
        heading = f" {title} "
        return "┌" + heading + "─" * max(0, width - len(heading) - 2) + "┐"
    bottom = "└" + "─" * (width - 2) + "┘"

    factory_state = snapshot.get("factory", snapshot.get("state", "STARTING"))
    status, _color = status_style(factory_state)
    uptime = format_elapsed(time.time() - float(snapshot.get("started_at") or time.time()))
    recovery = snapshot.get("recovery") or {}
    recovery_state = recovery.get("state", "IDLE")
    checkpoint = snapshot.get("supervisor") or snapshot
    task = checkpoint.get("task") or snapshot.get("task") or "RECONCILING"
    title = checkpoint.get("task_title") or snapshot.get("task_title") or ""
    phase = checkpoint.get("phase") or snapshot.get("phase") or "RECONCILING"
    action = checkpoint.get("current_action") or snapshot.get("current_action") or "Awaiting controller activity"
    action_started = checkpoint.get("action_started_at") or checkpoint.get("updated_at") or snapshot.get("updated_at")
    action_elapsed = format_elapsed(time.time() - float(action_started)) if action_started else "00:00:00"
    active = checkpoint.get("active_agent") or "none"
    preferred = checkpoint.get("preferred_agent") or "codex"
    active_is_real = str(checkpoint.get("state", "")).startswith("RUNNING_") and checkpoint.get("active_agent")
    active_label = str(active).upper() if active_is_real else "NONE"
    events = list(snapshot.get("recent_events") or checkpoint.get("recent_events") or [])[-MAX_EVENTS:]

    lines = [top("CotS Autonomous Factory")]
    lines += [
        row(f"{spinner_frame(spinner_index)} {status:<15} Uptime {uptime}       Recovery: {recovery_state}"),
        row(f"Task {task}" + (f" — {title}" if title else "")),
        row(f"Phase {phase}"),
        row(f"Current: {action}  {action_elapsed}"),
        row(f"Last successful gate: {checkpoint.get('last_successful_gate') or 'none yet'}"),
        row(f"Next: {snapshot.get('next_expected_action') or recovery.get('current_action') or 'not deterministically known'}"),
        bottom,
        top("Services"),
        row(f"Factory Controller  {snapshot.get('factory', 'STARTING')}    Supervisor  {snapshot.get('supervisor_state', checkpoint.get('state', 'UNKNOWN'))}"),
        row(f"Host MCP  {snapshot.get('host_state', checkpoint.get('host_mcp_state', 'UNKNOWN'))}    Unreal MCP  {checkpoint.get('unreal_mcp_state', 'UNKNOWN')}"),
        row(f"Unreal / ToolLab  {checkpoint.get('toollab_state', 'UNKNOWN')}    Mutation lease  {checkpoint.get('mutation_lease_owner', 'none')}"),
        bottom,
        top("Agents"),
        row(f"Active  {active_label}    Preferred  {str(preferred).upper()}    Turns  {checkpoint.get('turn_count', 0)}    Rotations  {checkpoint.get('rotation_count', 0)}"),
        row(_agent_line("Codex", checkpoint.get("codex") or {}, inner)),
        row(_agent_line("Claude", checkpoint.get("claude") or {}, inner)),
        bottom,
        top("Efficiency"),
        row(f"Task turns {((checkpoint.get('efficiency') or {}).get('task_turns', checkpoint.get('turn_count', 0)))}    New reads {((checkpoint.get('efficiency') or {}).get('files_newly_read_this_turn', 0))}    Unchanged rereads {((checkpoint.get('efficiency') or {}).get('files_reread_unchanged', 0))}"),
        row(f"Targeted tests {((checkpoint.get('efficiency') or {}).get('targeted_test_runs', 0))}    Full suites {((checkpoint.get('efficiency') or {}).get('full_suite_runs', 0))}    Repeated failures {((checkpoint.get('efficiency') or {}).get('repeated_failure_count', 0))}"),
        row(f"Context {((checkpoint.get('efficiency') or {}).get('checkpoint_context_size', 0))} bytes    Turn elapsed {format_elapsed(float((checkpoint.get('efficiency') or {}).get('current_turn_elapsed_ms', 0)) / 1000)}"),
        bottom,
        top("Repository"),
        row(f"{snapshot.get('git_branch', '?')} · {snapshot.get('git_status', '?')} · {snapshot.get('last_commit', '?')}"),
    ]
    counts = snapshot.get("git_status_counts") or {}
    if counts:
        lines.append(row(f"Protected {counts.get('protected', 0)} · untracked {counts.get('untracked_other', 0)} · factory changes {counts.get('supervisor', 0)}"))
    lines.append(bottom)
    if recovery_state not in {"", "IDLE", None}:
        lines += [top("Recovery"), row(f"Category: {recovery.get('category', 'unknown')}    Incident: {recovery.get('incident', 'unknown')}"),
                  row(f"Attempt {recovery.get('attempt', 0)}/3    Repairing agent: {recovery.get('repairing_agent', active_label)}"),
                  row(f"State: {recovery_state}    Elapsed: {format_elapsed(time.time() - float(recovery.get('started_at') or snapshot.get('updated_at') or time.time()))}"),
                  row(f"Action: {recovery.get('current_action') or 'controlled repair'}"),
                  row(f"Previous failure: {recovery.get('reason') or recovery.get('previous_failure') or 'none'}"), bottom]
    lines += [top("Recent Activity")]
    lines.extend(row(event) for event in (events or ["(none yet)"]))
    lines += [bottom, "Ctrl+C  Safe shutdown  ·  Factory will checkpoint before exit"]
    return lines


def render_frame(snapshot: dict[str, Any], spinner_index: int = 0, width: int | None = None, color: bool = False) -> str:
    lines = render_lines(snapshot, spinner_index, width)
    if not color:
        return "\n".join(lines)
    _status, colour = status_style(snapshot.get("factory", snapshot.get("state")))
    # Colour only semantic highlights; control sequences never enter state/event data.
    styled: list[str] = []
    for index, line in enumerate(lines):
        tone = None
        if index == 0 or "Task " in line or "Current:" in line:
            tone = "cyan"
        elif index == 1:
            tone = colour
        elif "Active  " in line or "Preferred" in line:
            tone = "magenta"
        elif "Repository" in line or "Protected " in line:
            tone = "dim"
        elif "WAITING" in line or "REPAIR" in line:
            tone = "yellow"
        elif "FAILED" in line or "HUMAN_REQUIRED" in line:
            tone = "red"
        elif "COMPLETE" in line or " READY" in line or " clean " in line:
            tone = "green"
        styled.append((COLORS[tone] + line + COLORS["reset"]) if tone else line)
    return "\n".join(styled)


class TerminalDashboard:
    """Small redraw sink.  ANSI is optional and disabled for redirected output."""
    def __init__(self, stream: TextIO | None = None, color: bool | None = None) -> None:
        self.stream = stream or sys.stdout
        self._enable_windows_ansi()
        self.color = bool(self.stream.isatty()) if color is None else color
        self.ansi = bool(self.stream.isatty())
        try:
            "┌".encode(self.stream.encoding or "utf-8")
            self.unicode = True
        except UnicodeEncodeError:
            self.unicode = False
        self.spinner_index = 0

    @staticmethod
    def _enable_windows_ansi() -> None:
        if sys.platform != "win32" or not sys.stdout.isatty():
            return
        try:
            handle = ctypes.windll.kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass

    def draw(self, snapshot: dict[str, Any]) -> None:
        frame = render_frame(snapshot, self.spinner_index, color=self.color)
        self.spinner_index += 1
        if not self.unicode:
            frame = frame.translate(str.maketrans({"┌": "+", "┐": "+", "└": "+", "┘": "+", "─": "-", "│": "|", "·": ".", "—": "-", "…": "..."}))
        if self.ansi:
            payload = "\x1b[H" + "\x1b[K\n".join(frame.splitlines()) + "\x1b[K\x1b[0J"
            self.stream.write(payload)
        else:
            self.stream.write(frame + "\n")
        self.stream.flush()
