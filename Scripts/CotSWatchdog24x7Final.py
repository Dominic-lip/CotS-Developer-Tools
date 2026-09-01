#!/usr/bin/env python3
"""Production entry point for the enhanced CotS 24x7 watchdog."""
from __future__ import annotations

import CotSWatchdog24x7Enhanced as enhanced
from CotSUsageLedgerSafe import LockedProviderUsageLedger

# EnhancedWatchdog resolves this module global when it constructs the ledger.
enhanced.ProviderUsageLedger = LockedProviderUsageLedger

if __name__ == "__main__":
    raise SystemExit(enhanced.main())
