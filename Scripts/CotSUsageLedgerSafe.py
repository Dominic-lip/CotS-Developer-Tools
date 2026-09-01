#!/usr/bin/env python3
"""Cross-process safe adapters for the local provider usage ledger.

The watchdog is the preferred writer. The GUI may also refresh the ledger when
the watchdog is absent, but it must never double-consume protocol offsets or
block the UI behind a slow quota probe.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import CotSUsageLedger as base
from CotS24x7Common import COTS, read_json

LOCK_PATH = COTS / "provider-usage-ledger.lock"


class LedgerLease:
    def __init__(self, wait_seconds: float) -> None:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.touch(exist_ok=True)
        if LOCK_PATH.stat().st_size == 0:
            LOCK_PATH.write_text(" ", encoding="utf-8")
        self.file = LOCK_PATH.open("r+")
        self.acquired = False
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while True:
            try:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.acquired = True
                return
            except OSError:
                if time.monotonic() >= deadline:
                    self.file.close(); return
                time.sleep(0.05)

    def close(self) -> None:
        if not self.acquired or self.file.closed: return
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close(); self.acquired = False

    def __enter__(self) -> "LedgerLease": return self
    def __exit__(self, *_args: object) -> None: self.close()


class _SafeLedger(base.ProviderUsageLedger):
    def _reload_shared(self) -> None:
        value = read_json(base.STATE, self.data if isinstance(self.data, dict) else {})
        if not isinstance(value, dict): value = {}
        value.setdefault("schema_version", 3)
        value.setdefault("offsets", {})
        value.setdefault("codex", {})
        value.setdefault("claude", {})
        self.data = value


class LockedProviderUsageLedger(_SafeLedger):
    """Preferred watchdog writer: serialize offset advancement across processes."""
    def poll(self) -> bool:
        with LedgerLease(15.0) as lease:
            if not lease.acquired:
                self._reload_shared(); return False
            self._reload_shared()
            return super().poll()


class ReadMostlyProviderUsageLedger(_SafeLedger):
    """GUI adapter: never wait on a writer; fall back to its latest state."""
    def poll(self) -> bool:
        with LedgerLease(0.0) as lease:
            if not lease.acquired:
                self._reload_shared(); return False
            self._reload_shared()
            return super().poll()

    def snapshot(self) -> dict[str, Any]:
        self._reload_shared()
        return super().snapshot()


# Default safe adapter is the watchdog/writer form.
ProviderUsageLedger = LockedProviderUsageLedger


if __name__ == "__main__":
    ledger = LockedProviderUsageLedger(); ledger.poll(); import json; print(json.dumps(ledger.snapshot(), indent=2, default=str))
