#!/usr/bin/env python3
"""Production entry point for the enhanced CotS 24x7 watchdog."""
from __future__ import annotations

import time

import CotSWatchdog24x7Enhanced as enhanced
from CotSProcessLiveness import process_live
from CotSUsageLedgerSafe import LockedProviderUsageLedger

# EnhancedWatchdog resolves this module global when it constructs the ledger.
enhanced.ProviderUsageLedger = LockedProviderUsageLedger
# Base watchdog cleanup must never use os.kill(pid, 0) as a Windows liveness
# probe. A stale/racing supervisor PID previously raised SystemError and killed
# the entire outer watchdog immediately after successful local governor recovery.
enhanced.base._pid_live = process_live


class ProductionWatchdog(enhanced.EnhancedWatchdog):
    """Keep zero-cost telemetry alive even while autonomy is deliberately idle."""
    def wait_with_telemetry(self, seconds: float, state: str, action: str) -> str | None:
        self.state, self.current_action = state, action
        end = time.time() + max(0, seconds)
        self.cooldown_until = end
        self.persist_health(force=True)
        while not self.stop_event.is_set() and time.time() < end:
            self.tailer.poll()
            self.log_state_transition()
            self._poll_local()
            control = self.process_control()
            if control:
                return control
            self.persist_health()
            self.stop_event.wait(min(enhanced.base.POLL_SECONDS, max(0.05, end - time.time())))
        return None

    def maybe_run_fixit(self) -> None:
        """Ask local analysis whether an expensive cloud repair turn is useful."""
        if self.no_progress_streak < enhanced.base.FIXIT_TRIGGER_STREAK:
            return
        analysis = self._run_local_diagnosis("repeated no-progress factory failures before cloud FixIt")
        if analysis.get("cloud_wake_recommended") is False:
            self.telemetry.emit(
                "FIXIT_SKIPPED_LOCAL_AI",
                "Local diagnosis says a cloud repair turn is not useful yet; keeping recovery local",
                analysis=analysis,
            )
            return
        super().maybe_run_fixit()


# enhanced.main() instantiates its module-global EnhancedWatchdog class.
enhanced.EnhancedWatchdog = ProductionWatchdog

if __name__ == "__main__":
    raise SystemExit(enhanced.main())
