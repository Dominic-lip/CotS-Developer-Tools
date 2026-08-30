#!/usr/bin/env python3
"""Stable outer monitor: Factory outcome -> FixIt -> corrected Factory restart."""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from CotSRecovery import (COTS, FACTORY_STATE, HUMAN_REQUIRED_EXIT, INCIDENTS, MAX_INCIDENT_LOG,
                              RECOVERABLE_EXIT, IncidentCategory, atomic_json, read_json, write_incident,
                              SUPERVISOR_STATE, clear_provider_activity, provider_is_active, reclaim_orphaned_provider)
    from CotSFactoryDashboard import TerminalDashboard
except ModuleNotFoundError:
    from Scripts.CotSRecovery import (COTS, FACTORY_STATE, HUMAN_REQUIRED_EXIT, INCIDENTS, MAX_INCIDENT_LOG,
                                      RECOVERABLE_EXIT, IncidentCategory, atomic_json, read_json, write_incident,
                                      SUPERVISOR_STATE, clear_provider_activity, provider_is_active, reclaim_orphaned_provider)
    from Scripts.CotSFactoryDashboard import TerminalDashboard

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
FACTORY = SCRIPTS / "CotSFactoryController.py"
FIXIT = SCRIPTS / "CotSAgentFixIt.py"
MAX_ATTEMPTS = 3


def latest_incident() -> Path | None:
    paths = sorted(INCIDENTS.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True) if INCIDENTS.exists() else []
    return paths[0] if paths else None


def factory_crash_incident(exit_code: int) -> Path:
    return write_incident(IncidentCategory.FACTORY_CONTROLLER, f"Factory Controller exited unexpectedly ({exit_code})",
                          affected_component="factory", error_code="FACTORY_EXIT")


def set_recovery(incident: Path, state: str, attempt: int, **extra: object) -> None:
    value = read_json(FACTORY_STATE)
    previous = value.get("recovery") or {}
    value["recovery"] = {"state": state, "incident": incident.stem, "attempt": attempt,
                         "started_at": previous.get("started_at", time.time()), **extra}
    atomic_json(FACTORY_STATE, value)


def dashboard_snapshot() -> dict:
    value = dict(read_json(FACTORY_STATE))
    value["supervisor"] = dict(read_json(SUPERVISOR_STATE))
    return value


def deactivate_for_fixit() -> bool:
    """Bootstrap never trusts a stale ACTIVE label from a dead supervisor."""
    checkpoint = read_json(SUPERVISOR_STATE)
    if checkpoint.get("orphaned_provider_ownership") and not reclaim_orphaned_provider(checkpoint):
        return False
    if provider_is_active(checkpoint):
        if not reclaim_orphaned_provider(checkpoint):
            return False
    atomic_json(SUPERVISOR_STATE, clear_provider_activity(checkpoint))
    return True


def run(*, popen=subprocess.Popen, runner=subprocess.run) -> int:
    dashboard = TerminalDashboard()
    stop = threading.Event()
    def paint() -> None:
        while not stop.is_set():
            dashboard.draw(dashboard_snapshot()); stop.wait(0.75)
    thread = threading.Thread(target=paint, name="cots-bootstrap-dashboard", daemon=True); thread.start()
    try:
      while True:
        factory = popen([sys.executable, str(FACTORY)], cwd=REPO, text=True)
        exit_code = factory.wait()
        if exit_code == 0:
            return 0
        if exit_code == HUMAN_REQUIRED_EXIT:
            return HUMAN_REQUIRED_EXIT
        incident = latest_incident() if exit_code == RECOVERABLE_EXIT else factory_crash_incident(exit_code)
        if incident is None:
            return HUMAN_REQUIRED_EXIT
        fingerprint = incident.stem
        persisted = read_json(FACTORY_STATE)
        attempts = dict(persisted.get("fixit_attempts") or {})
        attempt = int(attempts.get(fingerprint, 0)) + 1
        attempts[fingerprint] = attempt
        persisted["fixit_attempts"] = attempts
        atomic_json(FACTORY_STATE, persisted)
        if attempt > MAX_ATTEMPTS:
            set_recovery(incident, "HUMAN_REQUIRED", MAX_ATTEMPTS, reason="maximum FixIt attempts exhausted")
            return HUMAN_REQUIRED_EXIT
        if not deactivate_for_fixit():
            set_recovery(incident, "WAITING_FOR_PROVIDER_CLEANUP", attempt, current_action="Waiting for owned provider cleanup")
            time.sleep(2)
            continue
        set_recovery(incident, "REPAIRING", attempt, current_action="Launching external AgentFixIt")
        repaired = runner([sys.executable, str(FIXIT), "--incident", str(incident), "--attempt", str(attempt)],
                          cwd=REPO, text=True, capture_output=True, timeout=7300, check=False)
        result = read_json(COTS / "fixit-result.local.json")
        if result.get("result") == "SUCCESS":
            value = read_json(FACTORY_STATE); value["last_recovery"] = {"incident": incident.stem, "attempt": attempt, "result": "SUCCESS", "completed_at": time.time()}; value["recovery"] = {"state": "IDLE"}; atomic_json(FACTORY_STATE, value)
            continue
        if result.get("result") == "HUMAN_REQUIRED":
            set_recovery(incident, "HUMAN_REQUIRED", attempt, reason=result.get("reason", "repair worker requires human"))
            return HUMAN_REQUIRED_EXIT
        if result.get("result") == "WAITING_FOR_PROVIDER":
            attempts[fingerprint] = max(0, attempt - 1)
            persisted["fixit_attempts"] = attempts
            atomic_json(FACTORY_STATE, persisted)
            set_recovery(incident, "WAITING_FOR_PROVIDER", attempt, current_action="Locally probing for repair provider")
            time.sleep(30)
            continue
        set_recovery(incident, "RETRYABLE_FAILURE", attempt, reason=(repaired.stdout + repaired.stderr)[-MAX_INCIDENT_LOG:])
        # Continue the loop: same fingerprint advances automatically to 2/3.
    finally:
      stop.set(); thread.join(timeout=2); dashboard.close()


if __name__ == "__main__":
    raise SystemExit(run())
