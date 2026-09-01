#!/usr/bin/env python3
"""Production entry point for the enhanced CotS 24x7 Control Center."""
from __future__ import annotations

import CotSControlCenter24x7Enhanced as enhanced
from CotSUsageLedgerSafe import ReadMostlyProviderUsageLedger

# The GUI never waits behind the watchdog's writer lease. If the watchdog is
# polling quota, the UI displays the latest persisted snapshot instead.
enhanced.ProviderUsageLedger = ReadMostlyProviderUsageLedger

if __name__ == "__main__":
    enhanced.ControlCenter().mainloop()
