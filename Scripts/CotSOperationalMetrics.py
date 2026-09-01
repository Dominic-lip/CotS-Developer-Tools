#!/usr/bin/env python3
"""Rolling local uptime/productivity metrics for CotS 24x7.

The store keeps tiny JSONL samples for the last 48 hours so the UI can report
real 24-hour uptime and productivity without asking an AI model.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, safe_nonnegative_int

SAMPLES = COTS / "operational-metrics.jsonl"
SAMPLE_INTERVAL_SECONDS = 30
RETENTION_SECONDS = 48 * 60 * 60


class OperationalMetrics:
    def __init__(self) -> None:
        self.last_sample_at = 0.0

    def record(self, health: dict[str, Any], supervisor: dict[str, Any], governor: dict[str, Any], hardware: dict[str, Any]) -> None:
        now = time.time()
        if now - self.last_sample_at < SAMPLE_INTERVAL_SECONDS: return
        self.last_sample_at = now
        state = str(health.get("state") or "UNKNOWN")
        alive = state not in {"STOPPED", "STOPPING"}
        productive = bool(governor.get("last_productive_at") and now - float(governor.get("last_productive_at") or 0) <= 15 * 60)
        record = {
            "ts": now, "alive": alive, "productive": productive, "state": state,
            "task": supervisor.get("task"), "turn_count": safe_nonnegative_int(supervisor.get("turn_count"), 0),
            "useful_turns": safe_nonnegative_int(governor.get("useful_turns"), 0),
            "commits": safe_nonnegative_int(governor.get("commits"), 0),
            "tests": safe_nonnegative_int(governor.get("tests"), 0),
            "acceptance_proofs": safe_nonnegative_int(governor.get("acceptance_proofs"), 0),
            "recoveries": safe_nonnegative_int(health.get("restart_count"), 0),
            "human_required": 1 if state == "HUMAN_REQUIRED" else 0,
            "disk_free_gb": ((hardware.get("disk") or {}).get("free_gb")),
        }
        SAMPLES.parent.mkdir(parents=True, exist_ok=True)
        with SAMPLES.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._prune(now)

    def _read(self, since: float) -> list[dict[str, Any]]:
        try:
            rows = []
            for line in SAMPLES.read_text(encoding="utf-8", errors="replace").splitlines():
                try: value = json.loads(line)
                except json.JSONDecodeError: continue
                if isinstance(value, dict) and isinstance(value.get("ts"), (int, float)) and value["ts"] >= since:
                    rows.append(value)
            return rows
        except OSError:
            return []

    def _prune(self, now: float) -> None:
        try:
            rows = self._read(now - RETENTION_SECONDS)
            if not rows: return
            with SAMPLES.open("w", encoding="utf-8") as handle:
                for row in rows: handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def report(self, hours: float = 24.0) -> dict[str, Any]:
        now = time.time(); rows = self._read(now - hours * 3600)
        if not rows:
            return {"window_hours": hours, "samples": 0, "uptime_percent": None, "productive_percent": None,
                    "useful_turns": 0, "commits": 0, "tests": 0, "recoveries": 0, "human_interventions": 0}
        alive = sum(1 for row in rows if row.get("alive")); productive = sum(1 for row in rows if row.get("productive"))
        first, last = rows[0], rows[-1]
        def delta(field: str) -> int:
            return max(0, safe_nonnegative_int(last.get(field), 0) - safe_nonnegative_int(first.get(field), 0))
        human_transitions = 0; previous = False
        for row in rows:
            current = bool(row.get("human_required"))
            if current and not previous: human_transitions += 1
            previous = current
        return {
            "window_hours": hours, "samples": len(rows), "uptime_percent": 100.0 * alive / len(rows),
            "productive_percent": 100.0 * productive / len(rows), "useful_turns": delta("useful_turns"),
            "commits": delta("commits"), "tests": delta("tests"), "acceptance_proofs": delta("acceptance_proofs"),
            "recoveries": delta("recoveries"), "human_interventions": human_transitions,
        }


if __name__ == "__main__":
    print(json.dumps(OperationalMetrics().report(), indent=2))
