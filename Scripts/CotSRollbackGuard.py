#!/usr/bin/env python3
"""Non-destructive rollback guard for CotS autonomous runtime tooling.

Before each factory generation, the watchdog snapshots only the small set of
24x7 runtime files. If those files change and fail a local canary after the
generation exits, the exact pre-generation copies are restored. No git reset,
clean, force checkout or history rewrite is used.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, atomic_json

REPO = Path(__file__).resolve().parent.parent
STATE = COTS / "rollback-guard.local.json"
SNAPSHOT_ROOT = COTS / "rollback-snapshots"
MANAGED_FILES = (
    "Scripts/CotS24x7Common.py",
    "Scripts/CotSAgentSupervisor24x7.py",
    "Scripts/CotSFactoryController24x7.py",
    "Scripts/CotSWatchdog24x7.py",
    "Scripts/CotSWatchdog24x7Enhanced.py",
    "Scripts/CotSControlCenter24x7.py",
    "Scripts/CotSControlCenter24x7Enhanced.py",
    "Scripts/CotSUsageLedger.py",
    "Scripts/CotSCodexQuotaProbe.py",
    "Scripts/CotSProductivityGovernor.py",
    "Scripts/CotSHardwareTelemetry.py",
    "Scripts/CotSLocalAI.py",
    "Scripts/CotSRollbackGuard.py",
    "Scripts/CotSNotifications.py",
    "Scripts/CotSOperationalMetrics.py",
    "Scripts/CotSChaosRunner.py",
    "Scripts/CotSSupportBundle.py",
)


def _hash(path: Path) -> str | None:
    try: return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError: return None


def current_hashes() -> dict[str, str | None]:
    return {relative: _hash(REPO / relative) for relative in MANAGED_FILES}


class RollbackGuard:
    def __init__(self) -> None:
        SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        self.active: dict[str, Any] | None = None

    def prepare_generation(self, generation: int) -> dict[str, Any]:
        stamp = f"g{generation:05d}-{int(time.time())}"
        folder = SNAPSHOT_ROOT / stamp; folder.mkdir(parents=True, exist_ok=False)
        hashes = current_hashes(); copied: list[str] = []
        for relative in MANAGED_FILES:
            source = REPO / relative
            if not source.exists(): continue
            destination = folder / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination); copied.append(relative)
        self.active = {"generation": generation, "snapshot": str(folder), "hashes": hashes, "copied": copied, "created_at": time.time()}
        atomic_json(STATE, {**self.active, "state": "ARMED"}); self._prune(); return dict(self.active)

    def changed_files(self) -> list[str]:
        if not self.active: return []
        now = current_hashes(); before = self.active.get("hashes") or {}
        return [relative for relative in MANAGED_FILES if now.get(relative) != before.get(relative)]

    def run_canary(self, timeout: int = 120) -> tuple[bool, str]:
        changed = self.changed_files()
        if not changed: return True, "runtime unchanged"
        existing = [str(REPO / path) for path in MANAGED_FILES if (REPO / path).exists()]
        compile_result = subprocess.run([sys.executable, "-m", "py_compile", *existing], cwd=REPO,
                                        text=True, capture_output=True, timeout=min(timeout, 45), check=False)
        if compile_result.returncode != 0:
            return False, (compile_result.stdout + compile_result.stderr)[-5000:]
        try:
            test_result = subprocess.run([
                sys.executable, "-m", "unittest",
                "Scripts.tests.test_cots_24x7", "Scripts.tests.test_cots_24x7_enhanced", "-q",
            ], cwd=REPO, text=True, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return False, "24x7 canary tests timed out"
        if test_result.returncode != 0:
            return False, (test_result.stdout + test_result.stderr)[-5000:]
        return True, f"canary passed for {len(changed)} changed runtime file(s)"

    def restore(self, reason: str) -> list[str]:
        if not self.active: return []
        folder = Path(str(self.active["snapshot"])); restored: list[str] = []
        for relative in self.active.get("copied") or []:
            source = folder / relative; destination = REPO / relative
            if not source.exists(): continue
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination); restored.append(relative)
        atomic_json(STATE, {**self.active, "state": "ROLLED_BACK", "reason": reason, "restored": restored, "rolled_back_at": time.time()})
        return restored

    def promote(self, note: str) -> None:
        if not self.active: return
        atomic_json(STATE, {**self.active, "state": "PROMOTED", "note": note, "promoted_at": time.time(), "new_hashes": current_hashes()})

    def _prune(self, keep: int = 8) -> None:
        folders = sorted((p for p in SNAPSHOT_ROOT.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
        for folder in folders[keep:]:
            try: shutil.rmtree(folder)
            except OSError: pass


if __name__ == "__main__":
    guard = RollbackGuard(); guard.prepare_generation(0); ok, detail = guard.run_canary(); print(json.dumps({"ok": ok, "detail": detail, "changed": guard.changed_files()}, indent=2))
