#!/usr/bin/env python3
"""Continuous campaign watchdog.

Uses the production 24x7 watchdog but routes factory work through the reviewed
campaign wrappers, owns the loopback host-side production lifecycle bridge, and
treats an authoritatively completed campaign as an idle terminal state rather
than a recoverable failure.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import CotSWatchdog24x7Final as final
from CotS24x7Common import FACTORY_STATE, SUPERVISOR_STATE, atomic_json, read_json
from CotSProductionHostBridge import ProductionHostBridge

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "Scripts"
COMPLETION_STATE = REPO / "Docs" / "FOUNDATION_COMPLETION_STATE.json"

# The final watchdog ultimately launches enhanced.base.FACTORY. Override only
# that fixed reviewed path; no arbitrary executable selection is introduced.
final.enhanced.base.FACTORY = SCRIPTS / "CotSFactoryControllerCampaign.py"


def campaign_complete() -> bool:
    try:
        doc = json.loads(COMPLETION_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    tasks = doc.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False
    return all(isinstance(entry, dict) and entry.get("status") == "COMPLETE_VERIFIED" for entry in tasks)


def supervisor_reports_complete() -> bool:
    sup = read_json(SUPERVISOR_STATE)
    return (
        str(sup.get("state") or "") == "COMPLETE"
        or str(sup.get("current_action") or "").strip().lower() == "roadmap completion verified"
    )


def mark_factory_complete() -> None:
    fac = read_json(FACTORY_STATE)
    fac.update({
        "factory": "COMPLETE",
        "supervisor_state": "STOPPED",
        "updated_at": time.time(),
        "recovery": {"state": "COMPLETE"},
    })
    events = list(fac.get("recent_events") or [])
    events.append(time.strftime("%H:%M:%S") + "  Campaign completion verified; watchdog waiting for reviewed work")
    fac["recent_events"] = events[-10:]
    atomic_json(FACTORY_STATE, fac)


class CampaignWatchdog(final.ProductionWatchdog):
    """Persistent campaign plus host-side production execution boundary."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.production_host = ProductionHostBridge()

    def run(self) -> int:
        self.production_host.start()
        self.telemetry.emit(
            "PRODUCTION_HOST_READY",
            "Loopback production lifecycle bridge is online under the watchdog host identity",
            host="127.0.0.1",
            port=8011,
        )
        try:
            return int(super().run())
        finally:
            self.production_host.stop()

    def monitor_factory(self, before: dict[str, Any], started: float) -> tuple[int, float, bool, str | None]:
        exit_code, runtime, progressed, control = super().monitor_factory(before, started)
        if control is None and campaign_complete() and supervisor_reports_complete():
            mark_factory_complete()
            self.no_progress_streak = 0
            self.state = "ROADMAP_COMPLETE"
            self.current_action = "Reviewed campaign complete; telemetry remains online"
            self.cooldown_until = 0
            self.telemetry.emit(
                "CAMPAIGN_COMPLETE",
                "Reviewed campaign complete; no FixIt, retry, provider call or cooldown required",
            )
            self.persist_health(force=True)
            return 0, runtime, True, None
        return exit_code, runtime, progressed, control


# final.enhanced.main() instantiates this module-global class.
final.enhanced.EnhancedWatchdog = CampaignWatchdog


def main() -> int:
    return int(final.enhanced.main())


if __name__ == "__main__":
    raise SystemExit(main())
