#!/usr/bin/env python3
"""Local provider protocol ledger. Never invokes Codex or Claude."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from CotS24x7Common import COTS, atomic_json, read_json, safe_nonnegative_int

CODEX = COTS / "codex-protocol.log"
CLAUDE = COTS / "claude-protocol.log"
STATE = COTS / "provider-usage-ledger.local.json"


class ProviderUsageLedger:
    def __init__(self) -> None:
        self.data = read_json(STATE, {
            "schema_version": 1,
            "offsets": {},
            "codex": {"turns_started":0,"turns_completed":0,"turns_failed":0,"usage_limit_hits":0,"duration_ms":0},
            "claude": {"results":0,"errors":0,"num_turns":0,"duration_ms":0,"duration_api_ms":0,"reported_cost_usd":0.0},
        })
        self.data.setdefault("offsets", {})
        self.data.setdefault("codex", {})
        self.data.setdefault("claude", {})

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
            elif method == "account/rateLimits/updated":
                codex["last_rate_limits"] = (msg.get("params") or {}).get("rateLimits") or {}
                emitted = msg.get("emittedAtMs")
                codex["last_rate_limits_at"] = (float(emitted)/1000.0) if isinstance(emitted,(int,float)) else time.time()

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
            claude["last_result_at"] = time.time()
        if changed:
            self.data["updated_at"] = time.time(); atomic_json(STATE, self.data)
        return changed

    def snapshot(self) -> dict[str, Any]:
        return dict(self.data)


if __name__ == "__main__":
    ledger = ProviderUsageLedger(); ledger.poll(); print(json.dumps(ledger.snapshot(), indent=2))
