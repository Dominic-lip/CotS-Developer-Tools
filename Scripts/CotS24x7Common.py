#!/usr/bin/env python3
"""Zero-provider-cost telemetry, normalization and control helpers for CotS 24x7."""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parent.parent
COTS = REPO / ".cots"
TELEMETRY_DIR = COTS / "telemetry"
HEALTH_PATH = COTS / "watchdog-24x7.local.json"
CONTROL_PATH = COTS / "control-24x7.local.json"
TOKEN_PATH = COTS / "telemetry-token.local.txt"
SUPERVISOR_STATE = COTS / "agent-supervisor.local.json"
FACTORY_STATE = COTS / "factory-controller.local.json"
STOP_FILE = COTS / "STOP_AUTONOMOUS"
EVENTS_LOG = COTS / "supervisor-events.log"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

INT_CONTEXT_FIELDS = {"targeted_tests_run", "full_suites_run"}
LIST_CONTEXT_FIELDS = {
    "acceptance_remaining", "decisions_made", "files_changed", "files_relevant",
    "commands_tests_already_run", "validation_passed", "next_actions", "donor_decisions",
    "read_fingerprints",
}
STRING_CONTEXT_FIELDS = {
    "task_id", "task_title", "phase", "objective", "current_blocker",
    "commit_head", "lease_state", "reason_for_full_suite",
}
KNOWN_CONTEXT_FIELDS = INT_CONTEXT_FIELDS | LIST_CONTEXT_FIELDS | STRING_CONTEXT_FIELDS


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else dict(default or {})
    except (OSError, json.JSONDecodeError, TypeError):
        return dict(default or {})


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for attempt in range(8):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.05 * (attempt + 1))


def clean_text(value: object, limit: int = 800) -> str:
    text = " ".join(ANSI_RE.sub("", str(value or "")).replace("\r", " ").replace("\n", " ").split())
    return text[:limit]


def safe_nonnegative_int(value: object, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    if isinstance(value, str):
        candidate = value.strip()
        if re.fullmatch(r"[+-]?\d+", candidate):
            return max(0, int(candidate))
    return max(0, int(fallback or 0))


def _safe_list(value: object, *, limit: int = 12) -> list[Any]:
    if not isinstance(value, list):
        return []
    result: list[Any] = []
    for item in value[:limit]:
        if isinstance(item, dict):
            result.append({clean_text(k, 80): sanitize_scalar(v) for k, v in list(item.items())[:12]})
        else:
            result.append(sanitize_scalar(item))
    return result


def sanitize_scalar(value: object) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:600]
    if isinstance(value, list):
        return _safe_list(value)
    if isinstance(value, dict):
        return {clean_text(k, 80): sanitize_scalar(v) for k, v in list(value.items())[:12]}
    return clean_text(value, 600)


