#!/usr/bin/env python3
"""Local productivity governor for the CotS 24x7 autonomous factory.

The governor never calls an AI provider. It watches durable supervisor/repo
signals and trips after several expensive provider turns fail to produce
engineering evidence (file changes, commits, tests, or acceptance proof).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, SUPERVISOR_STATE, atomic_json, fixed_git, read_json, safe_nonnegative_int

STATE = COTS / "productivity-governor.local.json"
DEFAULT_THRESHOLD = 4
DEFAULT_COOLDOWN_SECONDS = 15 * 60


def _list_len(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def evidence_signature(supervisor: dict[str, Any] | None = None) -> dict[str, Any]:
    supervisor = supervisor if isinstance(supervisor, dict) else read_json(SUPERVISOR_STATE)
    context = supervisor.get("compact_task_context") if isinstance(supervisor.get("compact_task_context"), dict) else {}
    efficiency = supervisor.get("efficiency") if isinstance(supervisor.get("efficiency"), dict) else {}
    status = fixed_git("status", "--porcelain=v1")
    return {
        "head": fixed_git("rev-parse", "HEAD").strip(),
        "working_tree": hashlib.sha256(status.encode("utf-8", errors="replace")).hexdigest()[:16],
        "targeted_tests": safe_nonnegative_int(context.get("targeted_tests_run", efficiency.get("targeted_test_runs", 0))),
        "full_suites": safe_nonnegative_int(context.get("full_suites_run", efficiency.get("full_suite_runs", 0))),
        "validation_count": _list_len(context.get("validation_passed")),
        "acceptance_remaining": _list_len(context.get("acceptance_remaining")),
        "last_successful_gate": supervisor.get("last_successful_gate"),
        "task": supervisor.get("task"),
        "phase": supervisor.get("phase"),
    }


def evidence_progressed(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if before.get("head") != after.get("head"):
        reasons.append("commit")
    if before.get("working_tree") != after.get("working_tree"):
        reasons.append("file_change")
    if safe_nonnegative_int(after.get("targeted_tests")) > safe_nonnegative_int(before.get("targeted_tests")):
        reasons.append("targeted_test")
    if safe_nonnegative_int(after.get("full_suites")) > safe_nonnegative_int(before.get("full_suites")):
        reasons.append("full_suite")
    if safe_nonnegative_int(after.get("validation_count")) > safe_nonnegative_int(before.get("validation_count")):
        reasons.append("acceptance_proof")
    if after.get("last_successful_gate") and after.get("last_successful_gate") != before.get("last_successful_gate"):
        reasons.append("successful_gate")
    if after.get("task") != before.get("task"):
        reasons.append("task_advanced")
    return bool(reasons), reasons


class ProductivityGovernor:
    def __init__(self, threshold: int = DEFAULT_THRESHOLD, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> None:
        self.threshold = max(2, int(threshold))
        self.cooldown_seconds = max(60, int(cooldown_seconds))
        self.data = read_json(STATE, {})
        self.data.setdefault("schema_version", 1)
        self.data.setdefault("unproductive_turns", 0)
        self.data.setdefault("useful_turns", 0)
        self.data.setdefault("observed_turns", 0)
        self.data.setdefault("commits", 0)
        self.data.setdefault("tests", 0)
        self.data.setdefault("acceptance_proofs", 0)
        self.data.setdefault("trips", 0)
        self.data.setdefault("cooldown_until", None)
        supervisor = read_json(SUPERVISOR_STATE)
        self.data.setdefault("last_turn_count", safe_nonnegative_int(supervisor.get("turn_count"), 0))
        self.data.setdefault("last_evidence", evidence_signature(supervisor))
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = time.time()
        atomic_json(STATE, self.data)

    def reset_streak(self, reason: str = "manual") -> None:
        self.data["unproductive_turns"] = 0
        self.data["cooldown_until"] = None
        self.data["last_reset_reason"] = reason
        self.data["last_evidence"] = evidence_signature()
        self.data["last_turn_count"] = safe_nonnegative_int(read_json(SUPERVISOR_STATE).get("turn_count"), 0)
        self.save()

    def observe(self, supervisor: dict[str, Any] | None = None) -> dict[str, Any]:
        supervisor = supervisor if isinstance(supervisor, dict) else read_json(SUPERVISOR_STATE)
        turn_count = safe_nonnegative_int(supervisor.get("turn_count"), 0)
        previous_turn = safe_nonnegative_int(self.data.get("last_turn_count"), turn_count)

        # Supervisor generations may legitimately start a new local turn
        # counter. Re-baseline instead of permanently ignoring all future turns.
        if turn_count < previous_turn:
            self.data["last_turn_count"] = turn_count
            self.data["last_evidence"] = evidence_signature(supervisor)
            self.data["last_counter_reset_at"] = time.time()
            self.save()
            return self.snapshot()
        if turn_count == previous_turn:
            return self.snapshot()

        before = self.data.get("last_evidence") if isinstance(self.data.get("last_evidence"), dict) else evidence_signature(supervisor)
        after = evidence_signature(supervisor)
        progressed, reasons = evidence_progressed(before, after)
        delta = max(1, turn_count - previous_turn)
        self.data["observed_turns"] = safe_nonnegative_int(self.data.get("observed_turns")) + delta
        if progressed:
            self.data["useful_turns"] = safe_nonnegative_int(self.data.get("useful_turns")) + 1
            self.data["unproductive_turns"] = 0
            if "commit" in reasons: self.data["commits"] = safe_nonnegative_int(self.data.get("commits")) + 1
            if "targeted_test" in reasons or "full_suite" in reasons: self.data["tests"] = safe_nonnegative_int(self.data.get("tests")) + 1
            if "acceptance_proof" in reasons or "successful_gate" in reasons: self.data["acceptance_proofs"] = safe_nonnegative_int(self.data.get("acceptance_proofs")) + 1
            self.data["last_productive_at"] = time.time()
            self.data["last_productive_reasons"] = reasons
        else:
            self.data["unproductive_turns"] = safe_nonnegative_int(self.data.get("unproductive_turns")) + delta
            self.data["last_unproductive_at"] = time.time()

        self.data["last_turn_count"] = turn_count
        self.data["last_evidence"] = after
        if safe_nonnegative_int(self.data.get("unproductive_turns")) >= self.threshold:
            if not isinstance(self.data.get("cooldown_until"), (int, float)) or self.data["cooldown_until"] <= time.time():
                self.data["trips"] = safe_nonnegative_int(self.data.get("trips")) + 1
                self.data["last_trip_at"] = time.time()
                self.data["cooldown_until"] = time.time() + self.cooldown_seconds
                self.data["trip_reason"] = f"{self.data['unproductive_turns']} provider turns without durable engineering evidence"
        self.save()
        return self.snapshot()

    def tripped(self) -> bool:
        return (
            safe_nonnegative_int(self.data.get("unproductive_turns")) >= self.threshold
            and isinstance(self.data.get("cooldown_until"), (int, float))
            and float(self.data["cooldown_until"]) > time.time()
        )

    def snapshot(self) -> dict[str, Any]:
        observed = safe_nonnegative_int(self.data.get("observed_turns"))
        useful = safe_nonnegative_int(self.data.get("useful_turns"))
        return {
            **self.data,
            "threshold": self.threshold,
            "productive_ratio": (useful / observed) if observed else None,
            "tripped": self.tripped(),
        }


if __name__ == "__main__":
    governor = ProductivityGovernor()
    print(json.dumps(governor.observe(), indent=2, default=str))
