#!/usr/bin/env python3
"""Local provider protocol ledger and quota view. Never invokes Codex or Claude turns."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from CotS24x7Common import COTS, atomic_json, read_json, safe_nonnegative_int
from CotSCodexQuotaProbe import probe_rate_limits

CODEX = COTS / "codex-protocol.log"
CLAUDE = COTS / "claude-protocol.log"
STATE = COTS / "provider-usage-ledger.local.json"
HISTORY = COTS / "telemetry" / "provider-usage-samples.jsonl"
DIRECT_PROBE_SECONDS = 60.0
CLOCK_RESET = re.compile(r"try again at\s+(\d{1,2}):(\d{2})\s*([AP]M)", re.I)
EPOCH_RESET = re.compile(r"(?:reset(?:s| at)?|try again at)\D{0,20}(\d{10}(?:\.\d+)?)", re.I)


def _number(mapping: object, *names: str) -> float | None:
    if not isinstance(mapping, dict): return None
    for name in names:
        value = mapping.get(name)
        if isinstance(value, bool): continue
        if isinstance(value, (int, float)): return float(value)
        if isinstance(value, str):
            try: return float(value.strip().rstrip("%"))
            except ValueError: pass
    return None


def _epoch(mapping: object, *names: str) -> float | None:
    value = _number(mapping, *names)
    if value is None: return None
    if value > 10_000_000_000: value /= 1000.0
    return value if value > 0 else None


def parse_reset_from_message(message: str, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    epoch = EPOCH_RESET.search(message or "")
    if epoch:
        try: return float(epoch.group(1))
        except ValueError: pass
    match = CLOCK_RESET.search(message or "")
    if not match: return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3).upper()
    if meridiem == "PM" and hour != 12: hour += 12
    if meridiem == "AM" and hour == 12: hour = 0
    local = time.localtime(now)
    candidate = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
    if candidate <= now: candidate += 24 * 3600
    return candidate


def _window_label(fallback: str, raw: object) -> str:
    minutes = _number(raw, "windowDurationMins", "windowMinutes", "window_minutes", "windowDurationMinutes")
    if minutes is not None:
        rounded = int(round(minutes))
        if rounded == 300: return "5-hour"
        if rounded == 10080: return "Weekly"
        if rounded % 1440 == 0: return f"{rounded//1440}-day"
        if rounded % 60 == 0: return f"{rounded//60}-hour"
        return f"{rounded}-minute"
    return fallback


def _normalize_window(label: str, raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw: return None
    used = _number(raw, "usedPercent", "used_percent", "percentUsed", "usagePercent", "usage_percent")
    remaining = _number(raw, "remainingPercent", "remaining_percent", "percentRemaining")
    limit = _number(raw, "limit", "total", "quota")
    remaining_units = _number(raw, "remaining", "remainingUnits", "remaining_units")
    if used is None and remaining is not None: used = 100.0 - remaining
    if used is None and limit and remaining_units is not None and limit > 0:
        used = 100.0 * (limit - remaining_units) / limit
    if used is not None: used = max(0.0, min(100.0, used))
    if remaining is None and used is not None: remaining = 100.0 - used
    reset = _epoch(raw, "resetAt", "resetsAt", "reset_at", "resetEpoch", "reset_epoch")
    window_minutes = _number(raw, "windowDurationMins", "windowMinutes", "window_minutes", "windowDurationMinutes")
    return {
        "label": _window_label(label, raw), "used_percent": used, "remaining_percent": remaining,
        "reset_at": reset, "window_minutes": window_minutes, "raw": raw,
    }


def format_reset(reset_at: float | None) -> str:
    if not isinstance(reset_at, (int, float)): return "Not reported"
    remaining = reset_at - time.time()
    clock = time.strftime("%Y-%m-%d %H:%M", time.localtime(reset_at))
    if remaining <= 0: return f"{clock} (due now)"
    hours, minutes = divmod(int(remaining // 60), 60)
    return f"{clock} (in {hours}h {minutes:02d}m)"


class ProviderUsageLedger:
    def __init__(self) -> None:
        self.data = read_json(STATE, {
            "schema_version": 3,
            "offsets": {},
            "codex": {"turns_started":0,"turns_completed":0,"turns_failed":0,"usage_limit_hits":0,"duration_ms":0},
            "claude": {"results":0,"errors":0,"num_turns":0,"duration_ms":0,"duration_api_ms":0,"reported_cost_usd":0.0},
        })
        self.data["schema_version"] = 3
        self.data.setdefault("offsets", {})
        self.data.setdefault("codex", {})
        self.data.setdefault("claude", {})
        self._last_sample_at = 0.0

    def _tail(self, path: Path, key: str):
        try:
            size = path.stat().st_size
            offset = safe_nonnegative_int(self.data["offsets"].get(key), 0)
            if offset > size: offset = 0
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(offset); lines = f.readlines(); self.data["offsets"][key] = f.tell()
            return lines
        except OSError:
            return []

    @staticmethod
    def _json_line(line: str) -> dict[str, Any] | None:
        text = line.strip()
        if text.startswith(("> ", "< ")): text = text[2:]
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    def _refresh_direct_quota(self) -> bool:
        now = time.time(); codex = self.data["codex"]
        shared = read_json(STATE); shared_codex = shared.get("codex") if isinstance(shared.get("codex"), dict) else {}
        shared_probe = shared_codex.get("last_direct_probe_at")
        local_probe = codex.get("last_direct_probe_at")
        if isinstance(shared_probe, (int, float)) and (not isinstance(local_probe, (int, float)) or shared_probe > local_probe):
            for key in ("last_direct_probe_at", "last_direct_probe_ok", "direct_probe_error", "last_rate_limits", "last_rate_limits_at", "last_rate_limits_source", "rate_limits_by_limit_id"):
                if key in shared_codex: codex[key] = shared_codex[key]
        last = codex.get("last_direct_probe_at")
        if isinstance(last, (int, float)) and now - last < DIRECT_PROBE_SECONDS: return False
        result = probe_rate_limits()
        codex["last_direct_probe_at"] = now; codex["last_direct_probe_ok"] = bool(result.get("ok"))
        if not result.get("ok"):
            codex["direct_probe_error"] = str(result.get("error") or "unknown quota probe error")[:1200]
            return True
        response = result.get("result") if isinstance(result.get("result"), dict) else {}
        by_id = response.get("rateLimitsByLimitId") if isinstance(response.get("rateLimitsByLimitId"), dict) else {}
        snapshot = by_id.get("codex") if isinstance(by_id.get("codex"), dict) else response.get("rateLimits")
        if isinstance(snapshot, dict):
            codex["last_rate_limits"] = snapshot; codex["last_rate_limits_at"] = now; codex["last_rate_limits_source"] = "account/rateLimits/read"
            codex["rate_limits_by_limit_id"] = by_id; codex.pop("direct_probe_error", None)
        else:
            codex["direct_probe_error"] = "account/rateLimits/read returned no Codex rate-limit snapshot"
        return True

    def poll(self) -> bool:
        changed = False
        codex = self.data["codex"]; claude = self.data["claude"]
        for line in self._tail(CODEX, "codex"):
            msg = self._json_line(line)
            if not msg: continue
            changed = True; method = msg.get("method")
            if method == "turn/start":
                codex["turns_started"] = safe_nonnegative_int(codex.get("turns_started")) + 1
            elif method == "turn/completed":
                turn = (msg.get("params") or {}).get("turn") or {}
                codex["turns_completed"] = safe_nonnegative_int(codex.get("turns_completed")) + 1
                if turn.get("status") == "failed": codex["turns_failed"] = safe_nonnegative_int(codex.get("turns_failed")) + 1
                if isinstance(turn.get("durationMs"), (int,float)): codex["duration_ms"] = safe_nonnegative_int(codex.get("duration_ms")) + int(turn["durationMs"])
            elif method == "error":
                error = (msg.get("params") or {}).get("error") or {}
                if error.get("codexErrorInfo") == "usageLimitExceeded":
                    codex["usage_limit_hits"] = safe_nonnegative_int(codex.get("usage_limit_hits")) + 1
                    codex["last_usage_limit_message"] = str(error.get("message") or "")[:1000]
                    codex["last_usage_limit_at"] = time.time()
                    parsed = parse_reset_from_message(codex["last_usage_limit_message"])
                    if parsed is not None: codex["last_usage_limit_reset_at"] = parsed
            elif method == "account/rateLimits/updated":
                codex["last_rate_limits"] = (msg.get("params") or {}).get("rateLimits") or {}
                emitted = msg.get("emittedAtMs")
                codex["last_rate_limits_at"] = (float(emitted)/1000.0) if isinstance(emitted,(int,float)) else time.time()
                codex["last_rate_limits_source"] = "account/rateLimits/updated"
            elif method in {"thread/tokenUsage/updated", "turn/tokenUsage/updated"}:
                payload = (msg.get("params") or {}).get("tokenUsage") or (msg.get("params") or {}).get("usage") or {}
                if isinstance(payload, dict): codex["last_token_usage"] = payload

        for line in self._tail(CLAUDE, "claude"):
            msg = self._json_line(line)
            if not msg or msg.get("type") != "result": continue
            changed = True
            claude["results"] = safe_nonnegative_int(claude.get("results")) + 1
            if msg.get("is_error"): claude["errors"] = safe_nonnegative_int(claude.get("errors")) + 1
            claude["num_turns"] = safe_nonnegative_int(claude.get("num_turns")) + safe_nonnegative_int(msg.get("num_turns"))
            for field in ("duration_ms", "duration_api_ms"):
                if isinstance(msg.get(field), (int,float)): claude[field] = safe_nonnegative_int(claude.get(field)) + int(msg[field])
            if isinstance(msg.get("total_cost_usd"), (int,float)):
                claude["reported_cost_usd"] = float(claude.get("reported_cost_usd") or 0) + float(msg["total_cost_usd"])
            if isinstance(msg.get("usage"), dict): claude["last_usage"] = msg["usage"]
            claude["last_result_at"] = time.time()
        try:
            if self._refresh_direct_quota(): changed = True
        except Exception as error:
            codex["direct_probe_error"] = f"quota probe failed safely: {error}"[:1200]; changed = True
        if changed:
            self.data["updated_at"] = time.time(); atomic_json(STATE, self.data)
        self._maybe_sample()
        return changed

    def codex_quota(self) -> dict[str, Any]:
        codex = self.data.get("codex") or {}; rates = codex.get("last_rate_limits") if isinstance(codex.get("last_rate_limits"), dict) else {}
        primary = _normalize_window("Primary", rates.get("primary")) if isinstance(rates, dict) else None
        secondary = _normalize_window("Secondary", rates.get("secondary")) if isinstance(rates, dict) else None
        windows = [item for item in (primary, secondary) if item]
        fallback_reset = codex.get("last_usage_limit_reset_at")
        message = str(codex.get("last_usage_limit_message") or "")
        if fallback_reset is None and message: fallback_reset = parse_reset_from_message(message)
        exhausted = bool(rates.get("rateLimitReachedType")) if isinstance(rates, dict) else False
        if not exhausted and codex.get("last_usage_limit_at"):
            exhausted = not windows or any(isinstance(w.get("used_percent"),(int,float)) and float(w["used_percent"]) >= 100 for w in windows)
        return {
            "windows": windows, "exhausted": exhausted,
            "fallback_reset_at": fallback_reset, "fallback_reset_text": format_reset(fallback_reset),
            "last_rate_limits_at": codex.get("last_rate_limits_at"), "last_rate_limits_source": codex.get("last_rate_limits_source"),
            "last_usage_limit_message": message, "credits": rates.get("credits") if isinstance(rates, dict) else None,
            "plan_type": rates.get("planType") if isinstance(rates, dict) else None, "direct_probe_error": codex.get("direct_probe_error"),
        }

    def _maybe_sample(self) -> None:
        now = time.time()
        if now - self._last_sample_at < 60: return
        self._last_sample_at = now
        quota = self.codex_quota(); codex = self.data.get("codex") or {}
        record = {
            "ts": now, "turns_started": safe_nonnegative_int(codex.get("turns_started")),
            "turns_completed": safe_nonnegative_int(codex.get("turns_completed")), "turns_failed": safe_nonnegative_int(codex.get("turns_failed")),
            "usage_limit_hits": safe_nonnegative_int(codex.get("usage_limit_hits")),
            "windows": [{"label": w.get("label"), "used_percent": w.get("used_percent"), "reset_at": w.get("reset_at")} for w in quota.get("windows", [])],
        }
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        try:
            with HISTORY.open("a", encoding="utf-8") as handle: handle.write(json.dumps(record, separators=(",", ":")) + "\n")
        except OSError: pass

    def history(self, hours: float = 24.0, limit: int = 500) -> list[dict[str, Any]]:
        cutoff = time.time() - max(1.0, hours) * 3600
        try:
            rows = []
            for line in HISTORY.read_text(encoding="utf-8", errors="replace").splitlines():
                try: value = json.loads(line)
                except json.JSONDecodeError: continue
                if isinstance(value, dict) and isinstance(value.get("ts"), (int,float)) and value["ts"] >= cutoff: rows.append(value)
            return rows[-limit:]
        except OSError: return []

    def snapshot(self) -> dict[str, Any]:
        return {**self.data, "codex_quota": self.codex_quota()}


if __name__ == "__main__":
    ledger = ProviderUsageLedger(); ledger.poll(); print(json.dumps(ledger.snapshot(), indent=2))
