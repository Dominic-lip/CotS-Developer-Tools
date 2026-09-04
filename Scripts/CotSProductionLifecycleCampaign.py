#!/usr/bin/env python3
"""Campaign authorization wrapper for the fixed CotS production lifecycle."""
from __future__ import annotations

import CotSProductionLifecycle as base

CAMPAIGN_LAST_TASK = 121


def install_campaign() -> None:
    base.ALLOWED_TASKS = {"TASK-015", *(f"TASK-{n}" for n in range(100, CAMPAIGN_LAST_TASK + 1))}


def main() -> int:
    install_campaign()
    return int(base.main())


if __name__ == "__main__":
    raise SystemExit(main())
