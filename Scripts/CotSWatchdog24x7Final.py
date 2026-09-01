#!/usr/bin/env python3
"""Production entry point for the enhanced CotS 24x7 watchdog."""
from __future__ import annotations

import time

import CotSWatchdog24x7Enhanced as enhanced
from CotSUsageLedgerSafe import LockedProviderUsageLedger

# EnhancedWatchdog resolves this module global when it constructs the ledger.
enhanced.ProviderUsageLedger = LockedProviderUsageLedger


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


# enhanced.main() instantiates its module-global EnhancedWatchdog class.
enhanced.EnhancedWatchdog = ProductionWatchdog

if __name__ == "__main__":
    raise SystemExit(enhanced.main())
