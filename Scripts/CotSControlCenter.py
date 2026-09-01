#!/usr/bin/env python3
"""CotS Factory V4 Control Center.

All filesystem/Git/diagnostic reads run off the Tk UI thread.  The window never
kills arbitrary processes: Run owns only the bootstrap child it launches, and
Stop Safely uses the durable Factory stop request plus provider-cancel contract.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
TOOLS_REPO = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from CotSProductionPreflight import check as run_preflight
from CotSRecovery import FACTORY_STATE, SUPERVISOR_STATE, atomic_json, read_json, request_provider_cancel
from CotSWorkspaceProfiles import profile_for_task

BOOTSTRAP = SCRIPT_DIR / "CotSFactoryBootstrapV4.py"
STOP_REQUEST = TOOLS_REPO / ".cots" / "factory-stop-request.local.json"
V4_FACTORY_STATE = TOOLS_REPO / ".cots" / "factory-controller-v4.local.json"
LEDGER = TOOLS_REPO / "Docs" / "FOUNDATION_COMPLETION_STATE.json"


def next_required_task() -> str | None:
    try:
        document = json.loads(LEDGER.read_text(encoding="utf-8"))
        for entry in document.get("tasks") or []:
            if isinstance(entry, dict) and entry.get("status") != "COMPLETE_VERIFIED":
                return str(entry.get("id"))
    except (OSError, json.JSONDecodeError):
        return None
    return None


def age_text(timestamp: Any) -> str:
    if not isinstance(timestamp, (int, float)):
        return "unknown"
    age = max(0, int(time.time() - float(timestamp)))
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    return f"{age // 3600}h {(age % 3600) // 60}m ago"


def snapshot() -> dict[str, Any]:
    factory = read_json(FACTORY_STATE)
    v4 = read_json(V4_FACTORY_STATE)
    supervisor = read_json(SUPERVISOR_STATE)
    task = next_required_task()
    profile = profile_for_task(task)
    provider = supervisor.get("active_agent")
    provider_turn = supervisor.get("provider_turn") if isinstance(supervisor.get("provider_turn"), dict) else {}
    context = supervisor.get("context_health") if isinstance(supervisor.get("context_health"), dict) else {}
    efficiency = supervisor.get("efficiency") if isinstance(supervisor.get("efficiency"), dict) else {}
    return {
        "task": task,
        "profile": profile.name,
        "workspace": str(profile.workspace_root),
        "repository": profile.repository,
        "project": str(profile.project_path),
        "factory": factory,
        "factory_v4": v4,
        "supervisor": supervisor,
        "provider": provider,
        "provider_heartbeat_age": age_text(provider_turn.get("heartbeat_at") or supervisor.get("provider_turn_heartbeat_at")),
        "checkpoint_age": age_text(supervisor.get("updated_at")),
        "context": context,
        "efficiency": efficiency,
    }


class Background:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.results: "queue.Queue[tuple[Callable[[Any], None], Any, BaseException | None]]" = queue.Queue()
        self.root.after(100, self._drain)

    def submit(self, fn: Callable[[], Any], callback: Callable[[Any], None]) -> None:
        def run() -> None:
            try:
                value = fn()
                self.results.put((callback, value, None))
            except BaseException as error:
                self.results.put((callback, None, error))
        threading.Thread(target=run, daemon=True).start()

    def _drain(self) -> None:
        while True:
            try:
                callback, value, error = self.results.get_nowait()
            except queue.Empty:
                break
            if error is not None:
                callback({"error": f"{type(error).__name__}: {error}"})
            else:
                callback(value)
        self.root.after(100, self._drain)


class ControlCenter:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("CotS Autonomous Factory V4")
        self.root.geometry("1180x760")
        self.root.minsize(940, 640)
        self.bg = Background(self.root)
        self.bootstrap_process: subprocess.Popen[str] | None = None
        self.refresh_inflight = False
        self.status_var = tk.StringVar(value="Loading…")
        self.task_var = tk.StringVar(value="—")
        self.profile_var = tk.StringVar(value="—")
        self.workspace_var = tk.StringVar(value="—")
        self.repo_var = tk.StringVar(value="—")
        self.provider_var = tk.StringVar(value="—")
        self.heartbeat_var = tk.StringVar(value="—")
        self.context_var = tk.StringVar(value="—")
        self.current_action_var = tk.StringVar(value="—")
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(150, self.refresh)

    def _build(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="Chronicles of the Sigilarium — Autonomous Factory", font=("Segoe UI", 17, "bold"))
        title.pack(anchor="w")
        ttk.Label(outer, textvariable=self.status_var).pack(anchor="w", pady=(2, 12))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(0, 12))
        ttk.Button(buttons, text="Run Autonomously", command=self.start_factory).pack(side="left")
        ttk.Button(buttons, text="Stop Safely", command=self.stop_safely).pack(side="left", padx=8)
        ttk.Button(buttons, text="Run Diagnostics", command=self.diagnostics).pack(side="left")
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(side="left", padx=8)

        summary = ttk.LabelFrame(outer, text="Current work", padding=10)
        summary.pack(fill="x")
        rows = [
            ("Task", self.task_var),
            ("Profile", self.profile_var),
            ("Workspace", self.workspace_var),
            ("Repository", self.repo_var),
            ("Provider", self.provider_var),
            ("Provider heartbeat", self.heartbeat_var),
            ("Context", self.context_var),
            ("Current action", self.current_action_var),
        ]
        for row, (label, variable) in enumerate(rows):
            ttk.Label(summary, text=label + ":", width=20).grid(row=row, column=0, sticky="nw", pady=2)
            ttk.Label(summary, textvariable=variable).grid(row=row, column=1, sticky="nw", pady=2)
        summary.columnconfigure(1, weight=1)

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(12, 0))
        left = ttk.LabelFrame(body, text="Recent activity", padding=8)
        right = ttk.LabelFrame(body, text="Diagnostics / details", padding=8)
        body.add(left, weight=3)
        body.add(right, weight=2)
        self.activity = tk.Text(left, wrap="word", height=18, state="disabled")
        self.activity.pack(fill="both", expand=True)
        self.details = tk.Text(right, wrap="word", height=18, state="disabled")
        self.details.pack(fill="both", expand=True)

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def refresh(self) -> None:
        if self.refresh_inflight:
            return
        self.refresh_inflight = True

        def done(value: Any) -> None:
            self.refresh_inflight = False
            if not isinstance(value, dict):
                return
            if value.get("error"):
                self.status_var.set(value["error"])
                return
            self.render(value)
            self.root.after(1000, self.refresh)

        self.bg.submit(snapshot, done)

    def render(self, data: dict[str, Any]) -> None:
        factory = data.get("factory") or {}
        v4 = data.get("factory_v4") or {}
        supervisor = data.get("supervisor") or {}
        factory_state = v4.get("state") or factory.get("factory") or "STOPPED"
        supervisor_state = supervisor.get("state") or "STOPPED"
        self.status_var.set(f"Factory: {factory_state}   Supervisor: {supervisor_state}   Checkpoint: {data.get('checkpoint_age')}")
        self.task_var.set(str(data.get("task") or "ROADMAP COMPLETE"))
        self.profile_var.set(str(data.get("profile") or "—"))
        self.workspace_var.set(str(data.get("workspace") or "—"))
        self.repo_var.set(str(data.get("repository") or "—"))
        self.provider_var.set(str(data.get("provider") or "idle"))
        self.heartbeat_var.set(str(data.get("provider_heartbeat_age") or "—"))
        context = data.get("context") or {}
        if context:
            self.context_var.set(json.dumps(context, separators=(",", ":"))[:220])
        else:
            efficiency = data.get("efficiency") or {}
            size = efficiency.get("checkpoint_context_size")
            self.context_var.set(f"checkpoint {size} bytes" if size is not None else "not reported")
        self.current_action_var.set(str(supervisor.get("current_action") or factory.get("next_expected_action") or "—"))
        events = []
        events.extend(factory.get("recent_events") or [])
        events.extend(supervisor.get("recent_events") or [])
        self._set_text(self.activity, "\n".join(str(item) for item in events[-30:]) or "No activity recorded.")

    def start_factory(self) -> None:
        if self.bootstrap_process is not None and self.bootstrap_process.poll() is None:
            messagebox.showinfo("CotS Factory", "The Control Center already owns a running Factory bootstrap.")
            return
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            self.bootstrap_process = subprocess.Popen(
                [sys.executable, str(BOOTSTRAP)],
                cwd=TOOLS_REPO,
                text=True,
                creationflags=flags,
            )
        except OSError as error:
            messagebox.showerror("CotS Factory", f"Could not start the Factory: {error}")
            return
        self.status_var.set(f"Factory bootstrap launched (PID {self.bootstrap_process.pid})")
        self.refresh()

    def stop_safely(self) -> None:
        factory = read_json(FACTORY_STATE)
        supervisor_pid = factory.get("supervisor_pid")
        atomic_json(STOP_REQUEST, {"requested_at": time.time(), "reason": "operator safe stop"})
        if isinstance(supervisor_pid, int) and supervisor_pid > 0:
            request_provider_cancel(supervisor_pid, "operator safe stop")
        self.status_var.set("Safe stop requested; waiting for the active provider boundary. No broad process kill will be used.")
        self.refresh()

    def diagnostics(self) -> None:
        task = next_required_task()
        profile = profile_for_task(task).name
        self._set_text(self.details, f"Running {profile} preflight…")

        def done(value: Any) -> None:
            self._set_text(self.details, json.dumps(value, indent=2, default=str))

        self.bg.submit(lambda: run_preflight(profile), done)

    def close(self) -> None:
        # Closing the window is not equivalent to killing the Factory. If this
        # Control Center owns a live bootstrap, ask explicitly rather than
        # silently orphaning/terminating it.
        if self.bootstrap_process is not None and self.bootstrap_process.poll() is None:
            if not messagebox.askyesno("CotS Factory", "The Factory appears to be running. Close only the Control Center window and leave it running?"):
                return
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    ControlCenter().run()
