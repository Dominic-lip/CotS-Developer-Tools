#!/usr/bin/env python3
"""Generation/process-bound single-mutator lease for CotS automation."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    from CotSProcess import identity_matches, process_identity
except ModuleNotFoundError:
    from Scripts.CotSProcess import identity_matches, process_identity


class LeaseError(RuntimeError):
    pass


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def read_lease(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def lease_is_live(lease: dict[str, Any]) -> bool:
    owner = lease.get("owner_process")
    return identity_matches(owner if isinstance(owner, dict) else None)


def current_owner(path: Path, *, reclaim_stale: bool = True) -> dict[str, Any]:
    lease = read_lease(path)
    if not lease:
        return {}
    if lease_is_live(lease):
        return lease
    if reclaim_stale:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return {}
    return lease


def acquire(
    path: Path,
    *,
    agent_id: str,
    owner_pid: int,
    generation: str,
    workspace_profile: str,
) -> dict[str, Any]:
    if not agent_id.strip():
        raise LeaseError("agent_id is required")
    identity = process_identity(owner_pid)
    if identity is None:
        raise LeaseError("owner process is not live")
    existing = current_owner(path)
    if existing and existing.get("agent_id") != agent_id:
        raise LeaseError(f"mutation lock held by {existing.get('agent_id')}")
    payload = {
        "schema_version": 2,
        "agent_id": agent_id,
        "generation": generation,
        "workspace_profile": workspace_profile,
        "acquired_at": time.time(),
        "owner_process": identity.to_json(),
    }
    _atomic_json(path, payload)
    return payload


def require(
    path: Path,
    *,
    agent_id: str,
    generation: str | None = None,
    workspace_profile: str | None = None,
) -> dict[str, Any]:
    lease = current_owner(path)
    if not lease:
        raise LeaseError("mutation lock is not held")
    if lease.get("agent_id") != agent_id:
        raise LeaseError("mutation lock not owned by caller")
    if generation is not None and lease.get("generation") != generation:
        raise LeaseError("mutation lock generation mismatch")
    if workspace_profile is not None and lease.get("workspace_profile") != workspace_profile:
        raise LeaseError("mutation lock workspace profile mismatch")
    return lease


def transfer(path: Path, *, agent_id: str, target_agent_id: str) -> dict[str, Any]:
    lease = require(path, agent_id=agent_id)
    lease = dict(lease)
    lease["agent_id"] = target_agent_id
    lease["transferred_from"] = agent_id
    lease["transferred_at"] = time.time()
    _atomic_json(path, lease)
    return lease


def release(path: Path, *, agent_id: str) -> None:
    require(path, agent_id=agent_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
