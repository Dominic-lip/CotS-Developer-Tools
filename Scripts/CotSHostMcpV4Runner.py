#!/usr/bin/env python3
"""Runtime entry point that binds V4 Host MCP leases to the owning Factory."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import CotSHostMcpV4 as host

FACTORY_PID = int(os.environ.get("COTS_FACTORY_PID") or os.getppid())
FACTORY_GENERATION = os.environ.get("COTS_FACTORY_GENERATION") or f"factory-{FACTORY_PID}"

_original_acquire = host.acquire
_original_status = host.get_status


def acquire(arguments: dict[str, Any]) -> dict[str, Any]:
    value = dict(arguments)
    value.setdefault("owner_pid", FACTORY_PID)
    value.setdefault("generation", FACTORY_GENERATION)
    return _original_acquire(value)


def get_status(arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _original_status(arguments)
    data = payload.setdefault("data", {})
    if isinstance(data, dict):
        data["factory_pid"] = FACTORY_PID
        data["factory_generation"] = FACTORY_GENERATION
    return payload


host.acquire = acquire
host.get_status = get_status

# Preserve the public tool names while making owner_pid/generation optional to
# clients: the trusted Factory supplies them out-of-band to the Host process.
description, _schema, _handler = host.TOOLS["AcquireMutationLock"]
host.TOOLS["AcquireMutationLock"] = (
    description,
    host.schema(
        {
            "agent_id": host.AGENT,
            "owner_pid": {"type": "integer", "minimum": 1},
            "generation": host.AGENT,
        },
        ["agent_id"],
    ),
    acquire,
)
status_description, status_schema, _ = host.TOOLS["GetWorkspaceStatus"]
host.TOOLS["GetWorkspaceStatus"] = (status_description, status_schema, get_status)


if __name__ == "__main__":
    raise SystemExit(host.main())
