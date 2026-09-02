#!/usr/bin/env python3
"""Safe chaos/regression runner for the CotS 24x7 control plane.

This runner never disables the real network and never kills an unrelated live
process. It executes deterministic simulations for child-process death,
malformed provider output, quota exhaustion, watchdog restart semantics, local
hardware/governor gates, identical-gate circuit breaking, and the fixed
production lifecycle boundary. Live destructive chaos remains behind an
explicit maintenance-mode boundary.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from CotS24x7Common import COTS, atomic_json

REPO = Path(__file__).resolve().parent.parent
RESULT = COTS / "chaos-last-result.local.json"
TESTS = (
    "Scripts.tests.test_cots_24x7",
    "Scripts.tests.test_cots_24x7_enhanced",
    "Scripts.tests.test_loop_guard",
    "Scripts.tests.test_production_lifecycle",
)


def run() -> dict:
    started = time.time()
    command = [sys.executable, "-m", "unittest", *TESTS, "-v"]
    process = subprocess.run(command, cwd=REPO, text=True, capture_output=True, timeout=180, check=False)
    value = {
        "started_at": started, "completed_at": time.time(), "passed": process.returncode == 0,
        "exit_code": process.returncode, "stdout": process.stdout[-20000:], "stderr": process.stderr[-10000:],
        "scope": [
            "provider malformed telemetry", "provider quota/reset parsing", "four-turn productivity trip",
            "hardware safety gates", "child-process death classification", "local telemetry survival",
            "rollback canary primitives", "watchdog false-human-gate recovery",
            "identical-gate cross-generation circuit breaker", "fixed production lifecycle boundary",
        ],
        "live_network_disruption": False, "unrelated_process_kills": False,
    }
    atomic_json(RESULT, value)
    return value


if __name__ == "__main__":
    outcome = run(); print(json.dumps(outcome, indent=2)); raise SystemExit(0 if outcome["passed"] else 1)
