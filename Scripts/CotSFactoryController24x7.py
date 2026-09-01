#!/usr/bin/env python3
"""24x7 containment wrapper for the reviewed CotS Factory Controller."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

import CotSFactoryController as base
from CotS24x7Common import DailyTelemetry, safe_nonnegative_int
from CotSRecovery import RECOVERABLE_EXIT, IncidentCategory, write_incident

SCRIPTS = Path(__file__).resolve().parent
telemetry = DailyTelemetry()
_original_read_json = base.read_json


def hardened_read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    value = _original_read_json(path, default)
    if path == base.STATE_PATH:
        attempts = value.get("repair_attempts")
        if not isinstance(attempts, dict):
            attempts = {}
        value["repair_attempts"] = {str(k): safe_nonnegative_int(v, 0) for k, v in attempts.items()}
        events = value.get("recent_events")
        value["recent_events"] = list(events)[-10:] if isinstance(events, list) else []
        for field in ("started_at", "updated_at", "supervisor_started_at"):
            if value.get(field) is not None and not isinstance(value[field], (int, float)):
                value.pop(field, None)
    return value


def install_hardening() -> None:
    base.SUPERVISOR_SCRIPT = SCRIPTS / "CotSAgentSupervisor24x7.py"
    base.read_json = hardened_read_json


def main() -> int:
    install_hardening()
    telemetry.emit("FACTORY_START", "24x7 Factory Controller starting")
    try:
        code = int(base.main())
        telemetry.emit("FACTORY_EXIT", f"Factory Controller exited with code {code}", exit_code=code)
        return code
    except KeyboardInterrupt:
        telemetry.emit("FACTORY_STOP", "Factory Controller received keyboard interrupt")
        return 130
    except BaseException as error:
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-12000:]
        telemetry.emit("FACTORY_CRASH", f"{type(error).__name__}: {error}", traceback=trace)
        try:
            write_incident(
                IncidentCategory.FACTORY_CONTROLLER,
                f"Unhandled Factory Controller exception: {type(error).__name__}: {error}",
                affected_component="factory",
                error_code="FACTORY_UNHANDLED_EXCEPTION",
            )
        except Exception:
            pass
        print(trace, file=sys.stderr)
        return RECOVERABLE_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
