#!/usr/bin/env python3
"""Canonical operator Control Center for the active production campaign.

The mature UI implementation remains in the versioned module during the staged
consolidation, but every operator-facing launch and fallback enters here.  Keep
the campaign watchdog target explicit: a dead telemetry listener must never
silently revive an older scheduler universe.
"""
from __future__ import annotations

import CotSControlCenter24x7Final as implementation

implementation.enhanced.WATCHDOG = implementation.enhanced.SCRIPTS / "CotSWatchdogCampaign.py"

ProductionControlCenter = implementation.ProductionControlCenter


def main() -> int:
    ProductionControlCenter().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