def sanitize_context(raw: object, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strictly normalize provider-supplied SUPERVISOR_CONTEXT.

    Malformed telemetry is ignored/repaired locally; it must never crash the
    autonomous supervisor or spend another model turn merely to repair telemetry.
    """
    previous = previous if isinstance(previous, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    out: dict[str, Any] = {}
    for field in KNOWN_CONTEXT_FIELDS:
        incoming = raw.get(field, previous.get(field))
        if field in INT_CONTEXT_FIELDS:
            out[field] = safe_nonnegative_int(incoming, safe_nonnegative_int(previous.get(field), 0))
        elif field in LIST_CONTEXT_FIELDS:
            if isinstance(incoming, list):
                out[field] = _safe_list(incoming)
            elif isinstance(previous.get(field), list):
                out[field] = _safe_list(previous[field])
            else:
                out[field] = []
        elif incoming is not None:
            out[field] = clean_text(incoming, 600)
    fps = []
    for item in out.get("read_fingerprints", []):
        if isinstance(item, dict):
            fps.append(item)
    out["read_fingerprints"] = fps
    return out


def fixed_git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=REPO, text=True, capture_output=True,
                                timeout=20, check=False)
        return (result.stdout + result.stderr).strip()[-12000:]
    except Exception as error:
        return f"unavailable: {error}"


def progress_signature() -> dict[str, Any]:
    supervisor = read_json(SUPERVISOR_STATE)
    return {
        "head": fixed_git("rev-parse", "HEAD"),
        "task": supervisor.get("task"),
        "phase": supervisor.get("phase"),
        "turn_count": safe_nonnegative_int(supervisor.get("turn_count"), 0),
        "last_successful_gate": supervisor.get("last_successful_gate"),
    }


def meaningful_progress(before: dict[str, Any], after: dict[str, Any]) -> bool:
    if before.get("head") and after.get("head") and before["head"] != after["head"]:
        return True
    if safe_nonnegative_int(after.get("turn_count")) > safe_nonnegative_int(before.get("turn_count")):
        return True
    if after.get("last_successful_gate") and after.get("last_successful_gate") != before.get("last_successful_gate"):
        return True
    if after.get("task") and (after.get("task"), after.get("phase")) != (before.get("task"), before.get("phase")):
        return True
    return False


class DailyTelemetry:
    """Local-only telemetry. No model/provider calls are made here."""
    def __init__(self) -> None:
        self.lock = threading.RLock()
        TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _paths(ts: float | None = None) -> tuple[Path, Path]:
        stamp = time.localtime(ts or time.time())
        day = time.strftime("%Y-%m-%d", stamp)
        return TELEMETRY_DIR / f"{day}.log", TELEMETRY_DIR / f"{day}.jsonl"

    def emit(self, kind: str, message: str, **fields: Any) -> None:
        now = time.time()
        log_path, jsonl_path = self._paths(now)
        record = {
            "ts": now, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "kind": clean_text(kind, 80), "message": clean_text(message, 1200),
            **{clean_text(k, 80): sanitize_scalar(v) for k, v in fields.items()},
        }
        summary = f"[{record['time']}] {record['kind']}: {record['message']}"
        with self.lock:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(summary + "\n")
            with jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")

    def list_days(self) -> list[str]:
        return sorted((p.stem for p in TELEMETRY_DIR.glob("????-??-??.log")), reverse=True)

    def read_day(self, day: str, limit_bytes: int = 2_000_000) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            return ""
        path = TELEMETRY_DIR / f"{day}.log"
        try:
            data = path.read_bytes()
            if len(data) > limit_bytes:
                data = data[-limit_bytes:]
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""


def ensure_control_token() -> str:
    COTS.mkdir(parents=True, exist_ok=True)
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token


def write_control(action: str, **fields: Any) -> None:
    atomic_json(CONTROL_PATH, {"action": action, "requested_at": time.time(), **fields})


def consume_control() -> dict[str, Any]:
    value = read_json(CONTROL_PATH)
    if not value:
        return {}
    try:
        CONTROL_PATH.unlink()
    except OSError:
        pass
    return value


def snapshot_health(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    supervisor = read_json(SUPERVISOR_STATE)
    factory = read_json(FACTORY_STATE)
    result = {
        "time": time.time(),
        "watchdog": read_json(HEALTH_PATH),
        "factory": factory,
        "supervisor": supervisor,
        "git": {
            "head": fixed_git("rev-parse", "--short", "HEAD"),
            "branch": fixed_git("rev-parse", "--abbrev-ref", "HEAD"),
            "status": fixed_git("status", "--porcelain=v1"),
        },
    }
    if extra:
        result.update(extra)
    return result


class EventTailer:
    """Tails the existing supervisor event log and mirrors only concise lines."""
    def __init__(self, telemetry: DailyTelemetry) -> None:
        self.telemetry = telemetry
        self.offset = 0
        self.identity: tuple[int, int] | None = None

    def poll(self) -> None:
        try:
            stat = EVENTS_LOG.stat()
            ident = (getattr(stat, "st_ino", 0), stat.st_size)
            if self.identity is None:
                self.offset = stat.st_size
            elif stat.st_size < self.offset:
                self.offset = 0
            self.identity = ident
            with EVENTS_LOG.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self.offset)
                for line in handle:
                    text = clean_text(line, 1000)
                    if text:
                        self.telemetry.emit("SUPERVISOR", text)
                self.offset = handle.tell()
        except OSError:
            return
