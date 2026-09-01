#!/usr/bin/env python3
"""Local milestone notifications for CotS 24x7.

Notifications are intentionally sparse and deduplicated.  On Windows a small
local tray balloon is used; otherwise events are recorded to the local
telemetry log.  No external notification service is contacted.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, DailyTelemetry, atomic_json, clean_text, read_json

STATE = COTS / "notification-state.local.json"
MIN_REPEAT_SECONDS = 60 * 60


def _balloon(title: str, message: str) -> None:
    if os.name != "nt": return
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe: return
    safe_title = title.replace("'", "''")[:120]
    safe_message = message.replace("'", "''")[:700]
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
        "$n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Information; "
        f"$n.BalloonTipTitle='{safe_title}'; $n.BalloonTipText='{safe_message}'; $n.Visible=$true; "
        "$n.ShowBalloonTip(8000); Start-Sleep -Seconds 9; $n.Dispose()"
    )
    try:
        subprocess.Popen([exe, "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class MilestoneNotifier:
    def __init__(self) -> None:
        self.telemetry = DailyTelemetry()
        self.state = read_json(STATE, {"sent": {}, "last_task": None})
        self.state.setdefault("sent", {})

    def _emit(self, key: str, title: str, message: str, repeat_seconds: int = MIN_REPEAT_SECONDS) -> bool:
        now = time.time(); previous = self.state["sent"].get(key)
        if isinstance(previous, (int, float)) and now - previous < repeat_seconds:
            return False
        self.state["sent"][key] = now; atomic_json(STATE, self.state)
        self.telemetry.emit("MILESTONE", f"{title}: {message}", notification_key=key)
        _balloon(title, message)
        return True

    def poll(self, health: dict[str, Any], supervisor: dict[str, Any], *, cooldown_seconds: float = 0.0) -> None:
        current_task = supervisor.get("task")
        previous_task = self.state.get("last_task")
        if previous_task and current_task and current_task != previous_task:
            self._emit(f"task:{previous_task}:complete", "CotS task advanced", f"{previous_task} completed; now working {current_task}", repeat_seconds=24*3600)
        if current_task:
            self.state["last_task"] = current_task

        state = str(health.get("state") or "")
        if state == "HUMAN_REQUIRED":
            self._emit("human-required", "CotS needs attention", clean_text(health.get("current_action"), 500))

        if cooldown_seconds >= 1800:
            self._emit("long-cooldown", "CotS in 30-minute cooldown", "Repeated no-progress recovery triggered the maximum local backoff.")

        for name in ("codex", "claude"):
            info = supervisor.get(name) if isinstance(supervisor.get(name), dict) else {}
            if info.get("status") == "USAGE_EXHAUSTED":
                reset = info.get("reset_at")
                when = time.strftime("%H:%M", time.localtime(reset)) if isinstance(reset, (int, float)) else "unknown reset time"
                self._emit(f"quota:{name}", f"{name.capitalize()} quota exhausted", f"Provider will remain idle until {when}.")

        last_progress = health.get("last_progress_at")
        if state not in {"STOPPED_BY_USER", "ROADMAP_COMPLETE"} and isinstance(last_progress, (int, float)) and time.time() - last_progress >= 3600:
            self._emit("unhealthy-hour", "CotS has made no progress for an hour", clean_text(health.get("current_action"), 500))
        atomic_json(STATE, self.state)


if __name__ == "__main__":
    notifier = MilestoneNotifier(); print(json.dumps(notifier.state, indent=2))
