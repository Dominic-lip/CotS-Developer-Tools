#!/usr/bin/env python3
"""Persistent zero-provider-cost circuit breaker for repeated CotS gates.

A restart is only useful when some relevant input/evidence changed. This guard
fingerprints structured supervisor gates across Factory generations and blocks
provider re-entry after the same gate is observed twice with identical durable
engineering evidence in either DeveloperTools or the production CotS tree.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from CotS24x7Common import COTS, SUPERVISOR_STATE, atomic_json, clean_text, fixed_git, read_json, safe_nonnegative_int

STATE = COTS / "loop-guard.local.json"
PRODUCTION = Path(r"C:\Dev\CotS")
DEFAULT_THRESHOLD = 2
GATE_STATES = frozenset({
    "RECOVERABLE_GATE", "HUMAN_GATE", "HUMAN_REQUIRED", "FAILED",
    "TERMINAL_FAILURE", "GOVERNOR_PAUSED",
})


def _list_len(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _normal_reason(value: object) -> str:
    return " ".join(clean_text(value, 900).lower().split())


def _production_git(*args: str) -> str:
    if not (PRODUCTION / ".git").exists():
        return ""
    try:
        result = subprocess.run(["git", *args], cwd=PRODUCTION, text=True, capture_output=True, timeout=15, check=False)
        return (result.stdout + result.stderr).strip()[-12000:]
    except Exception:
        return ""


def gate_descriptor(supervisor: dict[str, Any] | None = None) -> dict[str, str] | None:
    supervisor = supervisor if isinstance(supervisor, dict) else read_json(SUPERVISOR_STATE)
    state = str(supervisor.get("state") or "")
    structured = supervisor.get("recoverable_gate")
    if isinstance(structured, dict):
        category = str(structured.get("category") or "RECOVERABLE_GATE")
        reason = _normal_reason(structured.get("reason") or supervisor.get("current_action") or "recoverable gate")
    elif state in GATE_STATES:
        category = state
        reason = _normal_reason(
            supervisor.get("human_gate")
            or supervisor.get("failure")
            or supervisor.get("current_action")
            or state
        )
    else:
        return None
    if not reason:
        reason = state.lower() or "gate"
    return {
        "state": state,
        "category": category,
        "reason": reason,
        "task": str(supervisor.get("task") or ""),
        "phase": str(supervisor.get("phase") or ""),
    }


def gate_fingerprint(gate: dict[str, str] | None) -> str | None:
    if not gate:
        return None
    material = "|".join((gate.get("category", ""), gate.get("reason", ""), gate.get("task", ""), gate.get("phase", "")))
    return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()[:20]


def durable_evidence(supervisor: dict[str, Any] | None = None) -> dict[str, Any]:
    supervisor = supervisor if isinstance(supervisor, dict) else read_json(SUPERVISOR_STATE)
    context = supervisor.get("compact_task_context") if isinstance(supervisor.get("compact_task_context"), dict) else {}
    efficiency = supervisor.get("efficiency") if isinstance(supervisor.get("efficiency"), dict) else {}
    status = fixed_git("status", "--porcelain=v1")
    production_status = _production_git("status", "--porcelain=v1")
    production_exists = (PRODUCTION / "CotS.uproject").is_file()
    return {
        "head": fixed_git("rev-parse", "HEAD").strip(),
        "working_tree": hashlib.sha256(status.encode("utf-8", errors="replace")).hexdigest()[:20],
        "production_exists": production_exists,
        "production_head": _production_git("rev-parse", "HEAD") if (PRODUCTION / ".git").exists() else "",
        "production_working_tree": hashlib.sha256(production_status.encode("utf-8", errors="replace")).hexdigest()[:20] if (PRODUCTION / ".git").exists() else ("present" if production_exists else "absent"),
        "task": str(supervisor.get("task") or ""),
        "phase": str(supervisor.get("phase") or ""),
        "targeted_tests": safe_nonnegative_int(context.get("targeted_tests_run", efficiency.get("targeted_test_runs", 0))),
        "full_suites": safe_nonnegative_int(context.get("full_suites_run", efficiency.get("full_suite_runs", 0))),
        "validation_count": _list_len(context.get("validation_passed")),
        "acceptance_remaining": _list_len(context.get("acceptance_remaining")),
    }


def evidence_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:20]


def durable_progress(before: dict[str, Any], after: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if before.get("head") and after.get("head") and before.get("head") != after.get("head"):
        reasons.append("commit")
    if before.get("working_tree") != after.get("working_tree"):
        reasons.append("file_change")
    if not before.get("production_exists") and after.get("production_exists"):
        reasons.append("production_bootstrap")
    if before.get("production_head") != after.get("production_head") and after.get("production_head"):
        reasons.append("production_commit")
    if before.get("production_working_tree") != after.get("production_working_tree"):
        reasons.append("production_file_change")
    if safe_nonnegative_int(after.get("targeted_tests")) > safe_nonnegative_int(before.get("targeted_tests")):
        reasons.append("targeted_test")
    if safe_nonnegative_int(after.get("full_suites")) > safe_nonnegative_int(before.get("full_suites")):
        reasons.append("full_suite")
    if safe_nonnegative_int(after.get("validation_count")) > safe_nonnegative_int(before.get("validation_count")):
        reasons.append("acceptance_proof")
    before_remaining = safe_nonnegative_int(before.get("acceptance_remaining"), 0)
    after_remaining = safe_nonnegative_int(after.get("acceptance_remaining"), 0)
    if before_remaining and after_remaining < before_remaining:
        reasons.append("acceptance_reduced")
    if before.get("task") and after.get("task") and before.get("task") != after.get("task"):
        reasons.append("task_advanced")
    return bool(reasons), reasons


def configuration_like(reason: str) -> bool:
    lowered = _normal_reason(reason)
    terms = (
        "not configured", "no configured", "missing adapter", "prerequisite missing",
        "permission boundary", "outside this session", "configuration required",
        "unsupported lifecycle", "adapter missing",
    )
    return any(term in lowered for term in terms)


class LoopGuard:
    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.threshold = max(2, int(threshold))
        self.data = read_json(STATE, {})
        self.data.setdefault("schema_version", 1)
        self.data.setdefault("repeat_count", 0)
        self.data.setdefault("blocked", False)
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = time.time()
        atomic_json(STATE, self.data)

    def snapshot(self) -> dict[str, Any]:
        return {**self.data, "threshold": self.threshold}

    def clear(self, reason: str = "relevant state changed") -> None:
        self.data.update({
            "last_fingerprint": None,
            "last_evidence_hash": None,
            "repeat_count": 0,
            "blocked": False,
            "blocked_fingerprint": None,
            "blocked_evidence_hash": None,
            "blocked_reason": None,
            "last_clear_reason": reason,
        })
        self.save()

    def observe(
        self,
        supervisor: dict[str, Any] | None,
        before_evidence: dict[str, Any],
        after_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        supervisor = supervisor if isinstance(supervisor, dict) else {}
        gate = gate_descriptor(supervisor)
        progressed, progress_reasons = durable_progress(before_evidence, after_evidence)
        if gate is None:
            if self.data.get("blocked") and evidence_hash(after_evidence) != self.data.get("blocked_evidence_hash"):
                self.clear("gate disappeared after durable state change")
            return {"blocked": False, "gate": None, "durable_progress": progressed, "progress_reasons": progress_reasons}

        fingerprint = gate_fingerprint(gate)
        current_evidence_hash = evidence_hash(after_evidence)
        same = (
            fingerprint == self.data.get("last_fingerprint")
            and current_evidence_hash == self.data.get("last_evidence_hash")
            and not progressed
        )
        repeat_count = safe_nonnegative_int(self.data.get("repeat_count"), 0) + 1 if same else 1
        blocked = repeat_count >= self.threshold and not progressed
        self.data.update({
            "last_fingerprint": fingerprint,
            "last_evidence_hash": current_evidence_hash,
            "repeat_count": repeat_count,
            "last_gate": gate,
            "last_seen_at": time.time(),
            "blocked": blocked,
        })
        if blocked:
            self.data.update({
                "blocked_fingerprint": fingerprint,
                "blocked_evidence_hash": current_evidence_hash,
                "blocked_reason": gate.get("reason"),
                "blocked_task": gate.get("task"),
                "blocked_phase": gate.get("phase"),
                "blocked_at": time.time(),
                "blocked_kind": "configuration" if configuration_like(gate.get("reason", "")) else "repeated_gate",
            })
        self.save()
        return {
            "blocked": blocked,
            "gate": gate,
            "fingerprint": fingerprint,
            "repeat_count": repeat_count,
            "durable_progress": progressed,
            "progress_reasons": progress_reasons,
            "blocked_kind": self.data.get("blocked_kind") if blocked else None,
        }

    def condition_changed(self, supervisor: dict[str, Any] | None = None) -> bool:
        if not self.data.get("blocked"):
            return True
        current = durable_evidence(supervisor)
        current_gate = gate_descriptor(supervisor)
        return (
            evidence_hash(current) != self.data.get("blocked_evidence_hash")
            or gate_fingerprint(current_gate) != self.data.get("blocked_fingerprint")
        )


if __name__ == "__main__":
    guard = LoopGuard()
    current = read_json(SUPERVISOR_STATE)
    evidence = durable_evidence(current)
    print(json.dumps(guard.observe(current, evidence, evidence), indent=2, default=str))
