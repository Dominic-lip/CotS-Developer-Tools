#!/usr/bin/env python3
"""Create a redacted CotS support bundle without using an AI provider."""
from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

from CotS24x7Common import COTS, FACTORY_STATE, HEALTH_PATH, SUPERVISOR_STATE, TELEMETRY_DIR, fixed_git, read_json

SUPPORT_DIR = COTS / "support"
INCIDENTS_DIR = COTS / "incidents"
EXTRA_STATES = {
    "provider-usage.json": COTS / "provider-usage-ledger.local.json",
    "productivity-governor.json": COTS / "productivity-governor.local.json",
    "hardware.json": COTS / "hardware-telemetry.local.json",
    "rollback-guard.json": COTS / "rollback-guard.local.json",
    "notifications.json": COTS / "notification-state.local.json",
    "chaos-last-result.json": COTS / "chaos-last-result.local.json",
}


def _safe_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def _redacted_state(path: Path) -> dict:
    value = read_json(path)
    for provider in ("codex", "claude"):
        info = value.get(provider)
        if isinstance(info, dict):
            info = dict(info)
            for key in ("thread_id", "session_id"):
                if key in info: info[key] = "<redacted>"
            value[provider] = info
    ownership = value.get("provider_ownership")
    if isinstance(ownership, dict):
        ownership = dict(ownership)
        if "session_id" in ownership: ownership["session_id"] = "<redacted>"
        value["provider_ownership"] = ownership
    return value


def _write_tail(archive: zipfile.ZipFile, source: Path, name: str, limit: int = 2_000_000) -> None:
    try:
        data = source.read_bytes()
        archive.writestr(name, data[-limit:])
    except OSError:
        pass


def create_support_bundle() -> Path:
    SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = SUPPORT_DIR / f"CotS-support-{stamp}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("state/watchdog.json", _safe_json_bytes(read_json(HEALTH_PATH)))
        archive.writestr("state/factory.json", _safe_json_bytes(_redacted_state(FACTORY_STATE)))
        archive.writestr("state/supervisor.json", _safe_json_bytes(_redacted_state(SUPERVISOR_STATE)))
        for name, path in EXTRA_STATES.items():
            if path.exists(): archive.writestr(f"state/{name}", _safe_json_bytes(read_json(path)))
        archive.writestr("git/head.txt", fixed_git("rev-parse", "HEAD") + "\n")
        archive.writestr("git/status.txt", fixed_git("status", "--porcelain=v1") + "\n")
        archive.writestr("git/last-commit.txt", fixed_git("log", "-1", "--format=%h %s") + "\n")
        if TELEMETRY_DIR.exists():
            for path in sorted(TELEMETRY_DIR.glob("*"))[-20:]:
                if path.is_file() and path.suffix in {".log", ".jsonl", ".md"}:
                    _write_tail(archive, path, f"telemetry/{path.name}")
        metrics = COTS / "operational-metrics.jsonl"
        if metrics.exists(): _write_tail(archive, metrics, "telemetry/operational-metrics.jsonl")
        if INCIDENTS_DIR.exists():
            incidents = sorted(INCIDENTS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)[-20:]
            for path in incidents:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        for key in list(value):
                            if any(term in key.lower() for term in ("token", "secret", "authorization", "password")):
                                value[key] = "<redacted>"
                    archive.writestr(f"incidents/{path.name}", _safe_json_bytes(value))
                except Exception: pass
        archive.writestr("README.txt", (
            "CotS support bundle generated locally.\n"
            "Included: watchdog/factory/supervisor state, quota ledger, productivity governor, hardware state, rollback/chaos state, recent local logs and git status.\n"
            "Excluded: telemetry control token, raw Codex/Claude protocol logs, credentials and caches.\n"
            "Upload this ZIP when remote diagnosis is needed.\n"
        ).encode("utf-8"))
    return target


if __name__ == "__main__": print(create_support_bundle())
