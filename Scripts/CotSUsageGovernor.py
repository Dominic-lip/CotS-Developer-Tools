#!/usr/bin/env python3
"""Canonical V4 usage/context/evidence normalization for CotS automation.

The provider may report counts as scalars or collections.  This module never
casts arbitrary containers to ``int`` and never treats arbitrary non-empty
strings as booleans.  Provider plan allowance remains UNKNOWN unless an
explicit provider field reports it.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any

CONTEXT_ROTATE_INPUT_TOKENS = 60_000
CONTEXT_CRITICAL_INPUT_TOKENS = 90_000
CONTEXT_ROTATE_RATIO = 0.50
CONTEXT_CRITICAL_RATIO = 0.65


def evidence_count(value: Any) -> int:
    """Conservatively normalize explicit evidence into a non-negative count."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value)) if value.is_integer() else 0
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
        return 0
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if isinstance(value, dict):
        explicit = value.get("count")
        if isinstance(explicit, (int, float, str)) and not isinstance(explicit, bool):
            return evidence_count(explicit)
        for key in ("items", "paths", "tests", "reads", "results"):
            nested = value.get(key)
            if isinstance(nested, (list, tuple, set)):
                return len(nested)
        return 0
    return 0


def strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0", ""}:
            return False
    return False


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value >= 0:
        return int(value)
    return None


@dataclass(frozen=True)
class UsageSample:
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    context_window: int | None = None
    plan_used_percent: float | None = None
    reset_at: float | None = None
    source: str = "unknown"

    @property
    def total_tokens(self) -> int | None:
        values = [self.input_tokens, self.output_tokens]
        return sum(value for value in values if value is not None) if any(value is not None for value in values) else None

    @property
    def context_ratio(self) -> float | None:
        if self.input_tokens is None or not self.context_window:
            return None
        return self.input_tokens / self.context_window

    @property
    def context_health(self) -> str:
        ratio = self.context_ratio
        if self.input_tokens is not None and self.input_tokens >= CONTEXT_CRITICAL_INPUT_TOKENS:
            return "CRITICAL"
        if ratio is not None and ratio >= CONTEXT_CRITICAL_RATIO:
            return "CRITICAL"
        if self.input_tokens is not None and self.input_tokens >= CONTEXT_ROTATE_INPUT_TOKENS:
            return "ROTATE"
        if ratio is not None and ratio >= CONTEXT_ROTATE_RATIO:
            return "ROTATE"
        return "HEALTHY" if self.input_tokens is not None else "UNKNOWN"

    @property
    def rotation_required(self) -> bool:
        return self.context_health in {"ROTATE", "CRITICAL"}


def parse_codex_usage(payload: dict[str, Any]) -> UsageSample | None:
    """Parse only known Codex usage shapes; never recursively hunt arbitrary keys."""
    if not isinstance(payload, dict):
        return None
    candidates: list[dict[str, Any]] = []
    for key in ("tokenUsage", "token_usage", "usage", "lastTurnUsage"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(payload)
    for data in candidates:
        input_tokens = _number(data.get("inputTokens"))
        if input_tokens is None:
            input_tokens = _number(data.get("input_tokens"))
        cached = _number(data.get("cachedInputTokens"))
        if cached is None:
            cached = _number(data.get("cached_input_tokens"))
        output = _number(data.get("outputTokens"))
        if output is None:
            output = _number(data.get("output_tokens"))
        window = _number(data.get("modelContextWindow"))
        if window is None:
            window = _number(data.get("context_window"))
        if any(value is not None for value in (input_tokens, cached, output, window)):
            return UsageSample(
                input_tokens=input_tokens,
                cached_input_tokens=cached,
                output_tokens=output,
                context_window=window,
                source="codex",
            )
    return None


def parse_explicit_plan_allowance(payload: dict[str, Any], sample: UsageSample | None = None) -> UsageSample:
    """Attach plan percentage only from explicit allowance/rate-limit fields."""
    base = sample or UsageSample()
    if not isinstance(payload, dict):
        return base
    percent: float | None = None
    reset: float | None = None
    for key in ("planUsedPercent", "allowanceUsedPercent", "usagePercent"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= float(value) <= 100:
            percent = float(value)
            break
    for key in ("resetAtEpochSeconds", "resetsAtEpochSeconds"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            reset = float(value)
            break
    return UsageSample(
        input_tokens=base.input_tokens,
        cached_input_tokens=base.cached_input_tokens,
        output_tokens=base.output_tokens,
        context_window=base.context_window,
        plan_used_percent=percent,
        reset_at=reset,
        source=base.source,
    )


class UsageGovernor:
    """Small durable engineering-turn scorer used by V4 control-plane code."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)

    def record_turn(self, *, task_id: str | None, provider: str, emitted: dict[str, Any], infrastructure_failure: bool = False) -> dict[str, Any]:
        targeted = evidence_count(emitted.get("targeted_tests_this_turn"))
        full_suites = evidence_count(emitted.get("full_suites_this_turn"))
        cached_reads = evidence_count(emitted.get("cached_reads_reused_this_turn"))
        activity = evidence_count(emitted.get("activity_count"))
        live_validation = strict_bool(emitted.get("live_validation_this_turn"))
        productive = not infrastructure_failure and any((targeted, full_suites, activity, live_validation))
        record = {
            "recorded_at": time.time(),
            "task_id": task_id,
            "provider": provider,
            "targeted_tests": targeted,
            "full_suites": full_suites,
            "cached_reads_reused": cached_reads,
            "activity_count": activity,
            "live_validation": live_validation,
            "infrastructure_failure": infrastructure_failure,
            "productive": productive,
        }
        history = list(self.state.get("turns") or [])
        history.append(record)
        self.state["turns"] = history[-200:]
        self.state["zero_delta_turns"] = sum(1 for item in self.state["turns"] if not item.get("productive") and not item.get("infrastructure_failure"))
        self.state["infrastructure_failures"] = sum(1 for item in self.state["turns"] if item.get("infrastructure_failure"))
        self._save()
        return record
